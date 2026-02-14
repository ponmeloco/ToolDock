"""
Backend API Server for ToolDock.

Provides REST API for managing:
- Folders/Namespaces
- Tools (upload, validate, delete, update)
- External MCP Servers
- System administration (health, logs, info)

Security:
- Bearer token authentication for API calls
- Configurable CORS origins
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.auth import is_auth_enabled, verify_token
from app.middleware import TrailingNewlineMiddleware, RequestLoggingMiddleware
from app.utils import get_cors_origins
from app.web.routes import (
    folders_router,
    tools_router,
    fastmcp_router,
    reload_router,
    admin_router,
    playground_router,
)
from app.metrics_store import init_metrics_store
from app.web.routes.admin import setup_log_buffer
from app.reload import init_reloader

if TYPE_CHECKING:
    from app.registry import ToolRegistry

logger = logging.getLogger("backend-api")

SERVER_NAME = os.getenv("WEB_SERVER_NAME", "tooldock-backend")


def create_web_app(
    registry: "ToolRegistry",
) -> FastAPI:
    """
    Create the Backend API FastAPI application.

    This is a pure API server - no HTML is served.
    The Admin UI (React) is served from a separate container.

    Authentication:
    - Bearer token authentication for all API endpoints
    - Health endpoint is public (no auth required)

    Args:
        registry: The shared ToolRegistry (for status info)

    Returns:
        FastAPI application with API endpoints
    """
    app = FastAPI(
        title=f"{SERVER_NAME} - API",
        description="Backend API for ToolDock server management",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        redirect_slashes=False,
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
        openapi_schema["components"] = openapi_schema.get("components", {})
        openapi_schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Enter your Bearer token",
            }
        }
        # Apply security to all endpoints except health
        for path in openapi_schema["paths"]:
            if path != "/health":
                for method in openapi_schema["paths"][path]:
                    if method != "options":
                        openapi_schema["paths"][path][method]["security"] = [{"BearerAuth": []}]
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    # Configure CORS with environment-based origins
    cors_origins = get_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_origins != ["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Add trailing newline to JSON responses for better CLI output
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        app.add_middleware(TrailingNewlineMiddleware)

    # Store registry in app state
    app.state.registry = registry

    # Setup log buffer for log viewing
    setup_log_buffer()

    # Initialize hot reload
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    tools_dir = f"{data_dir}/tools"
    reloader = init_reloader(registry, tools_dir)
    logger.info(f"Hot reload initialized with tools_dir: {tools_dir}")

    # Initialize metrics store (for admin API aggregation)
    init_metrics_store(data_dir)

    # Add request logging middleware (after log buffer is set up)
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        app.add_middleware(RequestLoggingMiddleware, service_name="web")

    # Set admin context (for namespace tool counts)
    from app.web.routes.admin import set_admin_context
    set_admin_context(registry)

    # FastMCP manager (process control + registry updates)
    if fastmcp_router is not None:
        try:
            from app.external.fastmcp_manager import FastMCPServerManager
            from app.web.routes.fastmcp import set_fastmcp_context
            fastmcp_manager = FastMCPServerManager(registry, manage_processes=True)
            set_fastmcp_context(fastmcp_manager)

            async def _fanout_fastmcp_reload_startup() -> None:
                """Ask OpenAPI/MCP transport processes to re-sync FastMCP servers.

                The web process is the one that actually starts subprocesses.
                OpenAPI/MCP can start before those servers are ready, so they
                need a second sync once the web process has finished startup.
                """
                if os.getenv("PYTEST_CURRENT_TEST") is not None:
                    return

                token = os.getenv("BEARER_TOKEN", "")
                headers = {"Authorization": f"Bearer {token}"} if token else {}

                host = os.getenv("HOST", "127.0.0.1")
                if host in {"0.0.0.0", ""}:
                    host = "127.0.0.1"

                openapi_port = os.getenv("OPENAPI_PORT", "8006")
                mcp_port = os.getenv("MCP_PORT", "8007")

                targets = [
                    ("openapi", f"http://{host}:{openapi_port}/admin/fastmcp/reload"),
                    ("mcp", f"http://{host}:{mcp_port}/admin/fastmcp/reload"),
                ]

                import httpx
                import asyncio

                # Retry briefly, because the other transport processes may still be booting.
                remaining = {name for name, _ in targets}
                async with httpx.AsyncClient(timeout=0.8) as client:
                    for attempt in range(6):
                        for name, url in targets:
                            if name not in remaining:
                                continue
                            try:
                                resp = await client.post(url, headers=headers)
                                if resp.status_code < 400:
                                    remaining.discard(name)
                                else:
                                    logger.debug(
                                        f"FastMCP startup fanout to {name} failed: {resp.status_code}"
                                    )
                            except Exception as exc:
                                logger.debug(f"FastMCP startup fanout to {name} error: {exc}")
                        if not remaining:
                            return
                        await asyncio.sleep(0.5)

            @app.on_event("startup")
            async def _seed_fastmcp_system_installer() -> None:
                await fastmcp_manager.ensure_system_installer_server()

            @app.on_event("startup")
            async def _seed_fastmcp_demo() -> None:
                await fastmcp_manager.seed_demo_server()

            @app.on_event("startup")
            async def _sync_fastmcp_from_db() -> None:
                try:
                    await fastmcp_manager.sync_from_db()
                    await _fanout_fastmcp_reload_startup()
                except BaseException as exc:
                    logger.warning(f"FastMCP sync failed (web): {exc}")
        except Exception as exc:
            logger.warning(f"FastMCP disabled: {exc}")

    # Include API routes
    app.include_router(folders_router)
    app.include_router(tools_router)
    if fastmcp_router is not None:
        app.include_router(fastmcp_router)
    app.include_router(reload_router)
    app.include_router(admin_router)
    app.include_router(playground_router)

    # Root endpoint - redirect to docs
    @app.get("/")
    async def root():
        """Redirect to API documentation."""
        return RedirectResponse(url="/docs")

    # Health check (no auth required)
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        stats = registry.get_stats()
        return {
            "status": "healthy",
            "service": "backend-api",
            "server_name": SERVER_NAME,
            "auth_enabled": is_auth_enabled(),
            "tools": {
                "native": stats.get("native", 0),
                "external": stats.get("external", 0),
                "total": stats.get("total", 0),
                "namespaces": stats.get("namespaces", 0),
            },
        }

    # Dashboard API
    @app.get("/api/dashboard")
    async def dashboard(_: str = Depends(verify_token)):
        """Get dashboard overview data."""
        stats = registry.get_stats()
        namespaces = registry.list_namespaces()

        return {
            "server_name": SERVER_NAME,
            "tools": {
                "native": stats.get("native", 0),
                "external": stats.get("external", 0),
                "total": stats.get("total", 0),
            },
            "namespaces": {
                "list": namespaces,
                "count": len(namespaces),
            },
            "endpoints": {
                "mcp_base": "/mcp",
                "namespace_endpoints": [f"/{ns}/mcp" for ns in namespaces],
            },
        }

    logger.info(f"Backend API server created: {SERVER_NAME} (Auth enabled: {is_auth_enabled()})")
    return app
