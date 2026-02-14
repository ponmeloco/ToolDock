from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WorkerError(Exception):
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


def success_response(request_id: str, result: Any, latency_ms: int) -> dict[str, Any]:
    return {"id": request_id, "ok": True, "result": result, "latency_ms": latency_ms}


def error_response(request_id: str, code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": request_id,
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        payload["error"]["details"] = details
    return payload
