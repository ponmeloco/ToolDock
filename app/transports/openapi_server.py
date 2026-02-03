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

from app.auth import get_bearer_token, is_auth_enabled, _constant_time_compare
from app.middleware import TrailingNewlineMiddleware, RequestLoggingMiddleware
from app.metrics_store import init_metrics_store
from app.registry import ToolRegistry
from app.reload import ToolReloader
from app.errors import ToolError, ToolTimeoutError, ToolUnauthorizedError, ToolValidationError

logger = logging.getLogger("openapi")

SERVER_NAME = os.getenv("OPENAPI_SERVER_NAME", "tooldock-openapi")
REGISTRY_NAMESPACE = os.getenv("REGISTRY_NAMESPACE", "default")


async def bearer_auth_dependency(request: Request) -> None:
    """Validate Bearer token authentication."""
    if not is_auth_enabled():
        return
    token = get_bearer_token()
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ToolUnauthorizedError("Authorization Header fehlt oder ist ungültig")
    provided = header.split(" ", 1)[1].strip()
    if not token or not _constant_time_compare(provided, token):
        raise ToolUnauthorizedError("Bearer Token ist ungültig")


def create_openapi_app(
    registry: ToolRegistry,
    external_manager=None,
    external_config=None,
) -> FastAPI:
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
        swagger_ui_parameters={
            "persistAuthorization": True,
        },
    )

    # Add OpenAPI security scheme for Bearer token
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Enter your Bearer token",
            }
        }
        existing_schemas = openapi_schema["components"].get("schemas", {})
        openapi_schema["components"]["schemas"] = {
            **existing_schemas,
            "ToolError": {
                "type": "object",
                "properties": {
                    "error": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string"},
                            "message": {"type": "string"},
                            "details": {"type": "object"},
                        },
                        "required": ["code", "message"],
                    }
                },
                "required": ["error"],
            },
            "ToolResult": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "result": {},
                },
                "required": ["tool", "result"],
            },
            "ToolList": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "tools": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "input_schema": {"type": "object"},
                                "type": {"type": "string"},
                                "namespace": {"type": "string"},
                            },
                            "required": ["name", "description", "input_schema"],
                        },
                    },
                },
                "required": ["namespace", "tools"],
            },
            "Health": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "namespace": {"type": "string"},
                    "transport": {"type": "string"},
                    "tools": {"type": "object"},
                },
                "required": ["status", "transport", "tools"],
            },
        }
        openapi_schema["tags"] = [
            {"name": "Health", "description": "Health and readiness endpoints"},
            {"name": "Tools", "description": "List and execute registered tools"},
            {"name": "Admin", "description": "Admin endpoints (reload, servers, logs)"},
        ]
        openapi_schema["servers"] = [
            {"url": f"http://localhost:{os.getenv('OPENAPI_PUBLIC_PORT', os.getenv('OPENAPI_PORT', '8006'))}"},
        ]
        # Apply security to all endpoints except health
        for path in openapi_schema["paths"]:
            if path != "/health":
                for method in openapi_schema["paths"][path]:
                    if method != "options":
                        openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # Add trailing newline to JSON responses for better CLI output
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        app.add_middleware(TrailingNewlineMiddleware)

    # Add request logging middleware
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    init_metrics_store(data_dir)
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        app.add_middleware(RequestLoggingMiddleware, service_name="openapi")

    # Store registry in app state
    app.state.registry = registry

    @app.exception_handler(ToolUnauthorizedError)
    async def _unauthorized_handler(request: Request, exc: ToolUnauthorizedError):
        return JSONResponse({"error": exc.to_dict()}, status_code=401)

    @app.exception_handler(ToolValidationError)
    async def _validation_handler(request: Request, exc: ToolValidationError):
        return JSONResponse({"error": exc.to_dict()}, status_code=422)

    @app.exception_handler(ToolTimeoutError)
    async def _timeout_handler(request: Request, exc: ToolTimeoutError):
        return JSONResponse({"error": exc.to_dict()}, status_code=504)

    @app.exception_handler(ToolError)
    async def _tool_error_handler(request: Request, exc: ToolError):
        return JSONResponse({"error": exc.to_dict()}, status_code=400)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse({"error": {"code": "internal_error", "message": str(exc)}}, status_code=500)

    @app.get("/health", tags=["Health"], responses={200: {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Health"}}}}})
    async def health():
        stats = registry.get_stats()
        return {
            "status": "healthy",
            "namespace": REGISTRY_NAMESPACE,
            "transport": "openapi",
            "tools": stats,
        }

    @app.get(
        "/tools",
        dependencies=[Depends(bearer_auth_dependency)],
        tags=["Tools"],
        responses={
            200: {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolList"}}}},
            401: {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
        },
    )
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
                    "namespace": t.get("namespace", "shared"),
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
            tags=["Tools"],
            openapi_extra={
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": tool.input_model.model_json_schema()}},
                },
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolResult"}}}},
                    "400": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
                    "401": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
                    "422": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
                    "500": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
                },
            },
        )

    # Add dynamic endpoint for external tools (and any tool by name)
    @app.post(
        "/tools/{tool_name}",
        dependencies=[Depends(bearer_auth_dependency)],
        tags=["Tools"],
        responses={
            200: {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolResult"}}}},
            401: {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
            404: {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/ToolError"}}}},
        },
    )
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
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    tools_dir = Path(data_dir) / "tools"
    external_namespaces = None
    if external_manager is not None:
        try:
            external_namespaces = set(external_manager.get_stats().get("namespaces", []))
        except Exception:
            external_namespaces = None
    reloader = ToolReloader(registry, str(tools_dir), external_namespaces=external_namespaces)

    # Include admin router and set context
    from app.admin.routes import router as admin_router, set_admin_context
    set_admin_context(registry, external_manager, external_config, reloader)
    app.include_router(admin_router)

    logger.info(f"[{REGISTRY_NAMESPACE}] OpenAPI server created with {len(registry.list_tools())} native tools")
    return app
