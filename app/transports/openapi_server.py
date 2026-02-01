"""
OpenAPI Transport Server

This module provides the REST/OpenAPI transport layer for OpenWebUI
and other REST clients. It exposes tools as POST endpoints with
full OpenAPI documentation.

Usage:
    from app.transports.openapi_server import create_openapi_app
    from app.registry import get_registry

    app = create_openapi_app(get_registry())
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Body, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import get_bearer_token, is_auth_enabled
from app.middleware import TrailingNewlineMiddleware
from app.registry import ToolRegistry
from app.reload import ToolReloader
from app.errors import ToolError, ToolUnauthorizedError, ToolValidationError

logger = logging.getLogger("openapi")

SERVER_NAME = os.getenv("OPENAPI_SERVER_NAME", "omnimcp-openapi")
REGISTRY_NAMESPACE = os.getenv("REGISTRY_NAMESPACE", "default")


def bearer_auth_dependency(request: Request) -> None:
    """Validate Bearer token authentication."""
    if not is_auth_enabled():
        return
    token = get_bearer_token()
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ToolUnauthorizedError("Authorization Header fehlt oder ist ungültig")
    provided = header.split(" ", 1)[1].strip()
    if not token or provided != token:
        raise ToolUnauthorizedError("Bearer Token ist ungültig")


def create_openapi_app(registry: ToolRegistry) -> FastAPI:
    """
    Create a FastAPI application for OpenAPI transport.

    Args:
        registry: The shared ToolRegistry containing all registered tools

    Returns:
        FastAPI application with tool endpoints
    """
    app = FastAPI(
        title=SERVER_NAME,
        version="1.0.0",
        description="OpenAPI toolserver exposing registered tools.",
    )

    # Add trailing newline to JSON responses for better CLI output
    app.add_middleware(TrailingNewlineMiddleware)

    # Store registry in app state
    app.state.registry = registry

    @app.exception_handler(ToolUnauthorizedError)
    async def _unauthorized_handler(request: Request, exc: ToolUnauthorizedError):
        return JSONResponse({"error": exc.to_dict()}, status_code=401)

    @app.exception_handler(ToolValidationError)
    async def _validation_handler(request: Request, exc: ToolValidationError):
        return JSONResponse({"error": exc.to_dict()}, status_code=422)

    @app.exception_handler(ToolError)
    async def _tool_error_handler(request: Request, exc: ToolError):
        return JSONResponse({"error": exc.to_dict()}, status_code=400)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse({"error": {"code": "internal_error", "message": str(exc)}}, status_code=500)

    @app.get("/health")
    async def health():
        stats = registry.get_stats()
        return {
            "status": "healthy",
            "namespace": REGISTRY_NAMESPACE,
            "transport": "openapi",
            "tools": stats,
        }

    @app.get("/tools", dependencies=[Depends(bearer_auth_dependency)])
    async def list_tools():
        # Use list_all() to include both native and external tools
        all_tools = app.state.registry.list_all()
        return {
            "namespace": REGISTRY_NAMESPACE,
            "tools": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["inputSchema"],
                    "type": t.get("type", "native"),
                }
                for t in all_tools
            ],
        }

    # Register native tool endpoints
    def make_endpoint(tool_name: str):
        async def endpoint(
            payload: Dict[str, Any] = Body(default={}),
            _auth: Any = Depends(bearer_auth_dependency),
        ):
            result = await app.state.registry.call(tool_name, payload or {})
            return {"tool": tool_name, "result": result}

        endpoint.__name__ = f"tool_{REGISTRY_NAMESPACE}_{tool_name}"
        return endpoint

    for tool in registry.list_tools():
        app.add_api_route(
            f"/tools/{tool.name}",
            make_endpoint(tool.name),
            methods=["POST"],
            name=tool.name,
            operation_id=f"{REGISTRY_NAMESPACE}__{tool.name}",
            description=tool.description,
            openapi_extra={
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": tool.input_model.model_json_schema()}},
                }
            },
        )

    # Add dynamic endpoint for external tools (and any tool by name)
    @app.post("/tools/{tool_name}", dependencies=[Depends(bearer_auth_dependency)])
    async def call_tool_dynamic(
        tool_name: str,
        payload: Dict[str, Any] = Body(default={}),
    ):
        """Execute any tool by name (supports external tools with prefixed names)."""
        if not registry.has_tool(tool_name):
            raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
        result = await registry.call(tool_name, payload or {})
        return {"tool": tool_name, "result": result}

    # Initialize reloader for this registry
    data_dir = os.getenv("DATA_DIR", "omnimcp_data")
    tools_dir = Path(data_dir) / "tools"
    reloader = ToolReloader(registry, str(tools_dir))

    # Include admin router and set context
    from app.admin.routes import router as admin_router, set_admin_context
    set_admin_context(registry, None, None, reloader)
    app.include_router(admin_router)

    logger.info(f"[{REGISTRY_NAMESPACE}] OpenAPI server created with {len(registry.list_tools())} native tools")
    return app


