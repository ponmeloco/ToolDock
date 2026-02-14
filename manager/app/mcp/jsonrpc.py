from __future__ import annotations

import json
from typing import Any

JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def parse_request(body: bytes, protocol_version: str) -> dict[str, Any] | list[dict[str, Any]] | dict[str, Any]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return error_response(None, PARSE_ERROR, f"Invalid JSON: {exc}")

    if protocol_version in {"2025-06-18", "2025-11-25"}:
        if not isinstance(parsed, dict):
            return error_response(None, INVALID_REQUEST, "Request must be a JSON object")
        err = _validate_single(parsed)
        return err if err else parsed

    # compatibility mode (2025-03-26)
    if isinstance(parsed, list):
        if not parsed:
            return error_response(None, INVALID_REQUEST, "Batch request cannot be empty")
        out: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                out.append(error_response(None, INVALID_REQUEST, "Batch item must be object"))
                continue
            err = _validate_single(item)
            out.append(err if err else item)
        return out

    if isinstance(parsed, dict):
        err = _validate_single(parsed)
        return err if err else parsed

    return error_response(None, INVALID_REQUEST, "Invalid request payload")


def _validate_single(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        return error_response(payload.get("id"), INVALID_REQUEST, "jsonrpc must be '2.0'")
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        return error_response(payload.get("id"), INVALID_REQUEST, "method is required")
    params = payload.get("params")
    if params is not None and not isinstance(params, dict):
        return error_response(payload.get("id"), INVALID_PARAMS, "params must be an object")
    return None


def success_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if data is not None:
        payload["error"]["data"] = data
    return payload


def is_notification(request: dict[str, Any]) -> bool:
    return "id" not in request or request.get("id") is None
