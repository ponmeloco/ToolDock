from __future__ import annotations

import json
from typing import Any

from app.mcp.session import SessionInfo, SessionManager
from app.mcp.stream import StreamManager
from app.tools.service import ManagerToolService


class ManagerMcpMethods:
    def __init__(self, service: ManagerToolService, sessions: SessionManager, streams: StreamManager):
        self._service = service
        self._sessions = sessions
        self._streams = streams

    async def dispatch(self, method: str, params: dict[str, Any], session: SessionInfo | None) -> dict[str, Any] | None:
        if method == "initialize":
            return await self.initialize(params)
        if method == "notifications/initialized":
            if session is None:
                return None
            await self.notifications_initialized(session)
            return None
        if method == "ping":
            return {"pong": True}
        if method == "tools/list":
            if session is None or not session.initialized:
                raise ValueError("notifications/initialized must be sent before tools/list")
            return {"tools": [self._to_mcp_tool(item) for item in self._service.list_tool_descriptors()]}
        if method == "tools/call":
            if session is None or not session.initialized:
                raise ValueError("notifications/initialized must be sent before tools/call")
            return await self.tools_call(params)
        raise KeyError(method)

    async def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        protocol = str(params.get("protocolVersion") or "")
        if protocol not in self._sessions.supported_versions:
            protocol = self._sessions.supported_versions[0]

        session = self._sessions.create(protocol)
        return {
            "protocolVersion": protocol,
            "serverInfo": {"name": "tooldock-manager", "version": "2.0.0"},
            "capabilities": {"tools": {"listChanged": True}},
            "sessionId": session.session_id,
        }

    async def notifications_initialized(self, session: SessionInfo) -> None:
        self._sessions.mark_initialized(session.session_id)
        self._streams.append_event(session.session_id, "ready", {"initialized": True})

    async def tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")

        descriptor = _descriptor_by_name(self._service.list_tool_descriptors(), name)
        if descriptor is None:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown manager tool: {name}"}],
            }

        missing = _missing_required_arguments(descriptor, arguments)
        if missing:
            required = _required_arguments(descriptor)
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Missing required arguments for {name}: {', '.join(missing)}. "
                            f"Required: {', '.join(required)}"
                        ),
                    }
                ],
            }

        try:
            result = await self._service.call_tool(name, arguments)
        except KeyError as exc:
            missing_key = str(exc.args[0]) if exc.args else ""
            if missing_key and missing_key != name:
                return {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": f"Missing required argument for {name}: {missing_key}",
                        }
                    ],
                }
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"Unknown manager tool: {name}"}],
            }
        except Exception as exc:  # noqa: BLE001
            message = str(exc).strip() or f"{type(exc).__name__} raised with no message"
            return {
                "isError": True,
                "content": [{"type": "text", "text": message}],
            }

        payload = {"content": [{"type": "text", "text": _safe_json(result)}]}
        # MCP structuredContent must be an object for broad client compatibility.
        if isinstance(result, dict):
            payload["structuredContent"] = result
        return payload

    def _to_mcp_tool(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        name = descriptor["name"]
        schema = descriptor.get("input_schema")
        if not isinstance(schema, dict):
            schema = {
                "type": "object",
                "additionalProperties": True,
            }
        return {
            "name": name,
            "title": name.replace("_", " ").title(),
            "description": descriptor.get("description", ""),
            "inputSchema": schema,
        }


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        return str(value)


def _descriptor_by_name(descriptors: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for descriptor in descriptors:
        if descriptor.get("name") == name:
            return descriptor
    return None


def _required_arguments(descriptor: dict[str, Any]) -> list[str]:
    schema = descriptor.get("input_schema")
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required]


def _missing_required_arguments(descriptor: dict[str, Any], arguments: dict[str, Any]) -> list[str]:
    required = _required_arguments(descriptor)
    return [field for field in required if field not in arguments]
