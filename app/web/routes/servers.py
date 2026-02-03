"""
External Server Management API Routes.

Provides endpoints for managing external MCP servers.

Security:
- Sensitive environment variables are masked in responses
- Bearer token authentication required
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/servers", tags=["servers"])

# Patterns for sensitive keys that should be masked
SENSITIVE_PATTERNS = [
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*key.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*connection.*string.*", re.IGNORECASE),
]

# Optional runtime context for live reloading
_external_manager = None
_external_config = None
_reloader = None


def set_servers_context(external_manager, external_config, reloader=None) -> None:
    """Set runtime context for external server management."""
    global _external_manager, _external_config, _reloader
    _external_manager = external_manager
    _external_config = external_config
    _reloader = reloader


class ServerConfig(BaseModel):
    """Configuration for an external server."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        default="custom",
        description="Server source: 'registry' or 'custom'",
    )
    enabled: bool = Field(default=True)
    name: Optional[str] = Field(
        default=None,
        description="Registry server name (for source=registry)",
    )
    command: Optional[str] = Field(
        default=None,
        description="Command to run (for source=custom)",
    )
    args: Optional[List[str]] = Field(
        default=None,
        description="Command arguments",
    )
    type: Optional[str] = Field(
        default="stdio",
        description="Transport type: 'stdio' or 'http'",
    )
    url: Optional[str] = Field(
        default=None,
        description="Server URL (for type=http)",
    )
    env: Optional[Dict[str, str]] = Field(
        default=None,
        description="Environment variables (values will be masked in responses)",
    )


class AddServerRequest(BaseModel):
    """Request to add a new external server."""

    model_config = ConfigDict(extra="forbid")

    server_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="Unique server identifier (becomes namespace)",
    )
    config: ServerConfig


class ServerInfo(BaseModel):
    """Information about an external server."""

    server_id: str
    namespace: str
    endpoint: str
    config: Dict[str, Any]
    enabled: bool


class ServerListResponse(BaseModel):
    """Response for listing servers."""

    servers: List[ServerInfo]
    total: int


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    for pattern in SENSITIVE_PATTERNS:
        if pattern.match(key):
            return True
    return False


def _mask_sensitive_data(data: Any, parent_key: str = "") -> Any:
    """
    Recursively mask sensitive data in a dictionary.

    Masks values that appear to contain secrets based on key names.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            full_key = f"{parent_key}.{key}" if parent_key else key
            if _is_sensitive_key(key):
                # Mask sensitive values but show they exist
                if value and isinstance(value, str):
                    if value.startswith("${"):
                        # Environment variable reference - keep it
                        result[key] = value
                    else:
                        # Actual value - mask it
                        result[key] = "***MASKED***"
                else:
                    result[key] = "***MASKED***" if value else None
            else:
                result[key] = _mask_sensitive_data(value, full_key)
        return result
    elif isinstance(data, list):
        return [_mask_sensitive_data(item, parent_key) for item in data]
    else:
        return data


def _get_config_path() -> Path:
    """Get the external servers config file path."""
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    return Path(data_dir) / "external" / "config.yaml"


def _load_config() -> Dict[str, Any]:
    """Load the external servers configuration."""
    config_path = _get_config_path()

    if not config_path.exists():
        return {"servers": {}, "settings": {}}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {"servers": {}, "settings": {}}


def _save_config(config: Dict[str, Any]) -> None:
    """Save the external servers configuration."""
    config_path = _get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"Saved config to {config_path}")


async def _apply_external_config() -> Dict[str, Any]:
    """
    Apply external config to running manager (if available).

    Returns:
        Summary dict with sync results or skipped reason
    """
    if _external_manager is None or _external_config is None:
        return {"status": "skipped", "reason": "External manager not initialized"}

    try:
        desired = await _external_config.build_enabled_configs()
        results = await _external_manager.sync_servers(desired)

        if _reloader is not None:
            _reloader.set_external_namespaces(set(desired.keys()))

        fanout = await _fanout_external_reload()
        return {"status": "ok", "results": results, "fanout": fanout}
    except Exception as e:
        logger.error(f"Failed to apply external config: {e}")
        return {"status": "error", "error": str(e)}


async def _fanout_external_reload() -> Dict[str, Any]:
    """
    Notify OpenAPI and MCP servers to reload external config.
    """
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
        "openapi": f"http://{host}:{openapi_port}/admin/servers/reload",
        "mcp": f"http://{host}:{mcp_port}/admin/servers/reload",
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
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}

    return results


@router.get("", response_model=ServerListResponse)
async def list_servers(_: str = Depends(verify_token)) -> ServerListResponse:
    """
    List all configured external servers.

    Note: Sensitive configuration values (tokens, passwords, etc.) are masked.
    """
    config = _load_config()
    servers_config = config.get("servers") or {}

    servers = []
    for server_id, server_config in servers_config.items():
        # Mask sensitive data before returning
        masked_config = _mask_sensitive_data(server_config)

        servers.append(
            ServerInfo(
                server_id=server_id,
                namespace=server_id,
                endpoint=f"/mcp/{server_id}",
                config=masked_config,
                enabled=server_config.get("enabled", True),
            )
        )

    return ServerListResponse(
        servers=sorted(servers, key=lambda s: s.server_id),
        total=len(servers),
    )


@router.get("/{server_id}", response_model=ServerInfo)
async def get_server(
    server_id: str,
    _: str = Depends(verify_token),
) -> ServerInfo:
    """
    Get configuration for a specific server.

    Note: Sensitive configuration values are masked.
    """
    config = _load_config()
    servers_config = config.get("servers") or {}

    if server_id not in servers_config:
        raise HTTPException(
            status_code=404,
            detail=f"Server not found: {server_id}",
        )

    server_config = servers_config[server_id]
    masked_config = _mask_sensitive_data(server_config)

    return ServerInfo(
        server_id=server_id,
        namespace=server_id,
        endpoint=f"/mcp/{server_id}",
        config=masked_config,
        enabled=server_config.get("enabled", True),
    )


@router.post("", response_model=ServerInfo)
async def add_server(
    request: AddServerRequest,
    _: str = Depends(verify_token),
) -> ServerInfo:
    """
    Add a new external server configuration.

    The server will be available as a namespace after restart or hot-reload.
    """
    config = _load_config()
    servers_config = config.get("servers") or {}

    if request.server_id in servers_config:
        raise HTTPException(
            status_code=409,
            detail=f"Server already exists: {request.server_id}",
        )

    # Convert Pydantic model to dict, excluding None values
    server_config = request.config.model_dump(exclude_none=True)

    servers_config[request.server_id] = server_config
    config["servers"] = servers_config

    _save_config(config)
    logger.info(f"Added server: {request.server_id}")
    apply_result = await _apply_external_config()
    if apply_result.get("status") == "error":
        logger.warning(f"External reload failed after add: {apply_result.get('error')}")

    # Return masked config
    masked_config = _mask_sensitive_data(server_config)

    return ServerInfo(
        server_id=request.server_id,
        namespace=request.server_id,
        endpoint=f"/mcp/{request.server_id}",
        config=masked_config,
        enabled=server_config.get("enabled", True),
    )


@router.put("/{server_id}", response_model=ServerInfo)
async def update_server(
    server_id: str,
    server_config: ServerConfig,
    _: str = Depends(verify_token),
) -> ServerInfo:
    """
    Update an existing server configuration.
    """
    config = _load_config()
    servers_config = config.get("servers") or {}

    if server_id not in servers_config:
        raise HTTPException(
            status_code=404,
            detail=f"Server not found: {server_id}",
        )

    # Convert Pydantic model to dict, excluding None values
    new_config = server_config.model_dump(exclude_none=True)

    servers_config[server_id] = new_config
    config["servers"] = servers_config

    _save_config(config)
    logger.info(f"Updated server: {server_id}")
    apply_result = await _apply_external_config()
    if apply_result.get("status") == "error":
        logger.warning(f"External reload failed after update: {apply_result.get('error')}")

    # Return masked config
    masked_config = _mask_sensitive_data(new_config)

    return ServerInfo(
        server_id=server_id,
        namespace=server_id,
        endpoint=f"/mcp/{server_id}",
        config=masked_config,
        enabled=new_config.get("enabled", True),
    )


@router.delete("/{server_id}")
async def delete_server(
    server_id: str,
    _: str = Depends(verify_token),
) -> dict:
    """
    Delete a server configuration.
    """
    config = _load_config()
    servers_config = config.get("servers") or {}

    if server_id not in servers_config:
        raise HTTPException(
            status_code=404,
            detail=f"Server not found: {server_id}",
        )

    del servers_config[server_id]
    config["servers"] = servers_config

    _save_config(config)
    logger.info(f"Deleted server: {server_id}")
    apply_result = await _apply_external_config()
    if apply_result.get("status") == "error":
        logger.warning(f"External reload failed after delete: {apply_result.get('error')}")

    return {
        "success": True,
        "message": f"Deleted server: {server_id}",
    }


@router.post("/{server_id}/enable")
async def enable_server(
    server_id: str,
    _: str = Depends(verify_token),
) -> dict:
    """Enable a server."""
    config = _load_config()
    servers_config = config.get("servers") or {}

    if server_id not in servers_config:
        raise HTTPException(
            status_code=404,
            detail=f"Server not found: {server_id}",
        )

    servers_config[server_id]["enabled"] = True
    config["servers"] = servers_config

    _save_config(config)
    logger.info(f"Enabled server: {server_id}")
    apply_result = await _apply_external_config()
    if apply_result.get("status") == "error":
        logger.warning(f"External reload failed after enable: {apply_result.get('error')}")

    return {"success": True, "message": f"Enabled server: {server_id}"}


@router.post("/{server_id}/disable")
async def disable_server(
    server_id: str,
    _: str = Depends(verify_token),
) -> dict:
    """Disable a server."""
    config = _load_config()
    servers_config = config.get("servers") or {}

    if server_id not in servers_config:
        raise HTTPException(
            status_code=404,
            detail=f"Server not found: {server_id}",
        )

    servers_config[server_id]["enabled"] = False
    config["servers"] = servers_config

    _save_config(config)
    logger.info(f"Disabled server: {server_id}")
    apply_result = await _apply_external_config()
    if apply_result.get("status") == "error":
        logger.warning(f"External reload failed after disable: {apply_result.get('error')}")

    return {"success": True, "message": f"Disabled server: {server_id}"}


@router.post("/reload")
async def reload_external_servers(_: str = Depends(verify_token)) -> dict:
    """
    Reload external servers from config.yaml without restarting.
    """
    result = await _apply_external_config()
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "Reload failed"))
    return result
