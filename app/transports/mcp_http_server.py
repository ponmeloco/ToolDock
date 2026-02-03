"""
MCP Streamable HTTP Transport Server

This module implements the Model Context Protocol (MCP) via Streamable HTTP.
It uses the same ToolRegistry as the OpenAPI server, so tools only need
to be defined once.

Supports namespace-based routing:
- /mcp/{namespace} - MCP endpoint for a specific namespace
- /mcp/namespaces - List all available namespaces
- /mcp - Global endpoint (all tools)

Security:
- Optional bearer token authentication (configurable via BEARER_TOKEN)
- Configurable CORS origins (via CORS_ORIGINS environment variable)

MCP Spec: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http

Usage:
    from app.transports.mcp_http_server import create_mcp_http_app
    from app.registry import get_registry

    app = create_mcp_http_app(get_registry())
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.middleware import TrailingNewlineMiddleware, RequestLoggingMiddleware
from app.metrics_store import init_metrics_store
from app.registry import ToolRegistry
from app.reload import ToolReloader
from app.errors import ToolError, ToolNotFoundError
from app.auth import verify_token, is_auth_enabled
from app.utils import get_cors_origins

logger = logging.getLogger("mcp-http")

SERVER_NAME = os.getenv("MCP_SERVER_NAME", "tooldock")
PROTOCOL_VERSION = os.getenv("MCP_PROTOCOL_VERSION", "2025-11-25")
_supported_versions_env = os.getenv("MCP_PROTOCOL_VERSIONS")
if _supported_versions_env:
    _supported_versions = _supported_versions_env
else:
    _supported_versions = (
        f"{PROTOCOL_VERSION},2025-03-26"
        if PROTOCOL_VERSION != "2025-03-26"
        else PROTOCOL_VERSION
    )
SUPPORTED_PROTOCOL_VERSIONS = [
    v.strip() for v in _supported_versions.split(",") if v.strip()
]


def create_mcp_http_app(
    registry: ToolRegistry,
    external_manager=None,
    external_config=None,
    fastmcp_manager=None,
) -> FastAPI:
    """
    Create a FastAPI app for MCP Streamable HTTP Transport.

    The server provides:
    - /mcp - Global endpoint (all tools from all namespaces)
    - /mcp/{namespace} - Namespace-specific endpoint
    - /mcp/namespaces - List available namespaces

    Args:
        registry: The shared ToolRegistry containing all registered tools

    Returns:
        FastAPI application with MCP endpoints
    """
    app = FastAPI(
        title=f"{SERVER_NAME} - MCP Streamable HTTP",
        description="Model Context Protocol server for tool execution with namespace routing",
        version="1.0.0",
    )

    # Configure CORS with environment-based origins
    cors_origins = get_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_origins != ["*"],  # Only allow credentials with specific origins
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Add trailing newline to JSON responses for better CLI output
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        app.add_middleware(TrailingNewlineMiddleware)
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    init_metrics_store(data_dir)
    if os.getenv("PYTEST_CURRENT_TEST") is None:
        app.add_middleware(RequestLoggingMiddleware, service_name="mcp")

    # Store registry in app state
    app.state.registry = registry

    # Initialize reloader (for admin endpoints)
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    tools_dir = os.path.join(data_dir, "tools")
    external_namespaces = None
    if external_manager is not None:
        try:
            external_namespaces = set(external_manager.get_stats().get("namespaces", []))
        except Exception:
            external_namespaces = None
    reloader = ToolReloader(registry, tools_dir, external_namespaces=external_namespaces)

    # Include admin router for runtime external management
    from app.admin.routes import router as admin_router, set_admin_context
    set_admin_context(registry, external_manager, external_config, reloader, fastmcp_manager)
    app.include_router(admin_router)

    # ==================== Handler Functions ====================

    async def handle_initialize(
        request_id: Any,
        params: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        requested_version = params.get("protocolVersion")
        if requested_version and requested_version not in SUPPORTED_PROTOCOL_VERSIONS:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": f"Unsupported protocolVersion: {requested_version}",
                    "data": {"supported": SUPPORTED_PROTOCOL_VERSIONS},
                },
            }
        ns_info = f" (namespace={namespace})" if namespace else ""
        logger.info(f"MCP Initialize from client: {client_info.get('name', 'unknown')}{ns_info}")

        server_name = f"{SERVER_NAME}/{namespace}" if namespace else SERVER_NAME

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {
                        "listChanged": False
                    }
                },
                "serverInfo": {
                    "name": server_name,
                    "version": "1.0.0"
                }
            }
        }

    async def handle_initialized(
        request_id: Any,
        params: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Handle MCP initialized notification (no response needed for notifications)."""
        ns_info = f" (namespace={namespace})" if namespace else ""
        logger.info(f"MCP client initialized{ns_info}")
        # Notifications don't get responses
        return None

    async def handle_ping(
        request_id: Any,
        params: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle MCP ping request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {}
        }

    async def handle_list_tools(
        request_id: Any,
        params: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle MCP tools/list request."""
        ns_info = f" (namespace={namespace})" if namespace else " (all namespaces)"
        logger.info(f"MCP: tools/list called{ns_info}")

        if namespace:
            # Return only tools from the specified namespace
            tools_list = registry.list_tools_for_namespace(namespace)
        else:
            # Return all tools from all namespaces
            all_tools = registry.list_all()
            tools_list = [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": tool["inputSchema"],
                }
                for tool in all_tools
            ]

        logger.info(f"MCP: Returning {len(tools_list)} tools{ns_info}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools_list
            }
        }

    async def handle_call_tool(
        request_id: Any,
        params: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle MCP tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        ns_info = f" (namespace={namespace})" if namespace else ""
        logger.info(f"MCP: tools/call - name={tool_name}{ns_info}")

        # Validate tool belongs to namespace (if namespace is specified)
        if namespace and not registry.tool_in_namespace(tool_name, namespace):
            logger.warning(f"MCP: Tool '{tool_name}' not in namespace '{namespace}'")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": f"Tool '{tool_name}' not found in namespace '{namespace}'"
                }
            }

        try:
            # Execute tool using shared registry
            result = await registry.call(tool_name, arguments)

            # Format result as MCP content
            if isinstance(result, str):
                text_content = result
            else:
                text_content = json.dumps(result, indent=2, ensure_ascii=False)

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text_content
                        }
                    ],
                    "isError": False
                }
            }

        except ToolNotFoundError as e:
            logger.error(f"MCP: Tool not found - {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Tool not found", "tool": tool_name})
                        }
                    ],
                    "isError": True
                }
            }

        except ToolError as e:
            logger.error(f"MCP: Tool error - {tool_name}: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Tool execution failed", "tool": tool_name})
                        }
                    ],
                    "isError": True
                }
            }

        except Exception as e:
            logger.error(f"MCP: Tool execution error - {tool_name}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Internal error", "tool": tool_name})
                        }
                    ],
                    "isError": True
                }
            }

    # Method handlers mapping
    METHOD_HANDLERS = {
        "initialize": handle_initialize,
        "initialized": handle_initialized,
        "notifications/initialized": handle_initialized,
        "ping": handle_ping,
        "tools/list": handle_list_tools,
        "tools/call": handle_call_tool,
    }

    def _validate_origin(request: Request) -> Optional[Response]:
        origin = request.headers.get("origin")
        if not origin:
            return None
        allowed = get_cors_origins()
        if allowed == ["*"]:
            return None
        if origin not in allowed:
            return Response(status_code=403)
        return None

    def _validate_protocol_header(request: Request) -> Optional[Response]:
        version = request.headers.get("MCP-Protocol-Version")
        if not version:
            # Per spec, assume default if absent
            return None
        if version not in SUPPORTED_PROTOCOL_VERSIONS:
            return Response(status_code=400)
        return None

    def _validate_accept_header(request: Request, require_stream: bool = False) -> Optional[Response]:
        accept = request.headers.get("accept", "")
        if require_stream:
            if "text/event-stream" not in accept:
                return Response(status_code=406)
            return None
        if "application/json" not in accept:
            return Response(status_code=400)
        return None

    async def process_jsonrpc_request(
        body: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC request."""
        # Reject JSON-RPC batching (removed in 2025-06-18)
        if isinstance(body, list):
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: JSON-RPC batching is not supported",
                },
            }

        # Validate JSON-RPC structure
        if body.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: jsonrpc must be '2.0'"
                }
            }

        method = body.get("method")
        if not method:
            # JSON-RPC response (no method, but result/error present)
            if "result" in body or "error" in body:
                return None
            return {
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: method is required"
                }
            }

        request_id = body.get("id")  # May be None for notifications
        params = body.get("params", {})

        # Check if this is a notification (no id)
        is_notification = request_id is None

        # Find and execute handler
        handler = METHOD_HANDLERS.get(method)
        if not handler:
            if is_notification:
                # Unknown notifications are ignored per spec
                logger.warning(f"MCP: Unknown notification method: {method}")
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

        try:
            response = await handler(request_id, params, namespace)
            return response
        except Exception as e:
            logger.error(f"MCP: Handler error for {method}", exc_info=True)
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error"
                }
            }

    # ==================== Endpoints ====================

    @app.get("/health")
    async def health():
        """Health check endpoint (no auth required)."""
        stats = registry.get_stats()
        return {
            "status": "healthy",
            "transport": "mcp-streamable-http",
            "protocol_version": PROTOCOL_VERSION,
            "server_name": SERVER_NAME,
            "auth_enabled": is_auth_enabled(),
            "tools": {
                "native": stats.get("native", 0),
                "external": stats.get("external", 0),
                "total": stats.get("total", 0),
                "namespaces": stats.get("namespaces", 0),
            },
        }

    @app.get("/mcp/namespaces")
    async def list_namespaces(_: str = Depends(verify_token)):
        """
        List all available namespaces.

        Each namespace can be accessed via /mcp/{namespace}
        """
        namespaces = registry.list_namespaces()
        stats = registry.get_stats()

        return {
            "namespaces": namespaces,
            "breakdown": stats.get("namespace_breakdown", {}),
            "total": len(namespaces),
        }

    @app.post("/mcp/{namespace}")
    async def mcp_namespace_endpoint(
        namespace: str,
        request: Request,
        _: str = Depends(verify_token),
    ):
        """
        MCP Streamable HTTP Endpoint for a specific namespace.

        Only tools registered under this namespace are accessible.
        Handles JSON-RPC 2.0 requests conforming to the MCP specification.

        Args:
            namespace: The namespace to use (e.g., 'shared', 'team1', 'github')
        """
        origin_error = _validate_origin(request)
        if origin_error:
            return origin_error
        protocol_error = _validate_protocol_header(request)
        if protocol_error:
            return protocol_error
        accept_error = _validate_accept_header(request, require_stream=False)
        if accept_error:
            return accept_error

        # Validate namespace exists
        if not registry.has_namespace(namespace):
            logger.warning(f"MCP: Request to unknown namespace: {namespace}")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": f"Unknown namespace: {namespace}",
                        "data": {
                            "available_namespaces": registry.list_namespaces()
                        }
                    }
                },
                status_code=200,  # JSON-RPC errors use 200 status
            )

        try:
            body = await request.json()
            method = body.get("method") if isinstance(body, dict) else "batch"
            logger.debug(f"MCP POST /{namespace}: method={method}")

            response = await process_jsonrpc_request(body, namespace)
            if response is None:
                # Notification or JSON-RPC response - return 202 Accepted (no content)
                return Response(status_code=202)
            return JSONResponse(content=response)

        except json.JSONDecodeError:
            logger.error("MCP: JSON parse error")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                },
                status_code=200,
            )

        except Exception:
            logger.error("MCP POST Error", exc_info=True)
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Internal error"
                    }
                },
                status_code=200,
            )

    @app.post("/mcp")
    async def mcp_endpoint(request: Request, _: str = Depends(verify_token)):
        """
        Global MCP Streamable HTTP Endpoint.

        Handles JSON-RPC 2.0 requests conforming to the MCP specification.
        All tools from all namespaces are accessible.
        """
        origin_error = _validate_origin(request)
        if origin_error:
            return origin_error
        protocol_error = _validate_protocol_header(request)
        if protocol_error:
            return protocol_error
        accept_error = _validate_accept_header(request, require_stream=False)
        if accept_error:
            return accept_error

        try:
            body = await request.json()
            method = body.get("method") if isinstance(body, dict) else "batch"
            logger.debug(f"MCP POST: method={method}")

            response = await process_jsonrpc_request(body, namespace=None)
            if response is None:
                # Notification or JSON-RPC response - return 202 Accepted (no content)
                return Response(status_code=202)
            return JSONResponse(content=response)

        except json.JSONDecodeError:
            logger.error("MCP: JSON parse error")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                },
                status_code=200,
            )

        except Exception:
            logger.error("MCP POST Error", exc_info=True)
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Internal error"
                    }
                },
                status_code=200,
            )

    @app.get("/mcp/info")
    async def mcp_info(_: str = Depends(verify_token)):
        """Non-standard discovery endpoint."""
        stats = registry.get_stats()
        return {
            "server": SERVER_NAME,
            "protocol": "MCP",
            "protocolVersion": PROTOCOL_VERSION,
            "supportedProtocolVersions": SUPPORTED_PROTOCOL_VERSIONS,
            "transport": "streamable-http",
            "endpoint": "/mcp",
            "namespace_endpoints": [f"/mcp/{ns}" for ns in registry.list_namespaces()],
            "methods": list(METHOD_HANDLERS.keys()),
            "tools": {
                "native": stats.get("native", 0),
                "external": stats.get("external", 0),
                "total": stats.get("total", 0),
            },
        }

    @app.get("/mcp/{namespace}/info")
    async def mcp_namespace_info(namespace: str, _: str = Depends(verify_token)):
        """Non-standard discovery endpoint for a namespace."""
        if not registry.has_namespace(namespace):
            return JSONResponse(
                content={
                    "error": f"Unknown namespace: {namespace}",
                    "available_namespaces": registry.list_namespaces(),
                },
                status_code=404,
            )
        tools = registry.list_tools_for_namespace(namespace)
        return {
            "server": f"{SERVER_NAME}/{namespace}",
            "namespace": namespace,
            "protocol": "MCP",
            "protocolVersion": PROTOCOL_VERSION,
            "supportedProtocolVersions": SUPPORTED_PROTOCOL_VERSIONS,
            "transport": "streamable-http",
            "endpoint": f"/mcp/{namespace}",
            "methods": list(METHOD_HANDLERS.keys()),
            "tools_count": len(tools),
        }

    @app.get("/mcp")
    async def mcp_get_stream(request: Request, _: str = Depends(verify_token)):
        """GET /mcp opens an SSE stream (may be idle)."""
        origin_error = _validate_origin(request)
        if origin_error:
            return origin_error
        protocol_error = _validate_protocol_header(request)
        if protocol_error:
            return protocol_error
        accept_error = _validate_accept_header(request, require_stream=True)
        if accept_error:
            return accept_error

        async def event_stream():
            yield b": ok\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/mcp/{namespace}")
    async def mcp_get_namespace_stream(namespace: str, request: Request, _: str = Depends(verify_token)):
        """GET /mcp/{namespace} opens an SSE stream (may be idle)."""
        origin_error = _validate_origin(request)
        if origin_error:
            return origin_error
        protocol_error = _validate_protocol_header(request)
        if protocol_error:
            return protocol_error
        accept_error = _validate_accept_header(request, require_stream=True)
        if accept_error:
            return accept_error
        if not registry.has_namespace(namespace):
            return JSONResponse(
                content={
                    "error": f"Unknown namespace: {namespace}",
                    "available_namespaces": registry.list_namespaces(),
                },
                status_code=404,
            )

        async def event_stream():
            yield b": ok\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # Sync FastMCP external servers (read from DB, connect + register tools)
    if fastmcp_manager is not None:
        try:
            import asyncio
            asyncio.run(fastmcp_manager.sync_from_db())
        except Exception as exc:
            logger.warning(f"FastMCP sync failed: {exc}")

    stats = registry.get_stats()
    logger.info(
        f"MCP Streamable HTTP server created with "
        f"{stats.get('native', 0)} native + {stats.get('external', 0)} external tools "
        f"across {stats.get('namespaces', 0)} namespace(s)"
    )
    return app
