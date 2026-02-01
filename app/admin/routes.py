"""
Admin API Routes.

Provides runtime management of external MCP servers.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# These will be set by the OpenAPI server on startup
_registry = None
_external_manager = None
_config = None
_reloader = None


def set_admin_context(registry, external_manager, config, reloader=None):
    """Set the admin context for route handlers."""
    global _registry, _external_manager, _config, _reloader
    _registry = registry
    _external_manager = external_manager
    _config = config
    _reloader = reloader


def get_manager():
    """Get the external server manager."""
    if _external_manager is None:
        raise HTTPException(
            status_code=503,
            detail="External server manager not initialized"
        )
    return _external_manager


# === Request/Response Models ===


class AddServerRequest(BaseModel):
    """Request to add a new server."""

    server_id: str = Field(..., description="Unique identifier for the server")
    source: str = Field(
        "registry",
        description="Source type: 'registry' or 'custom'"
    )
    name: Optional[str] = Field(
        None,
        description="Registry name (required for registry source)"
    )
    command: Optional[str] = Field(
        None,
        description="Command to run (for custom stdio source)"
    )
    args: Optional[List[str]] = Field(
        None,
        description="Command arguments (for custom stdio source)"
    )
    env: Optional[Dict[str, str]] = Field(
        None,
        description="Environment variables"
    )
    url: Optional[str] = Field(
        None,
        description="Server URL (for custom http source)"
    )
    save_to_config: bool = Field(
        True,
        description="Save to config.yaml for persistence"
    )


class ServerInfo(BaseModel):
    """Information about an external server."""

    server_id: str
    status: str
    tools: int
    tool_names: List[str]
    config_type: str


class ToolInfo(BaseModel):
    """Information about a tool."""

    name: str
    description: str
    type: str
    server: Optional[str] = None


class RegistryServerInfo(BaseModel):
    """Information about a server from the registry."""

    name: str
    description: str
    version: str
    type: str
    package_or_url: str


# === Routes ===


@router.get("/servers/search", response_model=List[RegistryServerInfo])
async def search_registry(
    query: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    _: str = Depends(verify_token),
) -> List[Dict[str, Any]]:
    """
    Search the MCP Registry for servers.

    Returns a list of matching servers with their metadata.
    """
    from app.external.registry_client import MCPRegistryClient

    client = MCPRegistryClient()

    try:
        results = await client.search_servers(query, limit=limit)

        servers = []
        for item in results:
            server = item.get("server", item)
            config = client.get_server_config(server)

            servers.append({
                "name": server.get("name", "unknown"),
                "description": server.get("description", ""),
                "version": server.get("version", ""),
                "type": config.get("type", "unknown"),
                "package_or_url": (
                    config.get("args", [""])[1] if config.get("args") and len(config.get("args", [])) > 1
                    else config.get("url", "")
                ),
            })

        return servers

    except Exception as e:
        logger.error(f"Registry search failed: {e}")
        raise HTTPException(status_code=502, detail=f"Registry search failed: {e}")


@router.get("/servers/installed", response_model=List[ServerInfo])
async def list_installed_servers(
    _: str = Depends(verify_token),
) -> List[Dict[str, Any]]:
    """
    List all currently installed external servers.
    """
    manager = get_manager()

    return [
        {
            "server_id": info["server_id"],
            "status": info["status"],
            "tools": info["tools"],
            "tool_names": info["tool_names"],
            "config_type": info["config"].get("type", "stdio"),
        }
        for info in manager.list_servers()
    ]


@router.post("/servers/add")
async def add_server(
    request: AddServerRequest,
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """
    Add and connect to a new external server.

    The server can be loaded from:
    - MCP Registry (source='registry', name='registry-name')
    - Custom STDIO command (source='custom', command='...', args=[...])
    - Custom HTTP URL (source='custom', url='...')
    """
    manager = get_manager()

    # Build config based on source
    if request.source == "registry":
        if not request.name:
            raise HTTPException(
                status_code=400,
                detail="'name' is required for registry source"
            )

        from app.external.registry_client import MCPRegistryClient

        client = MCPRegistryClient()
        server_data = await client.get_server(request.name)

        if not server_data:
            raise HTTPException(
                status_code=404,
                detail=f"Server not found in registry: {request.name}"
            )

        config = client.get_server_config(server_data)

        # Override with provided env
        if request.env:
            config["env"] = request.env

    else:
        # Custom configuration
        if request.url:
            config = {
                "type": "http",
                "url": request.url,
            }
        elif request.command:
            config = {
                "type": "stdio",
                "command": request.command,
                "args": request.args or [],
                "env": request.env or {},
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'url' or 'command' is required for custom source"
            )

    # Add the server
    try:
        result = await manager.add_server(request.server_id, config)

        # Save to config if requested
        if request.save_to_config and _config:
            _config.add_server_to_config(
                server_id=request.server_id,
                source=request.source,
                name=request.name,
                env=request.env,
            )

        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to add server: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add server: {e}")


@router.delete("/servers/{server_id}")
async def remove_server(
    server_id: str,
    remove_from_config: bool = Query(True, description="Also remove from config.yaml"),
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """
    Remove an external server and all its tools.
    """
    manager = get_manager()

    removed = await manager.remove_server(server_id)

    if not removed:
        raise HTTPException(status_code=404, detail=f"Server not found: {server_id}")

    # Remove from config if requested
    if remove_from_config and _config:
        _config.remove_server_from_config(server_id)

    return {"status": "removed", "server_id": server_id}


@router.get("/tools", response_model=Dict[str, Any])
async def list_all_tools(
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """
    List all tools with breakdown by type.
    """
    if _registry is None:
        raise HTTPException(status_code=503, detail="Registry not initialized")

    all_tools = _registry.list_all()

    native = [t for t in all_tools if t.get("type") == "native"]
    external = [t for t in all_tools if t.get("type") == "external"]

    return {
        "native": {
            "count": len(native),
            "tools": [{"name": t["name"], "description": t["description"]} for t in native],
        },
        "external": {
            "count": len(external),
            "tools": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "server": t.get("server"),
                }
                for t in external
            ],
        },
        "total": len(all_tools),
    }


@router.get("/stats")
async def get_stats(
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """
    Get statistics about servers and tools.
    """
    manager = get_manager()

    registry_stats = _registry.get_stats() if _registry else {}
    manager_stats = manager.get_stats()

    return {
        "tools": registry_stats,
        "servers": manager_stats,
    }


# === Reload Routes ===


@router.post("/reload")
async def reload_all_namespaces(
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """
    Reload all native tool namespaces.

    This will re-import all Python tool files from the tools directory.
    External servers are not affected.
    """
    if _reloader is None:
        raise HTTPException(
            status_code=503,
            detail="Reloader not initialized"
        )

    logger.info("API request: Reload all namespaces")
    results = _reloader.reload_all()

    return {
        "success": all(r.success for r in results),
        "message": f"Reloaded {len(results)} namespace(s)",
        "results": [
            {
                "namespace": r.namespace,
                "tools_unloaded": r.tools_unloaded,
                "tools_loaded": r.tools_loaded,
                "success": r.success,
                "error": r.error,
            }
            for r in results
        ],
    }


@router.post("/reload/{namespace}")
async def reload_namespace(
    namespace: str,
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    """
    Reload a specific namespace.

    Args:
        namespace: The namespace to reload
    """
    if _reloader is None:
        raise HTTPException(
            status_code=503,
            detail="Reloader not initialized"
        )

    logger.info(f"API request: Reload namespace '{namespace}'")
    result = _reloader.reload_namespace(namespace)

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail=result.error or f"Failed to reload namespace: {namespace}"
        )

    return {
        "success": True,
        "message": f"Successfully reloaded namespace '{namespace}': {result.tools_unloaded} unloaded, {result.tools_loaded} loaded",
        "result": {
            "namespace": result.namespace,
            "tools_unloaded": result.tools_unloaded,
            "tools_loaded": result.tools_loaded,
            "success": result.success,
            "error": result.error,
        },
    }
