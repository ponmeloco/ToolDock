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
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Body, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import get_bearer_token, is_auth_enabled
from app.registry import ToolRegistry
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
        return {
            "status": "ok",
            "namespace": REGISTRY_NAMESPACE,
            "transport": "openapi"
        }

    @app.get("/tools", dependencies=[Depends(bearer_auth_dependency)])
    async def list_tools():
        tools = app.state.registry.list_tools()
        return {
            "namespace": REGISTRY_NAMESPACE,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_model.model_json_schema()}
                for t in tools
            ],
        }

    # Register tool endpoints
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

    logger.info(f"[{REGISTRY_NAMESPACE}] OpenAPI server created with {len(registry.list_tools())} tools")
    return app


# Legacy compatibility: create app with startup event for direct uvicorn usage
def create_legacy_openapi_app() -> FastAPI:
    """
    Create OpenAPI app with startup-based tool loading.

    This is for backward compatibility with the original openapi_app.py pattern.
    For new code, prefer create_openapi_app() with explicit registry.
    """
    from app.loader import load_tools_from_directory

    TOOLS_DIR = os.getenv("TOOLS_DIR", os.path.join(os.getcwd(), "tools"))

    app = FastAPI(
        title=SERVER_NAME,
        version="1.0.0",
        description="OpenAPI toolserver exposing registered tools.",
    )

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

    @app.on_event("startup")
    async def startup_event():
        registry = ToolRegistry(namespace=REGISTRY_NAMESPACE)
        load_tools_from_directory(registry, TOOLS_DIR, recursive=True)
        app.state.registry = registry

        logger.info(f"[{REGISTRY_NAMESPACE}] Loaded {len(registry.list_tools())} tools from {TOOLS_DIR}")

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

    @app.get("/health")
    async def health():
        return {"status": "ok", "namespace": REGISTRY_NAMESPACE, "transport": "openapi"}

    @app.get("/tools", dependencies=[Depends(bearer_auth_dependency)])
    async def list_tools():
        tools = app.state.registry.list_tools()
        return {
            "namespace": REGISTRY_NAMESPACE,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_model.model_json_schema()}
                for t in tools
            ],
        }

    return app


# For backward compatibility: expose app directly
app = create_legacy_openapi_app()
