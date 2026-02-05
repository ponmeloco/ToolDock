"""FastMCP external server management routes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import os

import httpx

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth import verify_token
from app.db.database import get_db
from app.db.models import ExternalFastMCPServer
from app.external.fastmcp_manager import FastMCPServerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fastmcp", tags=["fastmcp"])

_fastmcp_manager: Optional[FastMCPServerManager] = None


def _optional_auth(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """Optional auth - returns None if no token, validates if present."""
    if not authorization:
        return None
    expected = os.getenv("BEARER_TOKEN", "")
    if not expected:
        return None
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid token")
    return token


async def _sync_fastmcp_registry() -> None:
    """Sync FastMCP servers with the registry."""
    if _fastmcp_manager is None:
        return
    try:
        await _fastmcp_manager.sync_from_db()
    except Exception as exc:
        logger.warning(f"FastMCP registry sync failed (web): {exc}")


async def _fanout_fastmcp_reload() -> Dict[str, Any]:
    if os.getenv("PYTEST_CURRENT_TEST") is not None:
        return {"status": "skipped", "reason": "test_mode"}

    token = os.getenv("BEARER_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    host = os.getenv("HOST", "127.0.0.1")
    if host in {"0.0.0.0", ""}:
        host = "127.0.0.1"
    openapi_port = os.getenv("OPENAPI_PORT", "8006")
    mcp_port = os.getenv("MCP_PORT", "8007")

    targets = {
        "openapi": f"http://{host}:{openapi_port}/admin/fastmcp/reload",
        "mcp": f"http://{host}:{mcp_port}/admin/fastmcp/reload",
    }

    results: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=0.5) as client:
        for name, url in targets.items():
            try:
                resp = await client.post(url, headers=headers)
                if resp.status_code >= 400:
                    results[name] = {"status": "error", "code": resp.status_code}
                else:
                    results[name] = {"status": "ok"}
            except Exception as exc:
                results[name] = {"status": "error", "error": str(exc)}
    return results


def set_fastmcp_context(manager: FastMCPServerManager) -> None:
    global _fastmcp_manager
    _fastmcp_manager = manager


# ============================================================
# Request/Response Models
# ============================================================

class AddFastMCPServerRequest(BaseModel):
    """Add server from registry."""
    model_config = ConfigDict(extra="forbid")

    server_name: Optional[str] = Field(None, min_length=3)
    server_id: Optional[str] = Field(None, min_length=8)
    namespace: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    version: Optional[str] = None


class AddManualServerRequest(BaseModel):
    """Add a manually configured MCP server (like Claude Desktop format)."""
    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    server_name: str = Field(..., min_length=1, max_length=255, description="Display name for the server")

    # Standard MCP config format (like Claude Desktop)
    command: str = Field(..., min_length=1, description="Startup command (e.g., 'python', 'node', 'npx')")
    args: Optional[List[str]] = Field(default=None, description="Command arguments")
    env: Optional[Dict[str, str]] = Field(default=None, description="Environment variables")

    # Optional config file content (will be saved to namespace directory)
    config_file: Optional[str] = Field(default=None, description="Config file content (saved as config.yaml)")
    config_filename: str = Field(default="config.yaml", description="Config filename")

    auto_start: bool = Field(default=False, description="Auto-start on ToolDock startup")


class AddFromConfigRequest(BaseModel):
    """Add MCP server from Claude Desktop JSON config format with pip package."""
    model_config = ConfigDict(extra="forbid")

    namespace: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")

    # Claude Desktop config format (paste the JSON)
    config: Dict[str, Any] = Field(
        ...,
        description="Claude Desktop config: {command, args?, env?}",
        json_schema_extra={
            "example": {
                "command": "python",
                "args": ["-m", "mcp_server_fetch"],
                "env": {"API_KEY": "xxx"}
            }
        }
    )

    # Optional: pip package to install first
    pip_package: Optional[str] = Field(
        default=None,
        description="Pip package to install (e.g., 'mcp-server-fetch')"
    )

    auto_start: bool = Field(default=True, description="Auto-start after installation")


class UpdateServerRequest(BaseModel):
    """Update server configuration."""
    model_config = ConfigDict(extra="forbid")

    server_name: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    auto_start: Optional[bool] = None


class ConfigFileRequest(BaseModel):
    """Update config file content."""
    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., description="Config file content")
    filename: str = Field(default="config.yaml", description="Config filename")


class FastMCPServerResponse(BaseModel):
    """Server response."""
    id: int
    server_name: str
    namespace: str
    version: Optional[str] = None
    install_method: str

    # MCP config fields
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None

    # Legacy fields for registry-installed servers
    repo_url: Optional[str] = None
    entrypoint: Optional[str] = None

    port: Optional[int] = None
    status: str
    pid: Optional[int] = None
    last_error: Optional[str] = None
    auto_start: bool = False

    # Config file info
    config_path: Optional[str] = None


class ConfigFileResponse(BaseModel):
    """Config file response."""
    namespace: str
    filename: str
    content: str
    path: str


def _get_server_dir(namespace: str) -> Path:
    """Get the directory for a server's files."""
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    return Path(data_dir) / "external" / "servers" / namespace


def _server_to_response(row: ExternalFastMCPServer) -> FastMCPServerResponse:
    """Convert database row to response model."""
    server_dir = _get_server_dir(row.namespace)
    config_path = None
    if server_dir.exists():
        for fname in ["config.yaml", "config.yml", "config.json"]:
            if (server_dir / fname).exists():
                config_path = str(server_dir / fname)
                break

    return FastMCPServerResponse(
        id=row.id,
        server_name=row.server_name,
        namespace=row.namespace,
        version=row.version,
        install_method=row.install_method,
        command=row.startup_command,
        args=row.command_args,
        env=row.env_vars,
        repo_url=row.repo_url,
        entrypoint=row.entrypoint,
        port=row.port,
        status=row.status,
        pid=row.pid,
        last_error=row.last_error,
        auto_start=row.auto_start,
        config_path=config_path,
    )


def _record_to_response(record: Any) -> FastMCPServerResponse:
    """Convert any record-like object (DB model or stub) to response."""
    return FastMCPServerResponse(
        id=record.id,
        server_name=record.server_name,
        namespace=record.namespace,
        version=getattr(record, "version", None),
        install_method=record.install_method,
        command=getattr(record, "startup_command", None),
        args=getattr(record, "command_args", None),
        env=getattr(record, "env_vars", None),
        repo_url=getattr(record, "repo_url", None),
        entrypoint=getattr(record, "entrypoint", None),
        port=getattr(record, "port", None),
        status=record.status,
        pid=getattr(record, "pid", None),
        last_error=getattr(record, "last_error", None),
        auto_start=getattr(record, "auto_start", False),
        config_path=None,
    )


# ============================================================
# Registry Routes (GET - optional auth)
# ============================================================

@router.get("/registry/servers")
async def list_registry_servers(
    limit: int = 30,
    cursor: Optional[str] = None,
    search: Optional[str] = None,
    _: Optional[str] = Depends(_optional_auth),
) -> Dict[str, Any]:
    """List available servers from MCP registry."""
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        return await _fastmcp_manager.list_registry_servers(limit=limit, cursor=cursor, search=search)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/registry/health")
async def registry_health(_: Optional[str] = Depends(_optional_auth)) -> Dict[str, Any]:
    """Check if MCP registry is reachable."""
    if _fastmcp_manager is None:
        return {"status": "offline", "reason": "manager_not_initialized"}

    try:
        await _fastmcp_manager.list_registry_servers(limit=1)
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "offline", "reason": str(exc)}


# ============================================================
# Server List/Get Routes (GET - optional auth)
# ============================================================

@router.get("/servers", response_model=List[FastMCPServerResponse])
async def list_fastmcp_servers(_: Optional[str] = Depends(_optional_auth)) -> List[FastMCPServerResponse]:
    """List all installed MCP servers."""
    with get_db() as db:
        rows = db.execute(select(ExternalFastMCPServer)).scalars().all()
        return [_server_to_response(row) for row in rows]


@router.get("/servers/{server_id}", response_model=FastMCPServerResponse)
async def get_fastmcp_server(server_id: int, _: Optional[str] = Depends(_optional_auth)) -> FastMCPServerResponse:
    """Get a specific server's configuration."""
    with get_db() as db:
        record = db.get(ExternalFastMCPServer, server_id)
        if not record:
            raise HTTPException(status_code=404, detail="Server not found")
        return _server_to_response(record)


# ============================================================
# Config File Routes (for GUI code editor)
# ============================================================

@router.get("/servers/{server_id}/config", response_model=ConfigFileResponse)
async def get_server_config(
    server_id: int,
    filename: str = "config.yaml",
    _: Optional[str] = Depends(_optional_auth)
) -> ConfigFileResponse:
    """Get server config file content (for code editor)."""
    with get_db() as db:
        record = db.get(ExternalFastMCPServer, server_id)
        if not record:
            raise HTTPException(status_code=404, detail="Server not found")

        server_dir = _get_server_dir(record.namespace)
        config_path = server_dir / filename

        content = ""
        if config_path.exists():
            content = config_path.read_text(encoding="utf-8")

        return ConfigFileResponse(
            namespace=record.namespace,
            filename=filename,
            content=content,
            path=str(config_path),
        )


@router.put("/servers/{server_id}/config", response_model=ConfigFileResponse)
async def update_server_config_file(
    server_id: int,
    request: ConfigFileRequest,
    _: str = Depends(verify_token)
) -> ConfigFileResponse:
    """Update server config file content (from code editor)."""
    with get_db() as db:
        record = db.get(ExternalFastMCPServer, server_id)
        if not record:
            raise HTTPException(status_code=404, detail="Server not found")

        server_dir = _get_server_dir(record.namespace)
        server_dir.mkdir(parents=True, exist_ok=True)

        config_path = server_dir / request.filename
        config_path.write_text(request.content, encoding="utf-8")

        logger.info(f"Updated config for {record.namespace}: {config_path}")

        return ConfigFileResponse(
            namespace=record.namespace,
            filename=request.filename,
            content=request.content,
            path=str(config_path),
        )


@router.get("/servers/{server_id}/config/files")
async def list_server_config_files(
    server_id: int,
    _: Optional[str] = Depends(_optional_auth)
) -> Dict[str, Any]:
    """List all config files for a server."""
    with get_db() as db:
        record = db.get(ExternalFastMCPServer, server_id)
        if not record:
            raise HTTPException(status_code=404, detail="Server not found")

        server_dir = _get_server_dir(record.namespace)
        files = []

        if server_dir.exists():
            for f in server_dir.iterdir():
                if f.is_file() and (f.suffix in [".yaml", ".yml", ".json", ".toml"] or f.name == ".env"):
                    files.append({
                        "filename": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                    })

        return {
            "namespace": record.namespace,
            "directory": str(server_dir),
            "files": files,
        }


# ============================================================
# Server Management Routes (POST/PUT/DELETE - require auth)
# ============================================================

@router.post("/servers", response_model=FastMCPServerResponse)
async def add_fastmcp_server(request: AddFastMCPServerRequest, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    """Add server from MCP registry."""
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    if not request.server_name and not request.server_id:
        raise HTTPException(status_code=422, detail="Either 'server_name' or 'server_id' is required")

    try:
        record = await _fastmcp_manager.add_server_from_registry(
            server_name=request.server_name,
            namespace=request.namespace,
            version=request.version,
            server_id=request.server_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = _record_to_response(record)
    await _sync_fastmcp_registry()
    await _fanout_fastmcp_reload()
    return response


@router.post("/servers/manual", response_model=FastMCPServerResponse)
async def add_manual_server(request: AddManualServerRequest, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    """Add a manually configured MCP server.

    Uses the standard MCP config format (like Claude Desktop):
    - command: The startup command (python, node, npx, etc.)
    - args: Command line arguments
    - env: Environment variables
    """
    with get_db() as db:
        # Check namespace doesn't exist
        existing = db.execute(
            select(ExternalFastMCPServer).where(ExternalFastMCPServer.namespace == request.namespace)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Namespace already exists: {request.namespace}")

        record = ExternalFastMCPServer(
            server_name=request.server_name,
            namespace=request.namespace,
            install_method="manual",
            startup_command=request.command,
            command_args=request.args,
            env_vars=request.env,
            auto_start=request.auto_start,
            status="stopped",
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        # Create server directory and config file
        server_dir = _get_server_dir(request.namespace)
        server_dir.mkdir(parents=True, exist_ok=True)

        if request.config_file:
            config_path = server_dir / request.config_filename
            config_path.write_text(request.config_file, encoding="utf-8")
            logger.info(f"Created config for {request.namespace}: {config_path}")

        response = _server_to_response(record)

    await _sync_fastmcp_registry()
    await _fanout_fastmcp_reload()
    return response


@router.post("/servers/from-config", response_model=FastMCPServerResponse)
async def add_from_config(request: AddFromConfigRequest, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    """Add MCP server from Claude Desktop JSON config format.

    This is the recommended way to add Python MCP servers:
    1. Paste the config JSON from the server's README (Claude Desktop format)
    2. Optionally specify a pip package to install

    Example config:
    {
        "command": "python",
        "args": ["-m", "mcp_server_fetch"],
        "env": {"API_KEY": "xxx"}
    }
    """
    from app.deps import ensure_venv, install_packages

    # Validate config structure
    config = request.config
    command = config.get("command")
    if not command:
        raise HTTPException(status_code=422, detail="Config must have 'command' field")

    args = config.get("args", [])
    if not isinstance(args, list):
        raise HTTPException(status_code=422, detail="Config 'args' must be a list")

    env = config.get("env", {})
    if not isinstance(env, dict):
        raise HTTPException(status_code=422, detail="Config 'env' must be an object")

    # Derive server name from package or command
    server_name = request.pip_package or f"{command} {' '.join(args[:2])}"

    with get_db() as db:
        existing = db.execute(
            select(ExternalFastMCPServer).where(ExternalFastMCPServer.namespace == request.namespace)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Namespace already exists: {request.namespace}")

        record = ExternalFastMCPServer(
            server_name=server_name,
            namespace=request.namespace,
            install_method="config",
            startup_command=command,
            command_args=args if args else None,
            env_vars=env if env else None,
            auto_start=request.auto_start,
            status="installing" if request.pip_package else "stopped",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        server_id = record.id

    # Install pip package if specified
    if request.pip_package:
        try:
            venv_dir = ensure_venv(request.namespace)
            result = install_packages(request.namespace, [request.pip_package])
            if not result.get("success"):
                error_msg = result.get("stderr") or "Package installation failed"
                with get_db() as db:
                    record = db.get(ExternalFastMCPServer, server_id)
                    if record:
                        record.status = "error"
                        record.last_error = error_msg
                        db.commit()
                raise HTTPException(status_code=500, detail=error_msg)

            with get_db() as db:
                record = db.get(ExternalFastMCPServer, server_id)
                if record:
                    record.venv_path = str(venv_dir)
                    record.status = "stopped"
                    db.commit()
                    db.refresh(record)
        except HTTPException:
            raise
        except Exception as exc:
            with get_db() as db:
                record = db.get(ExternalFastMCPServer, server_id)
                if record:
                    record.status = "error"
                    record.last_error = str(exc)
                    db.commit()
            raise HTTPException(status_code=500, detail=str(exc))

    with get_db() as db:
        record = db.get(ExternalFastMCPServer, server_id)
        if not record:
            raise HTTPException(status_code=500, detail="Server record lost")
        response = _server_to_response(record)

    await _sync_fastmcp_registry()
    await _fanout_fastmcp_reload()
    return response


@router.put("/servers/{server_id}", response_model=FastMCPServerResponse)
async def update_server(
    server_id: int,
    request: UpdateServerRequest,
    _: str = Depends(verify_token)
) -> FastMCPServerResponse:
    """Update server configuration."""
    with get_db() as db:
        record = db.get(ExternalFastMCPServer, server_id)
        if not record:
            raise HTTPException(status_code=404, detail="Server not found")

        if request.server_name is not None:
            record.server_name = request.server_name
        if request.command is not None:
            record.startup_command = request.command
        if request.args is not None:
            record.command_args = request.args
        if request.env is not None:
            record.env_vars = request.env
        if request.auto_start is not None:
            record.auto_start = request.auto_start

        db.commit()
        db.refresh(record)
        response = _server_to_response(record)

    await _sync_fastmcp_registry()
    await _fanout_fastmcp_reload()
    return response


@router.post("/servers/{server_id}/start", response_model=FastMCPServerResponse)
async def start_fastmcp_server(server_id: int, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    """Start a MCP server."""
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        record = _fastmcp_manager.start_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = _record_to_response(record)
    # Give the server process time to start listening before syncing
    await asyncio.sleep(2)
    await _sync_fastmcp_registry()
    await _fanout_fastmcp_reload()
    return response


@router.post("/servers/{server_id}/stop", response_model=FastMCPServerResponse)
async def stop_fastmcp_server(server_id: int, _: str = Depends(verify_token)) -> FastMCPServerResponse:
    """Stop a MCP server."""
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        record = _fastmcp_manager.stop_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = _record_to_response(record)
    await _sync_fastmcp_registry()
    await _fanout_fastmcp_reload()
    return response


@router.delete("/servers/{server_id}")
async def delete_fastmcp_server(server_id: int, _: str = Depends(verify_token)) -> Dict[str, Any]:
    """Delete a MCP server."""
    if _fastmcp_manager is None:
        raise HTTPException(status_code=500, detail="FastMCP manager not initialized")

    try:
        _fastmcp_manager.delete_server(server_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _sync_fastmcp_registry()
    return {"success": True, "fanout": await _fanout_fastmcp_reload()}


@router.post("/sync")
async def sync_fastmcp(
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """Re-sync running FastMCP servers into the tool registry.

    Call this to pick up tools from servers that were still starting
    when the last sync ran.
    """
    await _sync_fastmcp_registry()
    fanout = await _fanout_fastmcp_reload()
    stats = _fastmcp_manager.registry.get_stats() if _fastmcp_manager else {}
    return {"success": True, "external_tools": stats.get("external", 0), "fanout": fanout}
