"""
MCP Streamable HTTP Transport Server

This module implements the Model Context Protocol (MCP) via Streamable HTTP.
It uses the same ToolRegistry as the OpenAPI server, so tools only need
to be defined once.

Supports namespace-based routing:
- /{namespace}/mcp - Namespace-scoped endpoint
- /mcp - Global endpoint (all tools)

Security:
- Optional bearer token authentication (configurable via BEARER_TOKEN)
- Configurable CORS origins (via CORS_ORIGINS environment variable)

MCP Spec: https://modelcontextprotocol.io/specification/2025-03-26/basic/transports

Usage:
    from app.transports.mcp_http_server import create_mcp_http_app
    from app.registry import get_registry

    app = create_mcp_http_app(get_registry())
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.middleware import TrailingNewlineMiddleware, RequestLoggingMiddleware
from app.metrics_store import init_metrics_store
from app.registry import ToolRegistry
from app.reload import ToolReloader
from app.errors import ToolError, ToolNotFoundError
from app.auth import verify_token, is_auth_enabled
from app.utils import get_cors_origins, set_request_context

logger = logging.getLogger("mcp-http")

SERVER_NAME = os.getenv("MCP_SERVER_NAME", "tooldock")
# Default to the oldest widely-supported protocol version for compatibility
# with clients (LM Studio, Claude Desktop bridges, etc.).
PROTOCOL_VERSION = os.getenv("MCP_PROTOCOL_VERSION", "2024-11-05")
_supported_versions_env = os.getenv("MCP_PROTOCOL_VERSIONS")
if _supported_versions_env:
    _supported_versions = _supported_versions_env
else:
    _supported_versions = ",".join([PROTOCOL_VERSION, "2025-03-26"])
SUPPORTED_PROTOCOL_VERSIONS = [
    v.strip() for v in _supported_versions.split(",") if v.strip()
]

# Reserved prefixes that cannot be used as namespace names in /{namespace}/mcp routes.
# FastAPI registers static routes before dynamic ones in declaration order, but this
# set acts as a safety net for edge cases.
RESERVED_PREFIXES = {
    "api", "mcp", "openapi", "docs", "assets", "health", "tools", "static",
}


def create_mcp_http_app(
    registry: ToolRegistry,
    fastmcp_manager=None,
) -> FastAPI:
    """
    Create a FastAPI app for MCP Streamable HTTP Transport.

    The server provides:
    - /{namespace}/mcp - Namespace-scoped endpoint
    - /mcp - Global endpoint (all tools from all namespaces)

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
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "Mcp-Session-Id", "MCP-Protocol-Version"],
        expose_headers=["Mcp-Session-Id"],
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
    # Per-client session store: {session_id: {namespace, created_at, client_info}}
    app.state._mcp_sessions: Dict[str, dict] = {}
    # SSE subscribers: GET streams for server-initiated messages only.
    # Per MCP spec (2025-03-26), POST responses are NOT echoed here.
    app.state._mcp_sse_subscribers_global: set[asyncio.Queue] = set()
    app.state._mcp_sse_subscribers_by_ns: dict[str, set[asyncio.Queue]] = {}

    # Initialize reloader (for admin endpoints)
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    tools_dir = os.path.join(data_dir, "tools")
    reloader = ToolReloader(registry, tools_dir)

    # Include admin router for runtime external management
    from app.admin.routes import router as admin_router, set_admin_context
    set_admin_context(registry, reloader, fastmcp_manager)
    app.include_router(admin_router)

    # ==================== Handler Functions ====================

    async def handle_initialize(
        request_id: Any,
        params: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Handle MCP initialize request.

        Returns the JSON-RPC response dict. The caller (_handle_mcp_post)
        creates the session and attaches the Mcp-Session-Id header.
        """
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
        negotiated_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else PROTOCOL_VERSION
        )

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": negotiated_version,
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

        # Resolve tool name: strip client prefixes (default__x) and recover
        # dropped namespace prefixes (install_x → ns:install_x).
        if tool_name and not registry.has_tool(tool_name):
            resolved = tool_name
            if "__" in tool_name:
                resolved = tool_name.rsplit("__", 1)[-1]
            if not registry.has_tool(resolved):
                suffix = f":{resolved}"
                for t in registry.list_all():
                    if t["name"].endswith(suffix):
                        resolved = t["name"]
                        break
            if registry.has_tool(resolved):
                tool_name = resolved

        ns_info = f" (namespace={namespace})" if namespace else ""
        logger.info(f"MCP: tools/call - name={tool_name}{ns_info}")
        set_request_context(tool_name=tool_name)

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
            # Some clients send older/newer versions; failing hard here breaks
            # interoperability. We still validate the negotiated version during
            # `initialize` (params.protocolVersion).
            logger.warning(f"Ignoring unsupported MCP-Protocol-Version header: {version}")
            return None
        return None

    def _validate_accept_header(request: Request, require_stream: bool = False) -> Optional[Response]:
        accept = request.headers.get("accept", "").lower()
        if require_stream:
            if "text/event-stream" not in accept:
                return Response(status_code=406)
            return None
        # For JSON-RPC POST endpoints, be permissive for compatibility:
        # allow missing Accept, */*, application/*, or application/json.
        if not accept:
            return None
        # Some clients send only text/event-stream even for POST, expecting
        # a single-event SSE response.
        if "text/event-stream" in accept:
            return None
        if "*/*" in accept or "application/*" in accept or "application/json" in accept:
            return None
        # Client explicitly asked for something incompatible with JSON responses.
        return Response(status_code=406)

    def _validate_content_type(request: Request) -> Optional[Response]:
        """Validate Content-Type header on POST requests.

        Per MCP spec, POST bodies must be JSON. Reject explicitly non-JSON
        Content-Types with -32700. Missing Content-Type is accepted (lenient).
        """
        ct = request.headers.get("content-type", "").lower().split(";")[0].strip()
        if not ct:
            return None  # Missing is OK
        if ct in ("application/json", "application/*", "*/*"):
            return None
        return _json_response(
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: unsupported Content-Type '{ct}', expected application/json",
                },
            },
        )

    def _sse_message(payload: Dict[str, Any]) -> bytes:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")

    _SESSION_MAX_AGE = 24 * 60 * 60  # 24 hours

    def _create_session(
        namespace: Optional[str] = None,
        client_info: Optional[dict] = None,
    ) -> str:
        """Create a new MCP session and return its ID."""
        session_id = str(uuid.uuid4())
        now = time.time()
        app.state._mcp_sessions[session_id] = {
            "namespace": namespace,
            "created_at": now,
            "client_info": client_info or {},
        }
        # Evict expired sessions
        cutoff = now - _SESSION_MAX_AGE
        expired = [
            sid for sid, meta in app.state._mcp_sessions.items()
            if meta["created_at"] < cutoff
        ]
        for sid in expired:
            del app.state._mcp_sessions[sid]
        return session_id

    def _validate_session(request: Request) -> Optional[Response]:
        """Validate Mcp-Session-Id header if present.

        Returns None if valid or absent (lenient). Returns a 404 Response
        if the header is present but the session is unknown/expired.
        """
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            return None  # Lenient: allow sessionless requests
        if session_id not in app.state._mcp_sessions:
            return _json_response(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Invalid or expired session",
                    },
                },
                status_code=404,
            )
        return None

    def _session_headers(session_id: Optional[str] = None) -> Dict[str, str]:
        if session_id:
            return {"Mcp-Session-Id": session_id}
        return {}

    def _json_response(
        content: Any,
        status_code: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ) -> Response:
        """Return a JSON response with exact Content-Type: application/json.

        FastAPI's JSONResponse appends '; charset=utf-8' which strict MCP
        clients (e.g. LM Studio) may reject.
        """
        body = json.dumps(content, ensure_ascii=False).encode("utf-8")
        return Response(
            content=body,
            status_code=status_code,
            media_type="application/json",
            headers=headers,
        )

    def _subscribe_sse(namespace: Optional[str]) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        if namespace:
            app.state._mcp_sse_subscribers_by_ns.setdefault(namespace, set()).add(q)
        else:
            app.state._mcp_sse_subscribers_global.add(q)
        return q

    def _unsubscribe_sse(namespace: Optional[str], q: asyncio.Queue) -> None:
        try:
            if namespace:
                subs = app.state._mcp_sse_subscribers_by_ns.get(namespace)
                if subs:
                    subs.discard(q)
                    if not subs:
                        app.state._mcp_sse_subscribers_by_ns.pop(namespace, None)
            else:
                app.state._mcp_sse_subscribers_global.discard(q)
        except Exception:
            return

    def _publish_sse(namespace: Optional[str], payload: Dict[str, Any]) -> None:
        """Publish a server-initiated message to SSE subscribers.

        Per MCP spec (2025-03-26), GET SSE streams MUST NOT receive
        JSON-RPC *responses* — only server-initiated requests and
        notifications.  POST handlers therefore should NOT call this
        for regular request/response traffic; the HTTP response body
        already delivers the result to the client.

        This function is reserved for future server-initiated messages
        (e.g. tools/listChanged notifications).
        """
        targets: set[asyncio.Queue] = set(app.state._mcp_sse_subscribers_global)
        if namespace:
            targets |= set(app.state._mcp_sse_subscribers_by_ns.get(namespace, set()))

        if not targets:
            return

        for q in targets:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                continue
            except Exception:
                continue

    async def process_jsonrpc_request(
        body: Dict[str, Any],
        namespace: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC request."""
        # Reject JSON-RPC batching (not supported by MCP spec)
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

    # ==================== Shared Route Handlers ====================

    async def _handle_mcp_post(
        request: Request,
        namespace: Optional[str] = None,
    ) -> Response:
        """Shared POST handler for all MCP endpoints."""
        origin_error = _validate_origin(request)
        if origin_error:
            return origin_error
        protocol_error = _validate_protocol_header(request)
        if protocol_error:
            return protocol_error
        accept_error = _validate_accept_header(request, require_stream=False)
        if accept_error:
            return accept_error
        content_type_error = _validate_content_type(request)
        if content_type_error:
            return content_type_error

        # Parse body early so we can detect method before session validation
        try:
            body = await request.json()
        except json.JSONDecodeError:
            logger.error("MCP: JSON parse error")
            return _json_response(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                },
            )

        method = body.get("method") if isinstance(body, dict) else "batch"
        is_initialize = method == "initialize"

        # Enrich request context for logging/metrics.
        # For tools/call the tool_name is set later in handle_call_tool;
        # for other methods, record the JSON-RPC method itself.
        if method and method != "tools/call":
            set_request_context(tool_name=f"mcp:{method}")

        # Session validation: skip for initialize (creates a new session),
        # validate for all other requests if header is present
        if not is_initialize:
            session_error = _validate_session(request)
            if session_error:
                return session_error

        # Determine current session_id from header (for non-initialize requests)
        current_session_id = request.headers.get("mcp-session-id")

        # Validate namespace exists (if specified)
        if namespace is not None:
            if not registry.has_namespace(namespace):
                logger.warning(f"MCP: Request to unknown namespace: {namespace}")
                req_id = body.get("id") if isinstance(body, dict) else None
                return _json_response(
                    content={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32600,
                            "message": f"Unknown namespace: {namespace}",
                            "data": {
                                "available_namespaces": registry.list_namespaces()
                            }
                        }
                    },
                    headers=_session_headers(current_session_id),
                )

        try:
            ns_label = f"/{namespace}" if namespace else ""
            logger.debug(f"MCP POST{ns_label}: method={method}")

            response = await process_jsonrpc_request(body, namespace)

            # For initialize: create a new session and include it in headers
            if is_initialize and response and "result" in response:
                client_info = {}
                if isinstance(body, dict):
                    client_info = body.get("params", {}).get("clientInfo", {})
                current_session_id = _create_session(namespace, client_info)

            headers = _session_headers(current_session_id)

            if response is None:
                return Response(status_code=202, headers=headers)
            return _json_response(content=response, headers=headers)

        except Exception:
            logger.error("MCP POST Error", exc_info=True)
            return _json_response(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Internal error"
                    }
                },
                headers=_session_headers(current_session_id),
            )

    async def _handle_mcp_sse_get(
        request: Request,
        namespace: Optional[str] = None,
    ) -> Response:
        """Shared GET SSE handler for all MCP endpoints."""
        origin_error = _validate_origin(request)
        if origin_error:
            return origin_error
        protocol_error = _validate_protocol_header(request)
        if protocol_error:
            return protocol_error
        accept_error = _validate_accept_header(request, require_stream=True)
        if accept_error:
            return accept_error

        session_error = _validate_session(request)
        if session_error:
            return session_error

        if namespace is not None and not registry.has_namespace(namespace):
            return _json_response(
                content={
                    "error": f"Unknown namespace: {namespace}",
                    "available_namespaces": registry.list_namespaces(),
                },
                status_code=404,
            )

        current_session_id = request.headers.get("mcp-session-id")
        resp_headers = {
            "Cache-Control": "no-cache",
            **_session_headers(current_session_id),
        }

        async def event_stream():
            if os.getenv("PYTEST_CURRENT_TEST") is not None:
                yield b": ok\n\n"
                return

            q = _subscribe_sse(namespace)
            try:
                yield b": connected\n\n"
                while True:
                    try:
                        item = await asyncio.wait_for(q.get(), timeout=15)
                        yield _sse_message(item)
                    except TimeoutError:
                        yield b": heartbeat\n\n"
            except asyncio.CancelledError:
                return
            finally:
                _unsubscribe_sse(namespace, q)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers=resp_headers,
        )

    async def _handle_mcp_delete(request: Request) -> Response:
        """Shared DELETE handler — terminate an MCP session."""
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            return _json_response(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Missing Mcp-Session-Id header",
                    },
                },
                status_code=400,
            )
        if session_id not in app.state._mcp_sessions:
            return _json_response(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Invalid or expired session",
                    },
                },
                status_code=404,
            )
        del app.state._mcp_sessions[session_id]
        logger.info(f"MCP session terminated: {session_id}")
        return Response(status_code=200)

    def _validate_dynamic_namespace(namespace: str) -> Optional[Response]:
        """Return a 404 response if namespace is a reserved prefix."""
        if namespace in RESERVED_PREFIXES:
            return _json_response(
                content={"error": f"Reserved prefix: {namespace}"},
                status_code=404,
            )
        return None

    # ==================== Static Endpoints (registered FIRST) ====================

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

        Each namespace can be accessed via /{namespace}/mcp
        """
        namespaces = registry.list_namespaces()
        stats = registry.get_stats()

        return {
            "namespaces": namespaces,
            "breakdown": stats.get("namespace_breakdown", {}),
            "total": len(namespaces),
        }

    @app.get("/mcp/info")
    async def mcp_info(_: str = Depends(verify_token)):
        """Non-standard discovery endpoint."""
        stats = registry.get_stats()
        ns_list = registry.list_namespaces()
        return {
            "server": SERVER_NAME,
            "protocol": "MCP",
            "protocolVersion": PROTOCOL_VERSION,
            "supportedProtocolVersions": SUPPORTED_PROTOCOL_VERSIONS,
            "transport": "streamable-http",
            "endpoint": "/mcp",
            "namespace_endpoints": [f"/{ns}/mcp" for ns in ns_list],
            "methods": list(METHOD_HANDLERS.keys()),
            "tools": {
                "native": stats.get("native", 0),
                "external": stats.get("external", 0),
                "total": stats.get("total", 0),
            },
        }

    # ==================== Global /mcp Endpoints ====================

    @app.post("/mcp")
    async def mcp_endpoint(request: Request, _: str = Depends(verify_token)):
        """
        Global MCP Streamable HTTP Endpoint.

        Handles JSON-RPC 2.0 requests conforming to the MCP specification.
        All tools from all namespaces are accessible.
        """
        return await _handle_mcp_post(request, namespace=None)

    @app.api_route("/mcp", methods=["DELETE"])
    async def mcp_delete_global(request: Request, _: str = Depends(verify_token)):
        """DELETE /mcp — terminate an MCP session."""
        return await _handle_mcp_delete(request)

    @app.get("/mcp")
    async def mcp_get_stream(request: Request, _: str = Depends(verify_token)):
        """GET /mcp opens an SSE stream (may be idle)."""
        return await _handle_mcp_sse_get(request, namespace=None)

    @app.api_route("/mcp/sse", methods=["GET", "POST"])
    async def mcp_sse_alias(request: Request, _: str = Depends(verify_token)):
        """
        Compatibility endpoint for clients that use /sse for both:
        - GET: open SSE stream
        - POST: send JSON-RPC messages
        """
        if request.method == "POST":
            return await _handle_mcp_post(request, namespace=None)
        return await _handle_mcp_sse_get(request, namespace=None)

    # ==================== /{namespace}/mcp Endpoints ====================

    @app.post("/{namespace}/mcp")
    async def ns_mcp_post(
        namespace: str,
        request: Request,
        _: str = Depends(verify_token),
    ):
        """
        MCP Streamable HTTP Endpoint for a specific namespace (preferred URL pattern).

        Only tools registered under this namespace are accessible.
        """
        reserved_error = _validate_dynamic_namespace(namespace)
        if reserved_error:
            return reserved_error
        return await _handle_mcp_post(request, namespace=namespace)

    @app.get("/{namespace}/mcp")
    async def ns_mcp_get(
        namespace: str,
        request: Request,
        _: str = Depends(verify_token),
    ):
        """GET /{namespace}/mcp opens an SSE stream for server-initiated messages."""
        reserved_error = _validate_dynamic_namespace(namespace)
        if reserved_error:
            return reserved_error
        return await _handle_mcp_sse_get(request, namespace=namespace)

    @app.api_route("/{namespace}/mcp", methods=["DELETE"])
    async def ns_mcp_delete(
        namespace: str,
        request: Request,
        _: str = Depends(verify_token),
    ):
        """DELETE /{namespace}/mcp — terminate an MCP session."""
        reserved_error = _validate_dynamic_namespace(namespace)
        if reserved_error:
            return reserved_error
        return await _handle_mcp_delete(request)

    @app.api_route("/{namespace}/mcp/sse", methods=["GET", "POST"])
    async def ns_mcp_sse_alias(
        namespace: str,
        request: Request,
        _: str = Depends(verify_token),
    ):
        """
        Compatibility endpoint for clients that use /sse:
        - GET: open SSE stream
        - POST: send JSON-RPC messages
        """
        reserved_error = _validate_dynamic_namespace(namespace)
        if reserved_error:
            return reserved_error
        if request.method == "POST":
            return await _handle_mcp_post(request, namespace=namespace)
        return await _handle_mcp_sse_get(request, namespace=namespace)

    @app.get("/{namespace}/mcp/info")
    async def ns_mcp_info(namespace: str, _: str = Depends(verify_token)):
        """Non-standard discovery endpoint for a namespace."""
        reserved_error = _validate_dynamic_namespace(namespace)
        if reserved_error:
            return reserved_error
        if not registry.has_namespace(namespace):
            return _json_response(
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
            "endpoint": f"/{namespace}/mcp",
            "methods": list(METHOD_HANDLERS.keys()),
            "tools_count": len(tools),
        }

    # Sync FastMCP external servers (read from DB, connect + register tools)
    if fastmcp_manager is not None:
        try:
            asyncio.run(fastmcp_manager.sync_from_db())
        except BaseException as exc:
            logger.warning(f"FastMCP sync failed: {exc}")

    stats = registry.get_stats()
    logger.info(
        f"MCP Streamable HTTP server created with "
        f"{stats.get('native', 0)} native + {stats.get('external', 0)} external tools "
        f"across {stats.get('namespaces', 0)} namespace(s)"
    )
    return app
