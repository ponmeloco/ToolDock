"""
Tool Server - Main Entrypoint

Starts the server in different modes:
- openapi: OpenAPI/REST Server only (for OpenWebUI)
- mcp-http: MCP Streamable HTTP Server only (for MCP Clients)
- both: Both servers in parallel

Control via SERVER_MODE environment variable.

Examples:
    # OpenAPI only (default)
    SERVER_MODE=openapi python main.py

    # MCP HTTP only
    SERVER_MODE=mcp-http python main.py

    # Both servers
    SERVER_MODE=both python main.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from multiprocessing import Process
from typing import Optional

import uvicorn

from app.loader import load_tools_from_directory
from app.registry import get_registry

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# Configuration
TOOLS_DIR = os.getenv("TOOLS_DIR", os.path.join(os.getcwd(), "tools"))
OPENAPI_PORT = int(os.getenv("OPENAPI_PORT", "8006"))
MCP_PORT = int(os.getenv("MCP_PORT", "8007"))
HOST = os.getenv("HOST", "0.0.0.0")
EXTERNAL_CONFIG = os.getenv("EXTERNAL_CONFIG", "tools/external/config.yaml")

# Global external server manager for shutdown handling
_external_manager: Optional["ExternalServerManager"] = None


def load_tools_into_registry():
    """Load tools from TOOLS_DIR into the global registry."""
    registry = get_registry()
    load_tools_from_directory(registry, TOOLS_DIR, recursive=True)
    logger.info(f"Loaded {len(registry.list_tools())} native tools from {TOOLS_DIR}")
    return registry


async def init_external_servers(registry):
    """Initialize external MCP servers from config."""
    global _external_manager

    from app.external.config import ExternalServerConfig
    from app.external.server_manager import ExternalServerManager

    logger.info("Initializing external MCP servers...")

    _external_manager = ExternalServerManager(registry)

    try:
        config = ExternalServerConfig(EXTERNAL_CONFIG)
        result = await config.apply(_external_manager)

        loaded = len(result.get("loaded", []))
        failed = len(result.get("failed", []))

        if loaded > 0:
            logger.info(f"Loaded {loaded} external servers")
        if failed > 0:
            logger.warning(f"Failed to load {failed} external servers")

        stats = registry.get_stats()
        logger.info(
            f"Total tools: {stats['native']} native + {stats['external']} external = {stats['total']}"
        )

    except Exception as e:
        logger.error(f"Failed to init external servers: {e}")
        # Continue - external servers are optional


async def shutdown_external_servers():
    """Shutdown all external servers gracefully."""
    global _external_manager

    if _external_manager:
        logger.info("Shutting down external servers...")
        await _external_manager.shutdown_all()
        _external_manager = None


def start_openapi_server():
    """Start FastAPI OpenAPI Server for OpenWebUI."""
    logger.info(f"Starting OpenAPI Server on {HOST}:{OPENAPI_PORT}...")

    from app.transports.openapi_server import create_openapi_app

    # Load native tools
    registry = load_tools_into_registry()

    # Load external servers
    asyncio.run(init_external_servers(registry))

    # Create app (with admin routes)
    app = create_openapi_app(registry)

    # Start server
    uvicorn.run(
        app,
        host=HOST,
        port=OPENAPI_PORT,
        log_level="info",
    )


def start_mcp_http_server():
    """Start MCP Streamable HTTP Server for MCP Clients."""
    logger.info(f"Starting MCP Streamable HTTP Server on {HOST}:{MCP_PORT}...")

    from app.transports.mcp_http_server import create_mcp_http_app

    # Load native tools
    registry = load_tools_into_registry()

    # Load external servers
    asyncio.run(init_external_servers(registry))

    # Create app
    app = create_mcp_http_app(registry)

    # Start server
    uvicorn.run(
        app,
        host=HOST,
        port=MCP_PORT,
        log_level="info",
    )


def start_both_servers():
    """Start both OpenAPI and MCP servers in parallel."""
    logger.info("Starting both servers in parallel...")

    # Start OpenAPI server in a subprocess
    logger.info(f"Starting OpenAPI server subprocess on port {OPENAPI_PORT}...")
    openapi_process = Process(target=start_openapi_server)
    openapi_process.start()

    # Start MCP server in main process
    logger.info(f"Starting MCP server in main process on port {MCP_PORT}...")
    try:
        start_mcp_http_server()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        logger.info("Terminating OpenAPI subprocess...")
        openapi_process.terminate()
        openapi_process.join(timeout=5)
        if openapi_process.is_alive():
            logger.warning("Force killing OpenAPI subprocess...")
            openapi_process.kill()
        logger.info("All servers stopped.")


def main():
    """Main entrypoint."""
    mode = os.getenv("SERVER_MODE", "openapi").lower()

    logger.info(f"Tool Server starting in mode: {mode}")
    logger.info(f"Tools directory: {TOOLS_DIR}")

    if mode == "openapi":
        logger.info("Mode: OpenAPI only (for OpenWebUI, REST clients)")
        start_openapi_server()

    elif mode == "mcp-http":
        logger.info("Mode: MCP Streamable HTTP only (for MCP Clients)")
        start_mcp_http_server()

    elif mode == "both":
        logger.info("Mode: Both servers parallel")
        logger.info(f"  - OpenAPI: http://{HOST}:{OPENAPI_PORT}")
        logger.info(f"  - MCP HTTP: http://{HOST}:{MCP_PORT}")
        start_both_servers()

    else:
        logger.error(f"Unknown SERVER_MODE: {mode}")
        logger.info("Valid options: openapi, mcp-http, both")
        sys.exit(1)


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""

    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.run(shutdown_external_servers())
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
        asyncio.run(shutdown_external_servers())
