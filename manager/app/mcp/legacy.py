from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.mcp.jsonrpc import INVALID_PARAMS, METHOD_NOT_FOUND, error_response, is_notification, parse_request, success_response
from app.mcp.methods import ManagerMcpMethods
from app.mcp.session import SessionInfo, SessionManager
from app.mcp.stream import StreamManager, format_sse


class ManagerLegacyMcpAdapter:
    def __init__(self, methods: ManagerMcpMethods, sessions: SessionManager, streams: StreamManager):
        self._methods = methods
        self._sessions = sessions
        self._streams = streams

    async def handle_sse(self, request: Request) -> StreamingResponse:
        session = self._sessions.create("2025-03-26")
        session.initialized = True

        endpoint_data = {"endpoint": f"/messages?session_id={session.session_id}"}
        endpoint_event = self._streams.append_event(session.session_id, "endpoint", endpoint_data)

        async def event_source():
            yield f"id: {endpoint_event}\nevent: endpoint\ndata: {json.dumps(endpoint_data, separators=(',', ':'))}\n\n"

            subscriber = self._streams.subscribe(session.session_id)
            async for event in _with_keepalive(subscriber):
                if isinstance(event, str):
                    yield event
                else:
                    yield format_sse(event)

        return StreamingResponse(event_source(), media_type="text/event-stream", headers={"Mcp-Session-Id": session.session_id})

    async def handle_messages(self, request: Request) -> Response:
        session_id = request.query_params.get("session_id")
        if not session_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_id query parameter is required")

        session = self._sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown session")

        parsed = parse_request(await request.body(), "2025-03-26")
        if isinstance(parsed, dict) and "error" in parsed and parsed.get("jsonrpc") == "2.0":
            return JSONResponse(status_code=status.HTTP_200_OK, content=parsed)

        if isinstance(parsed, list):
            out: list[dict[str, Any]] = []
            for payload in parsed:
                response = await self._dispatch(payload, session)
                if response is not None:
                    out.append(response)
            if not out:
                return Response(status_code=status.HTTP_202_ACCEPTED)
            return JSONResponse(status_code=status.HTTP_200_OK, content=out)

        assert isinstance(parsed, dict)
        response = await self._dispatch(parsed, session)
        if response is None:
            return Response(status_code=status.HTTP_202_ACCEPTED)
        return JSONResponse(status_code=status.HTTP_200_OK, content=response)

    async def _dispatch(self, payload: dict[str, Any], session: SessionInfo) -> dict[str, Any] | None:
        if "error" in payload and payload.get("jsonrpc") == "2.0":
            return payload

        method = payload["method"]
        params = payload.get("params") or {}
        request_id = payload.get("id")

        try:
            result = await self._methods.dispatch(method, params, session)
        except KeyError:
            result = error_response(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")
            return result
        except ValueError as exc:
            result = error_response(request_id, INVALID_PARAMS, str(exc))
            return result
        except Exception as exc:  # noqa: BLE001
            result = error_response(request_id, -32000, str(exc))
            return result

        if is_notification(payload):
            return None
        return success_response(request_id, result)


async def _with_keepalive(source):
    ait = source.__aiter__()
    while True:
        try:
            event = await asyncio.wait_for(ait.__anext__(), timeout=15)
            yield event
        except TimeoutError:
            yield ": keepalive\n\n"
