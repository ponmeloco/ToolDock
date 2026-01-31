"""
Backend API Server for OmniMCP.

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
from typing import TYPE_CHECKING, List

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.auth import is_auth_enabled, verify_token
from app.middleware import TrailingNewlineMiddleware, RequestLoggingMiddleware
from app.web.routes import folders_router, tools_router, servers_router, reload_router, admin_router
from app.web.routes.admin import setup_log_buffer
from app.reload import init_reloader

if TYPE_CHECKING:
    from app.registry import ToolRegistry

logger = logging.getLogger("backend-api")

SERVER_NAME = os.getenv("WEB_SERVER_NAME", "omnimcp-backend")
DATA_DIR = os.getenv("DATA_DIR", "omnimcp_data")


def _get_cors_origins() -> List[str]:
    """Get CORS origins from environment variable."""
    origins_str = os.getenv("CORS_ORIGINS", "").strip()
    if not origins_str or origins_str == "*":
        logger.warning(
            "CORS_ORIGINS not configured or set to '*'. "
            "This is insecure for production. Set specific origins."
        )
        return ["*"]
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]


def create_web_app(registry: "ToolRegistry") -> FastAPI:
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
        description="Backend API for OmniMCP server management",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Configure CORS with environment-based origins
    cors_origins = _get_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_origins != ["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Add trailing newline to JSON responses for better CLI output
    app.add_middleware(TrailingNewlineMiddleware)

    # Store registry in app state
    app.state.registry = registry

    # Setup log buffer for log viewing
    setup_log_buffer()

    # Initialize hot reload
    tools_dir = f"{DATA_DIR}/tools"
    init_reloader(registry, tools_dir)
    logger.info(f"Hot reload initialized with tools_dir: {tools_dir}")

    # Add request logging middleware (after log buffer is set up)
    app.add_middleware(RequestLoggingMiddleware)

    # Include API routes
    app.include_router(folders_router)
    app.include_router(tools_router)
    app.include_router(servers_router)
    app.include_router(reload_router)
    app.include_router(admin_router)

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
                "namespace_endpoints": [f"/mcp/{ns}" for ns in namespaces],
            },
        }

    logger.info(f"Backend API server created: {SERVER_NAME} (Auth enabled: {is_auth_enabled()})")
    return app
