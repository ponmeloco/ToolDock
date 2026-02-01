"""
Reload API Routes for ToolDock.

Provides endpoints for hot-reloading tools at runtime.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import verify_token, get_bearer_token
from app.reload import get_reloader, ReloadResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reload", tags=["reload"])

# Port for the OpenAPI server (to forward reload requests)
OPENAPI_PORT = int(os.getenv("OPENAPI_PORT", "8006"))


# ==================== Response Models ====================


class ReloadResultResponse(BaseModel):
    """Response model for a single reload result."""

    namespace: str
    tools_unloaded: int
    tools_loaded: int
    success: bool
    error: Optional[str] = None


class ReloadAllResponse(BaseModel):
    """Response model for reload all operation."""

    success: bool
    message: str
    results: List[ReloadResultResponse]
    total_namespaces: int
    successful_namespaces: int


class ReloadNamespaceResponse(BaseModel):
    """Response model for single namespace reload."""

    success: bool
    message: str
    result: ReloadResultResponse


# ==================== Helper Functions ====================


def _validate_namespace(namespace: str) -> None:
    """
    Validate a namespace name.

    Args:
        namespace: The namespace name to validate

    Raises:
        HTTPException: If the namespace name is invalid
    """
    if not namespace:
        raise HTTPException(status_code=400, detail="Namespace cannot be empty")

    # Only allow alphanumeric, underscore, and hyphen
    if not re.match(r"^[a-zA-Z0-9_-]+$", namespace):
        raise HTTPException(
            status_code=400,
            detail="Namespace must contain only alphanumeric characters, underscores, and hyphens",
        )

    # Prevent path traversal
    if ".." in namespace or namespace.startswith("/"):
        raise HTTPException(
            status_code=400,
            detail="Invalid namespace name",
        )


def _result_to_response(result: ReloadResult) -> ReloadResultResponse:
    """Convert internal ReloadResult to API response model."""
    return ReloadResultResponse(
        namespace=result.namespace,
        tools_unloaded=result.tools_unloaded,
        tools_loaded=result.tools_loaded,
        success=result.success,
        error=result.error,
    )


async def _forward_reload_to_openapi(namespace: Optional[str] = None) -> None:
    """
    Forward reload request to the OpenAPI server.

    In multi-process mode, each server has its own registry.
    This ensures the OpenAPI server also reloads its registry.

    Args:
        namespace: Specific namespace to reload, or None for all
    """
    token = get_bearer_token()
    if not token:
        logger.warning("No bearer token configured, skipping OpenAPI server reload")
        return

    url = f"http://localhost:{OPENAPI_PORT}/admin/reload"
    if namespace:
        url = f"{url}/{namespace}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
            if response.status_code == 200:
                logger.info(f"Successfully forwarded reload to OpenAPI server: {namespace or 'all'}")
            else:
                logger.warning(
                    f"OpenAPI server reload returned {response.status_code}: {response.text}"
                )
    except httpx.ConnectError:
        logger.debug("OpenAPI server not reachable (may not be running in separate process)")
    except Exception as e:
        logger.warning(f"Failed to forward reload to OpenAPI server: {e}")


# ==================== Endpoints ====================


@router.post("", response_model=ReloadAllResponse)
@router.post("/", response_model=ReloadAllResponse, include_in_schema=False)
async def reload_all_tools(request: Request, _: str = Depends(verify_token)) -> ReloadAllResponse:
    """
    Reload all native tool namespaces.

    This will:
    1. Unregister all tools in each native namespace
    2. Clear Python module caches
    3. Re-import and register tools from disk
    4. Forward reload to OpenAPI server (if running separately)

    External server namespaces are skipped.

    Returns:
        Summary of reload operation with per-namespace results
    """
    reloader = get_reloader()

    if reloader is None:
        raise HTTPException(
            status_code=503,
            detail="Reloader not initialized. Hot reload may not be enabled.",
        )

    logger.info("API request: Reload all namespaces")

    results = reloader.reload_all()
    response_results = [_result_to_response(r) for r in results]

    successful = sum(1 for r in results if r.success)
    total = len(results)

    # Forward reload to OpenAPI server (runs in separate process)
    await _forward_reload_to_openapi()

    if successful == total:
        message = f"Successfully reloaded all {total} namespace(s)"
    elif successful == 0:
        message = f"Failed to reload all {total} namespace(s)"
    else:
        message = f"Partially successful: {successful}/{total} namespace(s) reloaded"

    return ReloadAllResponse(
        success=successful == total,
        message=message,
        results=response_results,
        total_namespaces=total,
        successful_namespaces=successful,
    )


@router.post("/{namespace}", response_model=ReloadNamespaceResponse)
async def reload_namespace(request: Request, namespace: str, _: str = Depends(verify_token)) -> ReloadNamespaceResponse:
    """
    Reload tools in a specific namespace.

    This will:
    1. Unregister all tools in the namespace
    2. Clear Python module cache for the namespace
    3. Re-import and register tools from the namespace directory
    4. Forward reload to OpenAPI server (if running separately)

    Args:
        namespace: The namespace to reload

    Returns:
        Result of the reload operation

    Raises:
        HTTPException: If namespace is invalid or reload fails
    """
    _validate_namespace(namespace)

    reloader = get_reloader()

    if reloader is None:
        raise HTTPException(
            status_code=503,
            detail="Reloader not initialized. Hot reload may not be enabled.",
        )

    logger.info(f"API request: Reload namespace '{namespace}'")

    result = reloader.reload_namespace(namespace)
    response_result = _result_to_response(result)

    # Forward reload to OpenAPI server (runs in separate process)
    await _forward_reload_to_openapi(namespace)

    if result.success:
        message = (
            f"Successfully reloaded namespace '{namespace}': "
            f"{result.tools_unloaded} unloaded, {result.tools_loaded} loaded"
        )
    else:
        message = f"Failed to reload namespace '{namespace}': {result.error}"

    return ReloadNamespaceResponse(
        success=result.success,
        message=message,
        result=response_result,
    )


@router.get("/status")
async def reload_status(request: Request, _: str = Depends(verify_token)) -> dict:
    """
    Get the current status of the reloader.

    Returns:
        Information about the reloader state and available namespaces
    """
    reloader = get_reloader()

    if reloader is None:
        return {
            "enabled": False,
            "message": "Hot reload is not initialized",
        }

    registry = reloader.registry
    namespaces = registry.list_namespaces()

    native_namespaces = [
        ns for ns in namespaces if reloader.is_native_namespace(ns)
    ]
    external_namespaces = [
        ns for ns in namespaces if not reloader.is_native_namespace(ns)
    ]

    return {
        "enabled": True,
        "tools_dir": str(reloader.tools_dir),
        "namespaces": {
            "total": len(namespaces),
            "native": native_namespaces,
            "external": external_namespaces,
            "reloadable_count": len(native_namespaces),
        },
    }
