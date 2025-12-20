from __future__ import annotations

import os
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Dict

import mcp.types as types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.routing import Route

from app.auth import BearerAuthMiddleware
from app.loader import load_tools_from_directory
from app.registry import get_registry
from app.errors import ToolError


SERVER_NAME = os.getenv("MCP_SERVER_NAME", "mcp-tools-mcp")
TOOLS_DIR = os.getenv("TOOLS_DIR", os.path.join(os.getcwd(), "tools"))

logger = logging.getLogger("server")

mcp_server = Server(SERVER_NAME)


class SessionRegistry:
    def __init__(self):
        self._sessions: Dict[str, SseServerTransport] = {}

    def add(self, transport: SseServerTransport) -> str:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = transport
        return session_id

    def get(self, session_id: str) -> SseServerTransport | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]


session_registry = SessionRegistry()


@asynccontextmanager
async def lifespan(app: Starlette):
    registry = get_registry()
    load_tools_from_directory(registry, TOOLS_DIR)

    @mcp_server.list_tools()
    async def list_tools() -> list[types.Tool]:
        tools = registry.list_tools()
        return [
            types.Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_model.model_json_schema(),
            )
            for t in tools
        ]

    @mcp_server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.Content]:
        try:
            result = await registry.call(name, arguments or {})
            return [types.TextContent(type="text", text=str(result))]
        except ToolError as e:
            return [types.TextContent(type="text", text=str(e.to_dict()))]

    yield


async def handle_sse(request: Request):
    transport = SseServerTransport("/messages")
    session_id = session_registry.add(transport)
    logger.info(f"New SSE connection established. Session ID: {session_id}")

    try:
        async with mcp_server.run_to_transport(transport):
            transport._endpoint = f"/messages?session_id={session_id}"
            return await transport.handle_sse(request)
    except Exception as e:
        logger.error(f"SSE connection failed for {session_id}: {e}", exc_info=True)
        return Response("SSE connection failed", status_code=500)
    finally:
        session_registry.remove(session_id)


async def handle_messages(request: Request):
    session_id = request.query_params.get("session_id")
    if not session_id:
        return Response("Session ID required", status_code=400)

    transport = session_registry.get(session_id)
    if not transport:
        return Response("Session not found", status_code=404)

    try:
        return await transport.handle_post_message(request)
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        return Response("Internal Error", status_code=500)


async def handle_probe(request: Request):
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("method") == "initialize":
            params = body.get("params", {}) or {}
            response_content = {
                "jsonrpc": "2.0",
                "id": body.get("id", 0),
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": params.get("capabilities", {}) or {},
                    "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
                },
            }
            return JSONResponse(response_content, status_code=200)
    except Exception:
        pass

    return JSONResponse(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32700, "message": "Use GET /sse for SSE stream."}},
        status_code=200,
    )


async def health(request: Request):
    return JSONResponse({"status": "ok"}, status_code=200)


routes = [
    Route("/health", endpoint=health, methods=["GET"]),
    Route("/sse", endpoint=handle_sse, methods=["GET"]),
    Route("/sse", endpoint=handle_probe, methods=["POST"]),
    Route("/messages", endpoint=handle_messages, methods=["POST"]),
]

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    ),
    Middleware(
        BearerAuthMiddleware,
        public_paths={"/health"},
    ),
]

app = Starlette(
    debug=False,
    routes=routes,
    middleware=middleware,
    lifespan=lifespan,
)
