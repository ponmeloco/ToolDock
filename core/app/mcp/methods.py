from __future__ import annotations

import json
from typing import Any

from app.engine import NamespaceNotFound, ToolEngine, ToolNotFound
from app.mcp.session import SessionInfo, SessionManager
from app.mcp.stream import StreamManager
from app.workers.protocol import WorkerError


class McpMethods:
    def __init__(self, engine: ToolEngine, sessions: SessionManager, streams: StreamManager, server_name: str):
        self._engine = engine
        self._sessions = sessions
        self._streams = streams
        self._server_name = server_name

    async def dispatch(
        self,
        method: str,
        params: dict[str, Any],
        namespace: str,
        session: SessionInfo | None,
    ) -> dict[str, Any] | None:
        if method == "initialize":
            return await self.initialize(params)
        if method == "notifications/initialized":
            if session is None:
                return None
            await self.notifications_initialized(session)
            return None
        if method == "ping":
            return await self.ping()
        if method == "tools/list":
            if session is None:
                raise ValueError("Session required for tools/list")
            if not session.initialized:
                raise ValueError("notifications/initialized must be sent before tools/list")
            return await self.tools_list(namespace)
        if method == "tools/call":
            if session is None:
                raise ValueError("Session required for tools/call")
            if not session.initialized:
                raise ValueError("notifications/initialized must be sent before tools/call")
            return await self.tools_call(namespace, params)
        raise KeyError(method)

    async def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        protocol = str(params.get("protocolVersion") or "")
        if protocol not in self._sessions.supported_versions:
            protocol = self._sessions.supported_versions[0]

        session = self._sessions.create(protocol)
        return {
            "protocolVersion": protocol,
            "serverInfo": {
                "name": self._server_name,
                "version": "2.0.0",
            },
            "capabilities": {
                "tools": {
                    "listChanged": True,
                },
            },
            "sessionId": session.session_id,
        }

    async def notifications_initialized(self, session: SessionInfo) -> None:
        self._sessions.mark_initialized(session.session_id)
        self._streams.append_event(session.session_id, "ready", {"initialized": True})

    async def ping(self) -> dict[str, Any]:
        return {"pong": True}

    async def tools_list(self, namespace: str) -> dict[str, Any]:
        tools = await self._engine.list_mcp_tools(namespace)
        return {"tools": tools}

    async def tools_call(self, namespace: str, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")

        try:
            result = await self._engine.call_tool(namespace, name, arguments)
        except (NamespaceNotFound, ToolNotFound) as exc:
            return {
                "isError": True,
                "content": [{"type": "text", "text": str(exc)}],
            }
        except WorkerError as exc:
            return {
                "isError": True,
                "content": [{"type": "text", "text": exc.message}],
                "error": {"code": exc.code, "details": exc.details or {}},
            }

        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": _safe_json(result)}],
        }
        # MCP structuredContent must be an object for broad client compatibility.
        if isinstance(result, dict):
            payload["structuredContent"] = result
        return payload


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return str(value)
