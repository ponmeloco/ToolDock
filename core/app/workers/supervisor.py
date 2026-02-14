from __future__ import annotations

import asyncio
import hashlib
import os
import signal
import subprocess
import sys
import time
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import CoreSettings
from app.registry.models import NamespaceInfo
from app.workers.protocol import WorkerError
from app.workers.rpc import WorkerRPCClient


@dataclass(slots=True)
class WorkerRuntime:
    namespace: str
    socket_path: Path
    host: str
    port: int
    process: asyncio.subprocess.Process
    signature: str
    semaphore: asyncio.Semaphore


class WorkerSupervisor:
    def __init__(self, settings: CoreSettings):
        self._settings = settings
        self._data_dir = Path(settings.data_dir)
        self._venvs_dir = self._data_dir / "venvs"
        self._workers_dir = self._data_dir / "workers"
        self._project_root = Path(__file__).resolve().parents[2]

        self._namespaces: dict[str, NamespaceInfo] = {}
        self._env_by_ns: dict[str, dict[str, str]] = {}
        self._workers: dict[str, WorkerRuntime] = {}
        self._lock = asyncio.Lock()

        self._venvs_dir.mkdir(parents=True, exist_ok=True)
        self._workers_dir.mkdir(parents=True, exist_ok=True)

    async def apply_snapshot(
        self,
        namespaces: dict[str, NamespaceInfo],
        env_by_ns: dict[str, dict[str, str]],
    ) -> dict[str, list[str]]:
        restarted: list[str] = []
        synced: list[str] = []

        async with self._lock:
            removed = set(self._workers) - set(namespaces)
            for ns in sorted(removed):
                await self._stop_worker(ns)

            self._namespaces = namespaces
            self._env_by_ns = env_by_ns

            for ns, info in sorted(namespaces.items()):
                env = env_by_ns.get(ns, {})
                signature = self._namespace_signature(info, env)
                runtime = self._workers.get(ns)
                if runtime and runtime.signature == signature and runtime.process.returncode is None:
                    continue

                did_sync = await self._ensure_namespace_venv(info)
                if did_sync:
                    synced.append(ns)

                await self._start_or_restart_worker(ns, signature)
                restarted.append(ns)

        return {"workers_restarted": restarted, "deps_synced": synced}

    async def list_tools(self, namespace: str) -> list[dict[str, Any]]:
        payload = await self._request(namespace, {"id": _request_id(), "op": "tools.list"})
        return payload["result"]

    async def get_schema(self, namespace: str, tool_name: str) -> dict[str, Any]:
        payload = await self._request(
            namespace,
            {"id": _request_id(), "op": "tools.get_schema", "tool": tool_name},
        )
        return payload["result"]

    async def call_tool(self, namespace: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        payload = await self._request(
            namespace,
            {
                "id": _request_id(),
                "op": "tools.call",
                "tool": tool_name,
                "arguments": arguments,
            },
        )
        return payload["result"]

    async def shutdown(self) -> None:
        async with self._lock:
            for ns in sorted(list(self._workers.keys())):
                await self._stop_worker(ns)

    async def _request(self, namespace: str, request: dict[str, Any]) -> dict[str, Any]:
        if namespace not in self._namespaces:
            raise WorkerError("namespace_not_found", f"Unknown namespace: {namespace}")

        async with self._lock:
            runtime = self._workers.get(namespace)
            if runtime is None or runtime.process.returncode is not None:
                signature = self._namespace_signature(self._namespaces[namespace], self._env_by_ns.get(namespace, {}))
                await self._start_or_restart_worker(namespace, signature)
                runtime = self._workers[namespace]

        async with runtime.semaphore:
            client = WorkerRPCClient(
                runtime.socket_path,
                timeout_seconds=self._settings.tool_call_timeout_seconds,
                host=runtime.host,
                port=runtime.port,
            )
            response = await client.request(request)

        if response.get("ok"):
            return response

        err = response.get("error") or {}
        raise WorkerError(
            str(err.get("code", "internal_error")),
            str(err.get("message", "Worker call failed")),
            err.get("details"),
        )

    async def _start_or_restart_worker(self, namespace: str, signature: str) -> None:
        await self._stop_worker(namespace)

        info = self._namespaces[namespace]
        socket_path = self._workers_dir / f"{namespace}.sock"
        if socket_path.exists():
            socket_path.unlink(missing_ok=True)

        venv_python = self._venvs_dir / namespace / "bin" / "python"
        python_bin = venv_python if venv_python.exists() else Path(sys.executable)
        host = "127.0.0.1"
        port = _port_for_namespace(namespace)

        env = os.environ.copy()
        env.update(self._env_by_ns.get(namespace, {}))
        env["PYTHONPATH"] = str(self._project_root)

        process = await asyncio.create_subprocess_exec(
            str(python_bin),
            "-m",
            "app.worker_main",
            "--namespace",
            namespace,
            "--socket",
            str(socket_path),
            "--host",
            host,
            "--port",
            str(port),
            "--tools-dir",
            str(info.path),
            cwd=str(self._project_root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        runtime = WorkerRuntime(
            namespace=namespace,
            socket_path=socket_path,
            host=host,
            port=port,
            process=process,
            signature=signature,
            semaphore=asyncio.Semaphore(self._settings.namespace_max_concurrency),
        )
        self._workers[namespace] = runtime

        await self._wait_until_ready(runtime)

    async def _wait_until_ready(self, runtime: WorkerRuntime) -> None:
        deadline = time.monotonic() + max(self._settings.tool_call_timeout_seconds, 10)
        client = WorkerRPCClient(runtime.socket_path, timeout_seconds=2, host=runtime.host, port=runtime.port)

        while time.monotonic() < deadline:
            if runtime.process.returncode is None:
                try:
                    await asyncio.wait_for(runtime.process.wait(), timeout=0.01)
                except TimeoutError:
                    pass

            if runtime.process.returncode is not None:
                stdout, stderr = await runtime.process.communicate()
                raise WorkerError(
                    "worker_crashed",
                    f"Worker exited before ready (code={runtime.process.returncode})",
                    {
                        "stdout": stdout.decode("utf-8", errors="replace")[-1000:],
                        "stderr": stderr.decode("utf-8", errors="replace")[-1000:],
                    },
                )
            try:
                response = await client.request({"id": _request_id(), "op": "ping"})
                if response.get("ok"):
                    return
            except WorkerError:
                pass
            await asyncio.sleep(0.1)

        raise WorkerError("worker_timeout", f"Worker for {runtime.namespace} did not become ready")

    async def _stop_worker(self, namespace: str) -> None:
        runtime = self._workers.pop(namespace, None)
        if runtime is None:
            return

        try:
            client = WorkerRPCClient(runtime.socket_path, timeout_seconds=1, host=runtime.host, port=runtime.port)
            await client.request({"id": _request_id(), "op": "shutdown"})
        except Exception:
            pass

        if runtime.process.returncode is None:
            runtime.process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(runtime.process.wait(), timeout=3)
            except TimeoutError:
                runtime.process.kill()
                await runtime.process.wait()

        runtime.socket_path.unlink(missing_ok=True)

    def _namespace_signature(self, info: NamespaceInfo, env: dict[str, str]) -> str:
        hasher = hashlib.sha256()
        hasher.update((info.requirements_hash or "").encode("utf-8"))
        for py_file in sorted(info.path.glob("*.py"), key=lambda p: p.name):
            stat = py_file.stat()
            hasher.update(py_file.name.encode("utf-8"))
            hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
            hasher.update(str(stat.st_size).encode("utf-8"))
        for key in sorted(env):
            hasher.update(key.encode("utf-8"))
            hasher.update(str(env[key]).encode("utf-8"))
        return hasher.hexdigest()

    async def _ensure_namespace_venv(self, info: NamespaceInfo) -> bool:
        # Keep venv sync deterministic; thread offloading caused hangs in restricted runtimes.
        return self._sync_venv_blocking(info)

    def _sync_venv_blocking(self, info: NamespaceInfo) -> bool:
        ns = info.name
        venv_dir = self._venvs_dir / ns
        req_file = info.requirements_path
        python_bin = venv_dir / "bin" / "python"
        if (not python_bin.exists()) or (not self._venv_has_system_site_packages(venv_dir)):
            # Avoid slow ensurepip work when namespace has no external requirements.
            # Expose core runtime packages (for example fastmcp decorators) to namespace workers
            # while still allowing namespace-specific installs in the venv itself.
            venv.create(venv_dir, with_pip=bool(req_file), clear=venv_dir.exists(), system_site_packages=True)
            python_bin = venv_dir / "bin" / "python"

        stamp_file = venv_dir / ".requirements.sha256"

        if req_file is None:
            if stamp_file.exists():
                stamp_file.unlink(missing_ok=True)
            return False

        req_hash = info.requirements_hash or ""
        old_hash = stamp_file.read_text(encoding="utf-8").strip() if stamp_file.exists() else ""
        if req_hash == old_hash:
            return False

        subprocess.run(
            [str(python_bin), "-m", "ensurepip", "--upgrade"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            [str(python_bin), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req_file)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stamp_file.write_text(req_hash, encoding="utf-8")
        return True

    def _venv_has_system_site_packages(self, venv_dir: Path) -> bool:
        cfg = venv_dir / "pyvenv.cfg"
        if not cfg.exists():
            return False
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("include-system-site-packages"):
                _, _, value = line.partition("=")
                return value.strip().lower() == "true"
        return False


def _request_id() -> str:
    return f"req-{time.time_ns()}"


def _port_for_namespace(namespace: str) -> int:
    # Stable loopback port per namespace to allow worker fallback when Unix sockets are unavailable.
    digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
    return 30000 + (int(digest[:4], 16) % 20000)
