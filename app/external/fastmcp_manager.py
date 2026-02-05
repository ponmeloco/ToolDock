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
from app.deps import ensure_venv, install_packages, install_requirements, get_venv_dir, validate_npm_package
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

    async def seed_demo_server(self) -> None:
        """
        Install and start a demo FastMCP server on first run.
        Controlled by FASTMCP_DEMO_ENABLED (default true).
        """
        if os.getenv("FASTMCP_DEMO_ENABLED", "true").lower() not in {"1", "true", "yes"}:
            return

        data_dir = _get_data_dir()
        marker = data_dir / "external" / ".fastmcp_demo_seeded"
        if marker.exists():
            return

        namespace = os.getenv("FASTMCP_DEMO_NAMESPACE", "weather")
        demo_repo = os.getenv(
            "FASTMCP_DEMO_REPO",
            "https://github.com/modelcontextprotocol/servers.git",
        ).strip()
        demo_entrypoint = os.getenv(
            "FASTMCP_DEMO_ENTRYPOINT",
            "src/time/src/mcp_server_time/__init__.py",
        ).strip()
        search_env = os.getenv("FASTMCP_DEMO_SEARCH", "weather,filesystem,github")
        search_terms = [term.strip() for term in search_env.split(",") if term.strip()]

        with get_db() as db:
            existing = db.execute(
                select(ExternalFastMCPServer).where(ExternalFastMCPServer.namespace == namespace)
            ).scalar_one_or_none()
            if existing:
                if not existing.auto_start:
                    existing.auto_start = True
                    db.commit()
                    db.refresh(existing)
                if existing.status != "running":
                    try:
                        self.start_server(existing.id)
                    except Exception as exc:
                        logger.warning(f"FastMCP demo auto-start failed: {exc}")
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("exists")
                return

        client = MCPRegistryClient()

        if demo_repo:
            try:
                record = await self.add_server_from_repo(
                    repo_url=demo_repo,
                    namespace=namespace,
                    entrypoint=demo_entrypoint or None,
                )
                self.start_server(record.id)
                await asyncio.sleep(1.5)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(f"{demo_repo}\n")
                logger.info(
                    f"FastMCP demo server installed from repo: {demo_repo} (namespace={namespace})"
                )
                return
            except Exception as exc:
                logger.warning(f"FastMCP demo repo install failed: {exc}")

        def pick_candidate(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            server = entry.get("server", entry)
            if not isinstance(server, dict):
                return None
            server_id = server.get("id") or entry.get("id")
            server_name = server.get("name") or entry.get("name")
            if not server_id or not server_name:
                return None
            pkg = _pick_package(entry)
            repo_url = _extract_repo_url(entry)
            if pkg and str(pkg.get("registryType", "")).lower() not in ("pypi", "npm") and not repo_url:
                return None
            return {"id": str(server_id), "name": str(server_name)}

        candidate = None
        for term in search_terms:
            try:
                result = await client.list_servers(limit=20, search=term)
                servers = result.get("servers", [])
            except Exception as exc:
                logger.warning(f"FastMCP demo registry search failed for '{term}': {exc}")
                continue

            for entry in servers:
                candidate = pick_candidate(entry)
                if candidate:
                    break
            if candidate:
                break

        if not candidate:
            try:
                result = await client.list_servers(limit=100)
                servers = result.get("servers", [])
                for entry in servers:
                    candidate = pick_candidate(entry)
                    if candidate:
                        break
            except Exception as exc:
                logger.warning(f"FastMCP demo registry fallback failed: {exc}")

        if not candidate:
            logger.warning("FastMCP demo server not found in registry search results")
            return

        try:
            record = await self.add_server_from_registry(
                server_name=candidate["name"],
                namespace=namespace,
                server_id=candidate["id"],
            )
            self.start_server(record.id)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(f"{candidate['name']}\n")
            logger.info(f"FastMCP demo server installed: {candidate['name']} (namespace={namespace})")
        except Exception as exc:
            logger.warning(f"FastMCP demo server install failed: {exc}")

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
            if registry_type in ("pypi", "npm"):
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
        if install_method == "package" and pkg and pkg.get("registryType", "").lower() not in ("pypi", "npm"):
            # For unsupported package types, prefer repo fallback.
            if repo_url:
                install_method = "repo"
                pkg = None
            else:
                raise ValueError("Unsupported package type for FastMCP (only PyPI, npm, or repo)")

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

    async def add_server_from_repo(
        self,
        repo_url: str,
        namespace: str,
        entrypoint: Optional[str] = None,
    ) -> ExternalFastMCPServer:
        with get_db() as db:
            existing = db.execute(
                select(ExternalFastMCPServer).where(ExternalFastMCPServer.namespace == namespace)
            ).scalar_one_or_none()
            if existing:
                raise ValueError(f"Namespace already exists: {namespace}")

            record = ExternalFastMCPServer(
                server_name=repo_url,
                namespace=namespace,
                install_method="repo",
                repo_url=repo_url,
                entrypoint=entrypoint,
                status="installing",
                auto_start=True,
            )
            db.add(record)
            db.commit()
            db.refresh(record)

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

            # Ensure server directory exists for config files
            _get_server_dir(namespace).mkdir(parents=True, exist_ok=True)

            if record.install_method == "package":
                pkg = record.package_info or {}
                identifier = pkg.get("identifier")
                version = record.version or pkg.get("version")
                if not identifier:
                    raise ValueError("Missing package identifier")
                registry_type = str(pkg.get("registryType", "")).lower()

                if registry_type == "npm":
                    # npm uses @ for version pinning (e.g. @scope/pkg@1.2.3)
                    spec = f"{identifier}@{version}" if version else identifier
                    validation = validate_npm_package(spec)
                    if not validation.get("success"):
                        raise RuntimeError(
                            validation.get("stderr") or f"npm package not found: {spec}"
                        )
                    record.startup_command = "npx"
                    record.command_args = ["-y", spec]
                    record.status = "stopped"
                else:
                    # PyPI uses == for version pinning (e.g. pkg==1.2.3)
                    spec = f"{identifier}=={version}" if version else identifier
                    venv_dir = ensure_venv(namespace)
                    record.venv_path = str(venv_dir)
                    result = install_packages(namespace, [spec])
                    if not result.get("success"):
                        raise RuntimeError(result.get("stderr") or "Failed to install package")

                    # Pre-fill command from package name
                    module_name = _derive_module_name(identifier)
                    record.startup_command = "python"
                    record.command_args = ["-m", module_name]
                    record.status = "stopped"

            else:
                repo_path = _ensure_repo(namespace, record.repo_url)
                entrypoint = None
                if record.entrypoint:
                    candidate = Path(record.entrypoint)
                    if not candidate.is_absolute():
                        candidate = repo_path / candidate
                    if candidate.exists():
                        entrypoint = candidate

                if entrypoint is None:
                    entrypoint = _detect_entrypoint(repo_path)

                if entrypoint is None:
                    record.status = "error"
                    record.last_error = "No FastMCP entrypoint found in repo"
                else:
                    project_root = _find_repo_project_root(entrypoint, repo_path)
                    _install_repo_deps(namespace, project_root)
                    record.entrypoint = str(entrypoint)
                    record.startup_command = "python"
                    record.command_args = [str(entrypoint)]
                    record.status = "stopped"

            db.commit()

    def start_server(self, server_id: int) -> ExternalFastMCPServer:
        if not self.manage_processes:
            raise RuntimeError("Process management disabled in this context")

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            if not record:
                raise ValueError("Server not found")

            # Check if process is actually alive if status says running
            if record.status == "running" and record.pid:
                if _is_pid_alive(record.pid):
                    return record
                else:
                    # Process died, update status and restart
                    logger.info(f"FastMCP server {record.namespace} process died (PID {record.pid}), restarting...")
                    record.pid = None
                    record.status = "stopped"
                    db.commit()
                    db.refresh(record)
            elif record.status == "running":
                # Status is running but no PID - fix the state
                record.status = "stopped"
                db.commit()
                db.refresh(record)

            # HTTP transport: no process to start, just mark as running
            if record.transport_type == "http" and record.server_url:
                record.status = "running"
                record.last_error = None
                db.commit()
                db.refresh(record)
                return record

            # Validate we have something to run
            if not record.entrypoint and not record.startup_command:
                raise ValueError("Missing entrypoint or startup_command")

            port = record.port or _find_free_port()
            record.port = port

            log_path = _get_logs_dir() / f"{record.namespace}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "a", encoding="utf-8")

            env = os.environ.copy()
            env["FASTMCP_HOST"] = "127.0.0.1"
            env["FASTMCP_PORT"] = str(port)
            env["FASTMCP_STREAMABLE_HTTP_PATH"] = "/mcp"

            # Add custom env vars from database
            if record.env_vars:
                env.update(record.env_vars)

            # Add venv site-packages to PYTHONPATH so server dependencies are available
            site_packages = _get_venv_site_packages(record.venv_path)
            if site_packages:
                existing_path = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = f"{site_packages}:{existing_path}" if existing_path else site_packages

            cmd = _build_run_command(record)
            if not cmd:
                raise ValueError("Could not build run command")

            logger.info(f"Starting FastMCP server {record.namespace}: {' '.join(cmd)}")
            process = subprocess.Popen(
                cmd,
                cwd=_entrypoint_cwd(record.entrypoint, record.namespace),
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
            namespace = record.namespace
            if record.pid:
                _terminate_pid(record.pid)
            db.delete(record)
            db.commit()

        # Optionally cleanup repo folder
        repo_path = _get_server_dir(namespace)
        if repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)

        # Cleanup namespace venv (removes all packages for this namespace)
        try:
            from app.deps import delete_venv
            delete_venv(namespace)
        except Exception as exc:
            logger.warning(f"Failed to delete venv for namespace {namespace}: {exc}")

    # =========================
    # Sync running servers into registry
    # =========================

    async def sync_from_db(self) -> Dict[str, Any]:
        if self.manage_processes:
            with get_db() as db:
                rows = db.execute(
                    select(ExternalFastMCPServer).where(
                        ExternalFastMCPServer.auto_start.is_(True),
                        ExternalFastMCPServer.status.in_(["stopped", "installed"]),
                    )
                ).scalars().all()
                for row in rows:
                    try:
                        self.start_server(row.id)
                    except Exception as exc:
                        logger.warning(f"FastMCP auto-start failed for {row.namespace}: {exc}")

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

            # Determine URL based on transport type
            if record.transport_type == "http" and record.server_url:
                url = record.server_url
            elif record.port:
                url = f"http://127.0.0.1:{record.port}/mcp"
            else:
                logger.warning(f"FastMCP server {record.namespace} missing port/url; skipping")
                continue

            proxy = FastMCPHttpProxy(str(sid), url)
            try:
                for attempt in range(5):
                    try:
                        await proxy.connect()
                        break
                    except Exception as exc:
                        if attempt == 4:
                            raise
                        logger.warning(
                            f"FastMCP server {record.namespace} not ready (attempt {attempt + 1}/5): {exc}"
                        )
                        await asyncio.sleep(0.5)
            except Exception as exc:
                logger.warning(f"FastMCP server {record.namespace} failed to connect: {exc}")
                continue

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


def _find_repo_project_root(entrypoint: Path, repo_dir: Path) -> Path:
    current = entrypoint.parent
    repo_dir = repo_dir.resolve()
    while True:
        if (current / "requirements.txt").exists() or (current / "pyproject.toml").exists() or (current / "setup.py").exists():
            return current
        if current == repo_dir:
            return repo_dir
        parent = current.parent
        if parent == current:
            return repo_dir
        current = parent


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


def _derive_module_name(identifier: str) -> str:
    """Convert a package identifier to a Python module name.

    e.g. ``mcp-server-fetch`` -> ``mcp_server_fetch``
    """
    # Strip any extras specifier (e.g. "mcp[cli]" -> "mcp")
    name = identifier.split("[")[0]
    return name.replace("-", "_")


def _build_run_command(record: ExternalFastMCPServer) -> list[str]:
    """Build the command to run a MCP server via stdio_bridge.

    Uses the stdio_bridge to expose stdio-based MCP servers via HTTP.
    Supports Claude Desktop config format: command, args, env.
    """
    # For http transport, we don't need a command (connects to external URL)
    if record.transport_type == "http" and record.server_url:
        return []

    # Determine the command and args
    command = record.startup_command
    args = record.command_args or []

    venv_path = Path(record.venv_path or "")
    venv_python = venv_path / "bin" / "python"
    has_venv = venv_python.exists()

    # If no explicit command but we have an entrypoint, use python
    if not command and record.entrypoint:
        command = str(venv_python) if has_venv else "python"
        args = [record.entrypoint]

    if not command:
        return []

    # If the command is "python" and we have a venv, use the venv python
    # so installed packages are properly accessible
    if command in ("python", "python3") and has_venv:
        command = str(venv_python)

    # Build the stdio_bridge command
    bridge_path = Path(__file__).parent / "stdio_bridge.py"

    # Use the venv python to run the bridge (or system python as fallback)
    bridge_python = str(venv_python) if has_venv else "python"

    cmd = [
        bridge_python,
        str(bridge_path),
        "--command", command,
        "--args", json.dumps(args),
    ]

    if record.env_vars:
        cmd.extend(["--env", json.dumps(record.env_vars)])

    # Set working directory
    if record.entrypoint:
        cmd.extend(["--cwd", str(Path(record.entrypoint).parent)])
    else:
        server_dir = _get_server_dir(record.namespace)
        if server_dir.exists():
            cmd.extend(["--cwd", str(server_dir)])

    return cmd


def _get_venv_site_packages(venv_path: str | None) -> str | None:
    """Get the site-packages path for a venv."""
    if not venv_path:
        return None
    venv = Path(venv_path)
    # Find site-packages directory
    lib_dir = venv / "lib"
    if not lib_dir.exists():
        return None
    # Find python version directory
    for item in lib_dir.iterdir():
        if item.is_dir() and item.name.startswith("python"):
            site_packages = item / "site-packages"
            if site_packages.exists():
                return str(site_packages)
    return None


def _entrypoint_cwd(entrypoint: str | None, namespace: str | None = None) -> Optional[str]:
    """Get working directory for server startup."""
    if entrypoint:
        return str(Path(entrypoint).parent)
    if namespace:
        # For manual servers, use the server directory as cwd
        server_dir = _get_server_dir(namespace)
        if server_dir.exists():
            return str(server_dir)
    return None


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


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks existence
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission (still alive)
        return True


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
    for key in [
        "repository",
        "repository_url",
        "repositoryUrl",
        "repo",
        "repo_url",
        "source",
        "source_url",
        "sourceCodeUrl",
        "source_code_url",
        "project_url",
        "projectUrl",
        "homepage",
        "url",
    ]:
        value = server.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("repository")
        if isinstance(value, str) and value.startswith("http"):
            return value

    links = server.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict):
                url = link.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
    elif isinstance(links, dict):
        for value in links.values():
            if isinstance(value, dict):
                url = value.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
            elif isinstance(value, str) and value.startswith("http"):
                return value

    return None
