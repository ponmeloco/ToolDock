"""
Admin API Routes.

Provides runtime management of tools and FastMCP servers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# These will be set by the transport server on startup
_registry = None
_reloader = None
_fastmcp_manager = None


def set_admin_context(registry, reloader=None, fastmcp_manager=None):
    """Set the admin context for route handlers."""
    global _registry, _reloader, _fastmcp_manager
    _registry = registry
    _reloader = reloader
    _fastmcp_manager = fastmcp_manager


def get_fastmcp_manager():
    """Get the FastMCP manager (optional)."""
    if _fastmcp_manager is None:
        raise HTTPException(
            status_code=503,
            detail="FastMCP manager not initialized"
        )
    return _fastmcp_manager


@router.post("/fastmcp/reload")
async def reload_fastmcp(_: str = Depends(verify_token)) -> Dict[str, Any]:
    """Reload FastMCP external servers from the DB and re-register tools."""
    try:
        manager = get_fastmcp_manager()
        result = await manager.sync_from_db()
        return {"status": "ok", "result": result}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"FastMCP reload failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# === Request/Response Models ===


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
