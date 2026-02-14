from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import CoreSettings
from app.mcp.jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, error_response, is_notification, parse_request, success_response
from app.mcp.methods import McpMethods
from app.mcp.session import SessionInfo, SessionManager
from app.mcp.stream import StreamManager, format_sse


class McpHttpHandler:
    def __init__(
        self,
        settings: CoreSettings,
        methods: McpMethods,
        sessions: SessionManager,
        streams: StreamManager,
    ):
        self._settings = settings
        self._methods = methods
        self._sessions = sessions
        self._streams = streams

    async def handle_mcp_post(self, request: Request, namespace: str) -> Response:
        _validate_origin(request, self._settings)

        content_type = request.headers.get("content-type", "")
        if "application/json" not in content_type:
            return JSONResponse(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, content={"detail": "Content-Type must be application/json"})

        session_id = request.headers.get("mcp-session-id")
        provided_version = request.headers.get("mcp-protocol-version")
        protocol_version = self._sessions.resolve_protocol(provided_version, session_id)

        if protocol_version not in self._sessions.supported_versions:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "Unsupported MCP protocol version"})

        if not _accept_is_valid(request.headers.get("accept", ""), protocol_version):
            return JSONResponse(status_code=status.HTTP_406_NOT_ACCEPTABLE, content={"detail": "Invalid Accept header for protocol"})

        session: SessionInfo | None = None
        if session_id:
            session = self._sessions.get(session_id)
            if session is None:
                return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Unknown MCP session"})
            if provided_version and session.protocol_version != provided_version:
                return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "Protocol version mismatch for session"})

        parsed = parse_request(await request.body(), protocol_version)

        if isinstance(parsed, dict) and "error" in parsed and parsed.get("jsonrpc") == "2.0":
            return JSONResponse(status_code=status.HTTP_200_OK, content=parsed)

        if isinstance(parsed, list):
            responses = await self._dispatch_batch(parsed, namespace, session)
            if not responses:
                return Response(status_code=status.HTTP_202_ACCEPTED)
            return JSONResponse(status_code=status.HTTP_200_OK, content=responses)

        assert isinstance(parsed, dict)
        response_payload, session_header = await self._dispatch_single(parsed, namespace, session)
        if response_payload is None:
            return Response(status_code=status.HTTP_202_ACCEPTED)

        headers = {}
        if session_header:
            headers["Mcp-Session-Id"] = session_header
        return JSONResponse(status_code=status.HTTP_200_OK, content=response_payload, headers=headers)

    async def handle_mcp_get(self, request: Request, namespace: str) -> StreamingResponse:
        _validate_origin(request, self._settings)

        accept = request.headers.get("accept", "")
        if "text/event-stream" not in accept:
            raise HTTPException(status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="Accept must include text/event-stream")

        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mcp-Session-Id is required")

        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown MCP session")

        last_event_id = request.headers.get("last-event-id")
        replay = self._streams.replay_from(session_id, last_event_id)

        async def event_source():
            for event in replay:
                yield format_sse(event)

            subscriber = self._streams.subscribe(session_id)
            async for event in _with_keepalive(subscriber):
                if isinstance(event, str):
                    yield event
                else:
                    yield format_sse(event)

        return StreamingResponse(event_source(), media_type="text/event-stream")

    async def handle_mcp_delete(self, request: Request, namespace: str) -> Response:
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mcp-Session-Id is required")
        self._sessions.terminate(session_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def _dispatch_batch(
        self,
        payloads: list[dict[str, Any]],
        namespace: str,
        session: SessionInfo | None,
    ) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        for payload in payloads:
            if "error" in payload and payload.get("jsonrpc") == "2.0":
                responses.append(payload)
                continue
            response, _ = await self._dispatch_single(payload, namespace, session)
            if response is not None:
                responses.append(response)
        return responses

    async def _dispatch_single(
        self,
        payload: dict[str, Any],
        namespace: str,
        session: SessionInfo | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if "error" in payload and payload.get("jsonrpc") == "2.0":
            return payload, None

        method = payload["method"]
        params = payload.get("params") or {}
        request_id = payload.get("id")

        if method != "initialize" and session is None:
            result = error_response(request_id, INVALID_PARAMS, "Mcp-Session-Id required after initialize")
            return result, None

        try:
            result = await self._methods.dispatch(method, params, namespace, session)
        except KeyError:
            result = error_response(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
            return result, None
        except ValueError as exc:
            result = error_response(request_id, INVALID_PARAMS, str(exc))
            return result, None
        except Exception as exc:  # noqa: BLE001
            result = error_response(request_id, -32000, str(exc))
            return result, None

        if is_notification(payload):
            return None, None

        response = success_response(request_id, result)
        session_header = None

        if method == "initialize" and isinstance(result, dict):
            session_header = str(result.get("sessionId") or "")

        return response, session_header


async def _with_keepalive(source):
    ait = source.__aiter__()
    while True:
        try:
            event = await asyncio.wait_for(ait.__anext__(), timeout=15)
            yield event
        except TimeoutError:
            yield ": keepalive\n\n"


def _accept_is_valid(accept_header: str, protocol_version: str) -> bool:
    accept = {part.strip() for part in accept_header.split(",") if part.strip()}
    if protocol_version in {"2025-06-18", "2025-11-25"}:
        return "application/json" in accept and "text/event-stream" in accept
    return "application/json" in accept or (
        "application/json" in accept and "text/event-stream" in accept
    )


def _validate_origin(request: Request, settings: CoreSettings) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return

    allowed = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    if "*" in allowed:
        return
    if origin in allowed:
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is not allowed")
