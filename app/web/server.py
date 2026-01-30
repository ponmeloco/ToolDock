"""
Web GUI Server for OmniMCP.

Provides a web interface for managing:
- Folders/Namespaces
- Tools (upload, validate, delete)
- External MCP Servers

Security:
- HTTP Basic authentication for browser access (username: admin, password: BEARER_TOKEN)
- Bearer token authentication also supported for API calls
- Configurable CORS origins
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, List

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.auth import verify_basic_auth, verify_token_or_basic, is_auth_enabled, BasicAuthMiddleware, ADMIN_USERNAME
from app.middleware import TrailingNewlineMiddleware
from app.web.routes import folders_router, tools_router, servers_router, reload_router

if TYPE_CHECKING:
    from app.registry import ToolRegistry

logger = logging.getLogger("web-gui")

SERVER_NAME = os.getenv("WEB_SERVER_NAME", "omnimcp-web")
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
    Create the Web GUI FastAPI application.

    Authentication:
    - Browser access: HTTP Basic Auth (username: admin, password: BEARER_TOKEN)
    - API access: Bearer token OR Basic Auth

    Args:
        registry: The shared ToolRegistry (for status info)

    Returns:
        FastAPI application with web GUI endpoints
    """
    app = FastAPI(
        title=f"{SERVER_NAME} - Web GUI",
        description="Web interface for OmniMCP server management",
        version="1.0.0",
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

    # Add Basic Auth middleware for all routes except health
    app.add_middleware(
        BasicAuthMiddleware,
        public_paths={"/health"},
    )

    # Add trailing newline to JSON responses for better CLI output
    app.add_middleware(TrailingNewlineMiddleware)

    # Store registry in app state
    app.state.registry = registry

    # Include API routes
    # Note: Routes also have their own auth dependencies for additional security
    app.include_router(folders_router)
    app.include_router(tools_router)
    app.include_router(servers_router)
    app.include_router(reload_router)

    # Health check (no auth required - excluded in middleware)
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        stats = registry.get_stats()
        return {
            "status": "healthy",
            "service": "web-gui",
            "server_name": SERVER_NAME,
            "auth_enabled": is_auth_enabled(),
            "auth_type": "basic",
            "tools": {
                "native": stats.get("native", 0),
                "external": stats.get("external", 0),
                "total": stats.get("total", 0),
                "namespaces": stats.get("namespaces", 0),
            },
        }

    # Dashboard API (auth via middleware)
    @app.get("/api/dashboard")
    async def dashboard():
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

    # HTML Dashboard (auth via middleware)
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the HTML dashboard."""
        return _generate_dashboard_html(registry)

    logger.info(f"Web GUI server created: {SERVER_NAME} (Basic Auth enabled: {is_auth_enabled()})")
    return app


def _generate_dashboard_html(registry: "ToolRegistry") -> str:
    """Generate a simple HTML dashboard page."""
    stats = registry.get_stats()
    namespaces = registry.list_namespaces()
    namespace_breakdown = stats.get("namespace_breakdown", {})

    namespace_rows = ""
    for ns in namespaces:
        count = namespace_breakdown.get(ns, 0)
        namespace_rows += f"""
            <tr>
                <td><code>{ns}</code></td>
                <td>{count}</td>
                <td><code>/mcp/{ns}</code></td>
                <td>
                    <a href="/mcp/{ns}" target="_blank">Info</a>
                </td>
            </tr>
        """

    auth_status = "Enabled" if is_auth_enabled() else "Disabled"
    auth_color = "#27ae60" if is_auth_enabled() else "#e74c3c"
    auth_info = f"HTTP Basic (user: {ADMIN_USERNAME})" if is_auth_enabled() else "None"

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OmniMCP Dashboard</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
                line-height: 1.6;
                color: #333;
                background: #f5f5f5;
                padding: 2rem;
            }}
            .container {{
                max-width: 1200px;
                margin: 0 auto;
            }}
            h1 {{
                color: #2c3e50;
                margin-bottom: 1rem;
            }}
            h2 {{
                color: #34495e;
                margin: 2rem 0 1rem;
                border-bottom: 2px solid #3498db;
                padding-bottom: 0.5rem;
            }}
            .stats {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 1rem;
                margin-bottom: 2rem;
            }}
            .stat-card {{
                background: white;
                padding: 1.5rem;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .stat-card h3 {{
                font-size: 0.9rem;
                color: #7f8c8d;
                text-transform: uppercase;
            }}
            .stat-card .value {{
                font-size: 2.5rem;
                font-weight: bold;
                color: #3498db;
            }}
            .stat-card .value.auth {{
                font-size: 1.2rem;
                color: {auth_color};
            }}
            .stat-card .subtext {{
                font-size: 0.8rem;
                color: #95a5a6;
                margin-top: 0.25rem;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background: white;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            th, td {{
                padding: 1rem;
                text-align: left;
                border-bottom: 1px solid #eee;
            }}
            th {{
                background: #3498db;
                color: white;
            }}
            tr:hover {{
                background: #f8f9fa;
            }}
            code {{
                background: #ecf0f1;
                padding: 0.2rem 0.5rem;
                border-radius: 4px;
                font-family: 'Consolas', 'Monaco', monospace;
            }}
            a {{
                color: #3498db;
                text-decoration: none;
            }}
            a:hover {{
                text-decoration: underline;
            }}
            .api-section {{
                background: white;
                padding: 1.5rem;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-top: 2rem;
            }}
            .api-endpoint {{
                display: flex;
                align-items: center;
                padding: 0.5rem 0;
                border-bottom: 1px solid #eee;
            }}
            .api-endpoint:last-child {{
                border-bottom: none;
            }}
            .method {{
                display: inline-block;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                font-size: 0.8rem;
                font-weight: bold;
                margin-right: 1rem;
                min-width: 60px;
                text-align: center;
            }}
            .method.get {{ background: #27ae60; color: white; }}
            .method.post {{ background: #3498db; color: white; }}
            .method.delete {{ background: #e74c3c; color: white; }}
            .method.put {{ background: #f39c12; color: white; }}
            .info-box {{
                background: #d4edda;
                border: 1px solid #c3e6cb;
                border-radius: 8px;
                padding: 1rem;
                margin: 1rem 0;
            }}
            .info-box.warning {{
                background: #fff3cd;
                border-color: #ffc107;
            }}
            .logout-link {{
                float: right;
                color: #e74c3c;
                font-size: 0.9rem;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>
                OmniMCP Dashboard
                <a href="/logout" class="logout-link" onclick="logout(); return false;">Logout</a>
            </h1>

            <div class="info-box">
                <strong>Authenticated</strong> - You are logged in as <code>{ADMIN_USERNAME}</code>
            </div>

            <div class="stats">
                <div class="stat-card">
                    <h3>Native Tools</h3>
                    <div class="value">{stats.get('native', 0)}</div>
                </div>
                <div class="stat-card">
                    <h3>External Tools</h3>
                    <div class="value">{stats.get('external', 0)}</div>
                </div>
                <div class="stat-card">
                    <h3>Total Tools</h3>
                    <div class="value">{stats.get('total', 0)}</div>
                </div>
                <div class="stat-card">
                    <h3>Namespaces</h3>
                    <div class="value">{len(namespaces)}</div>
                </div>
                <div class="stat-card">
                    <h3>Authentication</h3>
                    <div class="value auth">{auth_status}</div>
                    <div class="subtext">{auth_info}</div>
                </div>
            </div>

            <h2>Namespaces</h2>
            <table>
                <thead>
                    <tr>
                        <th>Namespace</th>
                        <th>Tools</th>
                        <th>MCP Endpoint</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {namespace_rows if namespace_rows else '<tr><td colspan="4">No namespaces configured</td></tr>'}
                </tbody>
            </table>

            <h2>API Endpoints</h2>
            <div class="info-box warning">
                <strong>Authentication:</strong> Use HTTP Basic Auth (username: <code>{ADMIN_USERNAME}</code>, password: your BEARER_TOKEN)
                or Bearer token in header.
            </div>
            <div class="api-section">
                <h3>Folder Management</h3>
                <div class="api-endpoint">
                    <span class="method get">GET</span>
                    <code>/api/folders</code> - List all folders
                </div>
                <div class="api-endpoint">
                    <span class="method post">POST</span>
                    <code>/api/folders</code> - Create folder
                </div>
                <div class="api-endpoint">
                    <span class="method delete">DELETE</span>
                    <code>/api/folders/{{namespace}}</code> - Delete folder
                </div>

                <h3 style="margin-top: 1rem;">Tool Management</h3>
                <div class="api-endpoint">
                    <span class="method get">GET</span>
                    <code>/api/folders/{{namespace}}/tools</code> - List tools
                </div>
                <div class="api-endpoint">
                    <span class="method post">POST</span>
                    <code>/api/folders/{{namespace}}/tools</code> - Upload tool
                </div>
                <div class="api-endpoint">
                    <span class="method post">POST</span>
                    <code>/api/folders/{{namespace}}/tools/validate</code> - Validate tool
                </div>
                <div class="api-endpoint">
                    <span class="method delete">DELETE</span>
                    <code>/api/folders/{{namespace}}/tools/{{filename}}</code> - Delete tool
                </div>

                <h3 style="margin-top: 1rem;">Server Management</h3>
                <div class="api-endpoint">
                    <span class="method get">GET</span>
                    <code>/api/servers</code> - List external servers
                </div>
                <div class="api-endpoint">
                    <span class="method post">POST</span>
                    <code>/api/servers</code> - Add server
                </div>
                <div class="api-endpoint">
                    <span class="method put">PUT</span>
                    <code>/api/servers/{{server_id}}</code> - Update server
                </div>
                <div class="api-endpoint">
                    <span class="method delete">DELETE</span>
                    <code>/api/servers/{{server_id}}</code> - Delete server
                </div>

                <h3 style="margin-top: 1rem;">MCP Endpoints</h3>
                <div class="api-endpoint">
                    <span class="method get">GET</span>
                    <code>/mcp/namespaces</code> - List namespaces
                </div>
                <div class="api-endpoint">
                    <span class="method post">POST</span>
                    <code>/mcp/{{namespace}}</code> - MCP JSON-RPC endpoint
                </div>
            </div>
        </div>

        <script>
            function logout() {{
                // Clear credentials by making a request with wrong credentials
                var xhr = new XMLHttpRequest();
                xhr.open("GET", "/", true);
                xhr.setRequestHeader("Authorization", "Basic " + btoa("logout:logout"));
                xhr.onreadystatechange = function() {{
                    if (xhr.readyState === 4) {{
                        // Redirect to trigger new login prompt
                        window.location.href = "/?logout=" + Date.now();
                    }}
                }};
                xhr.send();
            }}
        </script>
    </body>
    </html>
    """
