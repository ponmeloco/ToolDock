"""
MCP Streamable HTTP Transport Server

This module implements the Model Context Protocol (MCP) via Streamable HTTP.
It uses the same ToolRegistry as the OpenAPI server, so tools only need
to be defined once.

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
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.registry import ToolRegistry
from app.errors import ToolError, ToolNotFoundError

logger = logging.getLogger("mcp-http")

SERVER_NAME = os.getenv("MCP_SERVER_NAME", "omnimcp")
PROTOCOL_VERSION = "2024-11-05"


def create_mcp_http_app(registry: ToolRegistry) -> FastAPI:
    """
    Create a FastAPI app for MCP Streamable HTTP Transport.

    The server provides a /mcp endpoint that accepts POST requests
    with JSON-RPC 2.0 messages, conforming to the MCP specification.

    Args:
        registry: The shared ToolRegistry containing all registered tools

    Returns:
        FastAPI application with MCP endpoint
    """
    app = FastAPI(
        title=f"{SERVER_NAME} - MCP Streamable HTTP",
        description="Model Context Protocol server for tool execution",
        version="1.0.0",
    )

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store registry in app state
    app.state.registry = registry

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        stats = registry.get_stats()
        return {
            "status": "healthy",
            "transport": "mcp-streamable-http",
            "protocol_version": PROTOCOL_VERSION,
            "server_name": SERVER_NAME,
            "tools": stats,
        }

    async def handle_initialize(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        logger.info(f"MCP Initialize from client: {client_info.get('name', 'unknown')}")

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
                    "name": SERVER_NAME,
                    "version": "1.0.0"
                }
            }
        }

    async def handle_initialized(request_id: Any, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle MCP initialized notification (no response needed for notifications)."""
        logger.info("MCP client initialized")
        # Notifications don't get responses
        return None

    async def handle_ping(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP ping request."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {}
        }

    async def handle_list_tools(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tools/list request."""
        logger.info("MCP: tools/list called")

        # Use list_all() to include both native and external tools
        all_tools = registry.list_all()
        tools_list = [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
            for tool in all_tools
        ]

        logger.info(f"MCP: Returning {len(tools_list)} tools (native + external)")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools_list
            }
        }

    async def handle_call_tool(request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        logger.info(f"MCP: tools/call - name={tool_name}, arguments={arguments}")

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
            logger.error(f"MCP: Tool not found - {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Tool not found", "details": str(e)})
                        }
                    ],
                    "isError": True
                }
            }

        except ToolError as e:
            logger.error(f"MCP: Tool error - {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(e.to_dict())
                        }
                    ],
                    "isError": True
                }
            }

        except Exception as e:
            logger.error(f"MCP: Tool execution error - {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": "Execution failed", "details": str(e)})
                        }
                    ],
                    "isError": True
                }
            }

    # Method handlers mapping
    METHOD_HANDLERS = {
        "initialize": handle_initialize,
        "initialized": handle_initialized,
        "ping": handle_ping,
        "tools/list": handle_list_tools,
        "tools/call": handle_call_tool,
    }

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        """
        MCP Streamable HTTP Endpoint.

        Handles JSON-RPC 2.0 requests conforming to the MCP specification.
        """
        try:
            body = await request.json()
            logger.debug(f"MCP POST: {body}")

            # Handle single request or batch
            if isinstance(body, list):
                # Batch request
                responses = []
                for item in body:
                    response = await process_jsonrpc_request(item)
                    if response is not None:  # Notifications don't return responses
                        responses.append(response)
                return JSONResponse(content=responses if responses else None)
            else:
                # Single request
                response = await process_jsonrpc_request(body)
                if response is None:
                    # Notification - return 204 No Content
                    return Response(status_code=204)
                return JSONResponse(content=response)

        except json.JSONDecodeError as e:
            logger.error(f"MCP: JSON parse error - {e}")
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error",
                        "data": str(e)
                    }
                },
                status_code=200  # JSON-RPC errors use 200 status
            )

        except Exception as e:
            logger.error(f"MCP POST Error: {e}", exc_info=True)
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": "Internal error",
                        "data": str(e)
                    }
                },
                status_code=200
            )

    async def process_jsonrpc_request(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC request."""
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
            response = await handler(request_id, params)
            return response
        except Exception as e:
            logger.error(f"MCP: Handler error for {method}: {e}", exc_info=True)
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }

    @app.get("/mcp")
    async def mcp_get_info():
        """
        GET /mcp returns server info and available methods.

        This is not part of the MCP spec but useful for discovery.
        """
        stats = registry.get_stats()
        return {
            "server": SERVER_NAME,
            "protocol": "MCP",
            "protocolVersion": PROTOCOL_VERSION,
            "transport": "streamable-http",
            "endpoint": "/mcp",
            "methods": list(METHOD_HANDLERS.keys()),
            "tools": stats,
        }

    stats = registry.get_stats()
    logger.info(
        f"MCP Streamable HTTP server created with "
        f"{stats['native']} native + {stats['external']} external tools"
    )
    return app
