"""FastMCP external server manager (registry -> install -> run)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import select

from app.db.database import get_db
from app.db.models import ExternalFastMCPServer, ExternalRegistryCache
from app.deps import ensure_venv, install_packages, install_requirements, get_venv_dir
from app.external.fastmcp_proxy import FastMCPHttpProxy
from app.external.registry_client import MCPRegistryClient
from app.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_PORT_START = 19000
DEFAULT_PORT_END = 19999


class FastMCPServerManager:
    """Manages FastMCP servers and registry sync."""

    def __init__(self, registry: ToolRegistry, manage_processes: bool = False):
        self.registry = registry
        self.manage_processes = manage_processes
        self._proxies: Dict[int, FastMCPHttpProxy] = {}

    # =========================
    # Registry helpers
    # =========================

    async def list_registry_servers(self, limit: int = 30, cursor: str | None = None, search: str | None = None):
        client = MCPRegistryClient()
        result = await client.list_servers(limit=limit, cursor=cursor, search=search)
        servers = result.get("servers", [])

        def is_installable(entry: Dict[str, Any]) -> bool:
            pkg = _pick_package(entry)
            repo_url = _extract_repo_url(entry)
            if pkg is None:
                return repo_url is not None
            registry_type = str(pkg.get("registryType", "")).lower()
            if registry_type == "pypi":
                return True
            return repo_url is not None

        filtered = [s for s in servers if is_installable(s)]
        normalized: list[Dict[str, Any]] = []
        for entry in filtered:
            server = entry.get("server", entry)
            if isinstance(server, dict):
                name = server.get("name") or entry.get("name")
                description = server.get("description") or entry.get("description")
                server_id = server.get("id") or entry.get("id")
                if name:
                    entry = dict(entry)
                    entry["name"] = name
                    if description:
                        entry["description"] = description
                    if server_id:
                        entry["id"] = server_id
            normalized.append(entry)
        if filtered != servers:
            result = dict(result)
            result["servers"] = normalized
            metadata = dict(result.get("metadata") or {})
            metadata["filtered"] = True
            metadata["filtered_out"] = len(servers) - len(filtered)
            result["metadata"] = metadata
        else:
            result = dict(result)
            result["servers"] = normalized
        return result

    async def get_registry_server(self, name: Optional[str] = None, server_id: Optional[str] = None) -> Dict[str, Any]:
        client = MCPRegistryClient()
        data: Optional[Dict[str, Any]] = None
        if server_id:
            data = await client.get_server_by_id(server_id)
        elif name:
            data = await client.get_server_by_name(name)
        if not data:
            identifier = server_id or name or "unknown"
            raise ValueError(f"Registry server not found: {identifier}")
        return data

    def _cache_registry_server(self, name: str, data: Dict[str, Any]) -> None:
        with get_db() as db:
            record = db.get(ExternalRegistryCache, name)
            if record is None:
                record = ExternalRegistryCache(server_name=name, metadata_json=data)
                db.add(record)
            else:
                record.metadata_json = data
            record.latest_version = _get_latest_version(data)
            db.commit()

    # =========================
    # Install / Start / Stop
    # =========================

    async def add_server_from_registry(
        self,
        server_name: Optional[str],
        namespace: str,
        version: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> ExternalFastMCPServer:
        data = await self.get_registry_server(server_name, server_id=server_id)
        resolved_name = _get_server_name(data) or server_name or server_id or "unknown"
        self._cache_registry_server(resolved_name, data)

        pkg = _pick_package(data)
        repo_url = _extract_repo_url(data)

        install_method = "package" if pkg else "repo"
        if install_method == "package" and pkg and pkg.get("registryType", "").lower() != "pypi":
            # For FastMCP, prefer repo fallback if package isn't pypi.
            if repo_url:
                install_method = "repo"
                pkg = None
            else:
                raise ValueError("Unsupported package type for FastMCP (only PyPI or repo)")

        if install_method == "repo" and not repo_url:
            raise ValueError("Registry server has no repo URL and no PyPI package")

        with get_db() as db:
            existing = db.execute(
                select(ExternalFastMCPServer).where(ExternalFastMCPServer.namespace == namespace)
            ).scalar_one_or_none()
            if existing:
                raise ValueError(f"Namespace already exists: {namespace}")

            record = ExternalFastMCPServer(
                server_name=resolved_name,
                namespace=namespace,
                version=version or _get_latest_version(data),
                install_method=install_method,
                package_info=pkg,
                repo_url=repo_url,
                status="installing",
            )
            db.add(record)
            db.commit()
            db.refresh(record)

        # Install immediately
        try:
            await asyncio.to_thread(self._install_server, record.id)
        except Exception as exc:
            with get_db() as db:
                record = db.get(ExternalFastMCPServer, record.id)
                if record:
                    record.status = "error"
                    record.last_error = str(exc)
                    db.commit()
            raise

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, record.id)
            if record:
                return record

        raise RuntimeError("Failed to load server after install")

    def _install_server(self, server_id: int) -> None:
        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            if not record:
                raise ValueError("Server not found")

            namespace = record.namespace
            venv_dir = ensure_venv(namespace)
            record.venv_path = str(venv_dir)

            # Ensure mcp CLI is available in venv
            result = install_packages(namespace, ["mcp"])
            if not result.get("success"):
                raise RuntimeError(result.get("stderr") or "Failed to install mcp")

            if record.install_method == "package":
                pkg = record.package_info or {}
                identifier = pkg.get("identifier")
                version = record.version or pkg.get("version")
                if not identifier:
                    raise ValueError("Missing package identifier")
                spec = f"{identifier}=={version}" if version else identifier
                result = install_packages(namespace, [spec])
                if not result.get("success"):
                    raise RuntimeError(result.get("stderr") or "Failed to install package")

                # Resolve entrypoint from installed package (best-effort)
                entrypoint = _find_entrypoint_from_package(namespace)
                if not entrypoint and record.repo_url:
                    # Fallback to repo if package doesn't expose an entrypoint
                    repo_path = _ensure_repo(namespace, record.repo_url)
                    entrypoint_path = _detect_entrypoint(repo_path)
                    _install_repo_deps(namespace, repo_path)
                    if entrypoint_path:
                        record.entrypoint = str(entrypoint_path)
                        record.install_method = "repo"
                        record.status = "installed"
                    else:
                        record.status = "error"
                        record.last_error = "No FastMCP entrypoint found in package or repo"
                elif not entrypoint:
                    record.status = "error"
                    record.last_error = "No FastMCP entrypoint found in package"
                else:
                    record.entrypoint = entrypoint
                    record.status = "installed"

            else:
                repo_path = _ensure_repo(namespace, record.repo_url)
                entrypoint = _detect_entrypoint(repo_path)

                # Install dependencies
                _install_repo_deps(namespace, repo_path)

                if not entrypoint:
                    record.status = "error"
                    record.last_error = "No FastMCP entrypoint found in repo"
                else:
                    record.entrypoint = str(entrypoint)
                    record.status = "installed"

            db.commit()

    def start_server(self, server_id: int) -> ExternalFastMCPServer:
        if not self.manage_processes:
            raise RuntimeError("Process management disabled in this context")

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            if not record:
                raise ValueError("Server not found")
            if record.status == "running":
                return record
            if not record.entrypoint:
                raise ValueError("Missing entrypoint; install may have failed")

            port = record.port or _find_free_port()
            record.port = port

            log_path = _get_logs_dir() / f"{record.namespace}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "a", encoding="utf-8")

            env = os.environ.copy()
            env["FASTMCP_HOST"] = "127.0.0.1"
            env["FASTMCP_PORT"] = str(port)
            env["FASTMCP_STREAMABLE_HTTP_PATH"] = "/mcp"

            cmd = _build_run_command(record)
            logger.info(f"Starting FastMCP server {record.namespace}: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                cwd=_entrypoint_cwd(record.entrypoint),
                env=env,
                stdout=log_file,
                stderr=log_file,
            )

            record.pid = process.pid
            record.status = "running"
            record.last_error = None
            db.commit()
            db.refresh(record)
            return record

    def stop_server(self, server_id: int) -> ExternalFastMCPServer:
        if not self.manage_processes:
            raise RuntimeError("Process management disabled in this context")

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            if not record:
                raise ValueError("Server not found")

            if record.pid:
                _terminate_pid(record.pid)

            record.pid = None
            record.status = "stopped"
            db.commit()
            db.refresh(record)
            return record

    def delete_server(self, server_id: int) -> None:
        if not self.manage_processes:
            raise RuntimeError("Process management disabled in this context")

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            if not record:
                return
            if record.pid:
                _terminate_pid(record.pid)
            db.delete(record)
            db.commit()

        # Optionally cleanup repo folder
        repo_path = _get_server_dir(record.namespace)
        if repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)

    # =========================
    # Sync running servers into registry
    # =========================

    async def sync_from_db(self) -> Dict[str, Any]:
        running: Dict[int, ExternalFastMCPServer] = {}
        with get_db() as db:
            rows = db.execute(
                select(ExternalFastMCPServer).where(ExternalFastMCPServer.status == "running")
            ).scalars().all()
            for row in rows:
                running[row.id] = row

        # Remove proxies for stopped servers
        to_remove = [sid for sid in self._proxies.keys() if sid not in running]
        for sid in to_remove:
            proxy = self._proxies.pop(sid)
            await proxy.disconnect()
            self.registry.unregister_external_server(str(sid))

        # Connect and register tools for running servers
        for sid, record in running.items():
            if sid in self._proxies:
                continue

            if not record.port:
                logger.warning(f"FastMCP server {record.namespace} missing port; skipping")
                continue

            url = f"http://127.0.0.1:{record.port}/mcp"
            proxy = FastMCPHttpProxy(str(sid), url)
            await proxy.connect()

            # Register tools
            for tool in proxy.get_tool_schemas(record.namespace):
                self.registry.register_external_tool(
                    name=tool["name"],
                    description=tool["description"],
                    schema=tool["inputSchema"],
                    server_id=str(sid),
                    original_name=tool["original_name"],
                    proxy=proxy,
                    namespace=record.namespace,
                )

            self._proxies[sid] = proxy

        return {"running": len(running), "connected": len(self._proxies)}


# =========================
# Helpers
# =========================


def _get_data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "tooldock_data"))


def _get_server_dir(namespace: str) -> Path:
    return _get_data_dir() / "external" / "servers" / namespace


def _get_logs_dir() -> Path:
    return _get_data_dir() / "external" / "logs"


def _ensure_repo(namespace: str, repo_url: Optional[str]) -> Path:
    if not repo_url:
        raise ValueError("Missing repo URL")

    repo_dir = _get_server_dir(namespace)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists() and (repo_dir / ".git").exists():
        _run_cmd(["git", "-C", str(repo_dir), "pull", "--ff-only"])
    else:
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        _run_cmd(["git", "clone", repo_url, str(repo_dir)])

    return repo_dir


def _install_repo_deps(namespace: str, repo_dir: Path) -> None:
    req = repo_dir / "requirements.txt"
    if req.exists():
        result = install_requirements(namespace, req.read_text())
        if not result.get("success"):
            raise RuntimeError(result.get("stderr") or "Failed to install requirements")
        return

    pyproject = repo_dir / "pyproject.toml"
    setup_py = repo_dir / "setup.py"
    if pyproject.exists() or setup_py.exists():
        venv_dir = get_venv_dir(namespace)
        python_path = venv_dir / "bin" / "python"
        cmd = [str(python_path), "-m", "pip", "install", "-e", str(repo_dir)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return


def _detect_entrypoint(repo_dir: Path) -> Optional[Path]:
    fastmcp_json = repo_dir / "fastmcp.json"
    if fastmcp_json.exists():
        try:
            data = json.loads(fastmcp_json.read_text())
            for key in ["entrypoint", "file", "path", "server_file", "module"]:
                if key in data:
                    candidate = Path(data[key])
                    if not candidate.is_absolute():
                        candidate = repo_dir / candidate
                    if candidate.exists():
                        return candidate
        except Exception:
            pass

    for name in ["server.py", "main.py", "app.py"]:
        candidate = repo_dir / name
        if candidate.exists():
            return candidate
    return None


def _find_entrypoint_from_package(namespace: str) -> Optional[str]:
    # Best-effort: no standard. Return None to require repo fallback or manual override.
    _ = namespace
    return None


def _build_run_command(record: ExternalFastMCPServer) -> list[str]:
    venv_path = Path(record.venv_path or "")
    python_path = venv_path / "bin" / "python"
    if not python_path.exists():
        python_path = Path(os.getenv("PYTHON", "python"))

    return [str(python_path), "-m", "mcp.cli.cli", "run", record.entrypoint, "--transport", "streamable-http"]


def _entrypoint_cwd(entrypoint: str | None) -> Optional[str]:
    if not entrypoint:
        return None
    return str(Path(entrypoint).parent)


def _find_free_port(start: int = DEFAULT_PORT_START, end: int = DEFAULT_PORT_END) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free ports available")


def _run_cmd(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def _terminate_pid(pid: int) -> None:
    try:
        os.kill(pid, 15)
    except ProcessLookupError:
        return


def _get_latest_version(data: Dict[str, Any]) -> Optional[str]:
    server = data.get("server", data)
    return server.get("version")


def _get_server_name(data: Dict[str, Any]) -> Optional[str]:
    server = data.get("server", data)
    name = server.get("name") if isinstance(server, dict) else None
    if name:
        return name
    if isinstance(data, dict):
        return data.get("name")
    return None


def _pick_package(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    server = data.get("server", data)
    packages = server.get("packages") or []
    if not packages:
        return None

    # Prefer PyPI packages
    for pkg in packages:
        if str(pkg.get("registryType", "")).lower() == "pypi":
            return pkg
    return packages[0]


def _extract_repo_url(data: Dict[str, Any]) -> Optional[str]:
    server = data.get("server", data)
    for key in ["repository", "repo", "repo_url", "source", "source_url", "url"]:
        value = server.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("repository")
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None
