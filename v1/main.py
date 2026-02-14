"""
ToolDock Tool Server - Main Entrypoint

Starts the server in different modes:
- openapi: OpenAPI/REST Server only (for OpenWebUI)
- mcp-http: MCP Streamable HTTP Server only (for MCP Clients)
- both: Both OpenAPI and MCP servers in parallel
- web-gui: Web GUI server only (for management interface)
- all: All three servers (OpenAPI, MCP, Web GUI)

Control via SERVER_MODE environment variable.

Examples:
    # OpenAPI only (default)
    SERVER_MODE=openapi python main.py

    # MCP HTTP only
    SERVER_MODE=mcp-http python main.py

    # Both servers
    SERVER_MODE=both python main.py

    # Web GUI only
    SERVER_MODE=web-gui python main.py

    # All three servers
    SERVER_MODE=all python main.py
"""

from __future__ import annotations

import logging
import os
import sys
from multiprocessing import Process
from pathlib import Path

import uvicorn

from app.loader import load_tools_from_namespaces
from app.registry import get_registry

# Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Logging Setup with configurable level
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# DATA_DIR is the base directory for all data (tools, config, external)
DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.getcwd(), "tooldock_data"))
TOOLS_DIR = os.path.join(DATA_DIR, "tools")

# Ports
OPENAPI_PORT = int(os.getenv("OPENAPI_PORT", "8006"))
MCP_PORT = int(os.getenv("MCP_PORT", "8007"))
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
HOST = os.getenv("HOST", "0.0.0.0")


def ensure_data_dirs():
    """Ensure required data directories exist."""
    data_path = Path(DATA_DIR)

    # Create directory structure
    dirs = [
        data_path / "tools" / "shared",
        data_path / "external",
        data_path / "external" / "servers",
        data_path / "external" / "logs",
        data_path / "config",
        data_path / "db",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    # Initialize database (tables + file) for new installs
    try:
        from app.db import init_db
        init_db()
    except Exception as exc:
        logger.warning(f"Database init failed: {exc}")

    logger.info(f"Data directory: {DATA_DIR}")


def load_tools_into_registry():
    """Load tools from TOOLS_DIR (namespace-based) into the global registry."""
    registry = get_registry()

    # Load tools from all namespace folders
    results = load_tools_from_namespaces(registry, TOOLS_DIR)

    total_files = sum(results.values())
    namespaces = list(results.keys())

    logger.info(
        f"Loaded tools from {len(namespaces)} namespace(s): {namespaces}"
    )
    logger.info(f"Total tool files loaded: {total_files}")

    return registry


def start_openapi_server():
    """Start FastAPI OpenAPI Server for OpenWebUI."""
    logger.info(f"Starting OpenAPI Server on {HOST}:{OPENAPI_PORT}...")

    from app.transports.openapi_server import create_openapi_app

    # Ensure data dirs exist
    ensure_data_dirs()

    # Load native tools
    registry = load_tools_into_registry()

    # Create app
    try:
        from app.external.fastmcp_manager import FastMCPServerManager
        fastmcp_manager = FastMCPServerManager(registry, manage_processes=False)
    except Exception as exc:
        logger.warning(f"FastMCP disabled: {exc}")
        fastmcp_manager = None

    app = create_openapi_app(registry, fastmcp_manager=fastmcp_manager)

    # Start server
    uvicorn.run(
        app,
        host=HOST,
        port=OPENAPI_PORT,
        log_level=LOG_LEVEL.lower(),
    )


def start_mcp_http_server():
    """Start MCP Streamable HTTP Server for MCP Clients."""
    logger.info(f"Starting MCP Streamable HTTP Server on {HOST}:{MCP_PORT}...")

    from app.transports.mcp_http_server import create_mcp_http_app

    # Ensure data dirs exist
    ensure_data_dirs()

    # Load native tools
    registry = load_tools_into_registry()

    # Create app
    try:
        from app.external.fastmcp_manager import FastMCPServerManager
        fastmcp_manager = FastMCPServerManager(registry, manage_processes=False)
    except Exception as exc:
        logger.warning(f"FastMCP disabled: {exc}")
        fastmcp_manager = None

    app = create_mcp_http_app(registry, fastmcp_manager=fastmcp_manager)

    # Start server
    uvicorn.run(
        app,
        host=HOST,
        port=MCP_PORT,
        log_level=LOG_LEVEL.lower(),
    )


def start_web_gui_server():
    """Start Web GUI Server for management interface."""
    logger.info(f"Starting Web GUI Server on {HOST}:{WEB_PORT}...")

    from app.web.server import create_web_app

    # Ensure data dirs exist
    ensure_data_dirs()

    # Load native tools (for stats display)
    registry = load_tools_into_registry()

    # Create app
    app = create_web_app(registry)

    # Start server
    uvicorn.run(
        app,
        host=HOST,
        port=WEB_PORT,
        log_level=LOG_LEVEL.lower(),
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
        _cleanup_process(openapi_process, "OpenAPI")
        logger.info("All servers stopped.")


def start_all_servers():
    """Start all three servers (OpenAPI, MCP, Web GUI) in parallel."""
    logger.info("Starting all servers in parallel...")

    processes = []

    # Start OpenAPI server in a subprocess
    logger.info(f"Starting OpenAPI server subprocess on port {OPENAPI_PORT}...")
    openapi_process = Process(target=start_openapi_server)
    openapi_process.start()
    processes.append(("OpenAPI", openapi_process))

    # Start Web GUI server in a subprocess
    logger.info(f"Starting Web GUI server subprocess on port {WEB_PORT}...")
    web_process = Process(target=start_web_gui_server)
    web_process.start()
    processes.append(("Web GUI", web_process))

    # Start MCP server in main process
    logger.info(f"Starting MCP server in main process on port {MCP_PORT}...")
    try:
        start_mcp_http_server()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal...")
    finally:
        for name, process in processes:
            _cleanup_process(process, name)
        logger.info("All servers stopped.")


def _cleanup_process(process: Process, name: str) -> None:
    """Gracefully terminate a subprocess."""
    logger.info(f"Terminating {name} subprocess...")
    process.terminate()
    process.join(timeout=5)

    if process.is_alive():
        logger.warning(f"Force killing {name} subprocess...")
        process.kill()
        process.join(timeout=2)  # Wait briefly after kill


def main():
    """Main entrypoint."""
    mode = os.getenv("SERVER_MODE", "openapi").lower()

    logger.info(f"ToolDock Server starting in mode: {mode}")
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"Tools directory: {TOOLS_DIR}")
    logger.info(f"Log level: {LOG_LEVEL}")

    if mode == "openapi":
        logger.info("Mode: OpenAPI only (for OpenWebUI, REST clients)")
        start_openapi_server()

    elif mode == "mcp-http":
        logger.info("Mode: MCP Streamable HTTP only (for MCP Clients)")
        start_mcp_http_server()

    elif mode == "both":
        logger.info("Mode: Both OpenAPI and MCP servers")
        logger.info(f"  - OpenAPI: http://{HOST}:{OPENAPI_PORT}")
        logger.info(f"  - MCP HTTP: http://{HOST}:{MCP_PORT}")
        start_both_servers()

    elif mode == "web-gui":
        logger.info("Mode: Web GUI only (management interface)")
        start_web_gui_server()

    elif mode == "all":
        logger.info("Mode: All three servers")
        logger.info(f"  - OpenAPI: http://{HOST}:{OPENAPI_PORT}")
        logger.info(f"  - MCP HTTP: http://{HOST}:{MCP_PORT}")
        logger.info(f"  - Web GUI: http://{HOST}:{WEB_PORT}")
        start_all_servers()

    else:
        logger.error(f"Unknown SERVER_MODE: {mode}")
        logger.info("Valid options: openapi, mcp-http, both, web-gui, all")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
