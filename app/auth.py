from __future__ import annotations

import os
from typing import Optional, Set

from fastapi import Header, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


def get_bearer_token() -> Optional[str]:
    token = os.getenv("BEARER_TOKEN", "").strip()
    return token or None


def is_auth_enabled() -> bool:
    return get_bearer_token() is not None


async def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """
    FastAPI dependency to verify bearer token.

    Returns the token if valid, raises HTTPException if invalid.
    """
    if not is_auth_enabled():
        return ""

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    provided = authorization.split(" ", 1)[1].strip()
    expected = get_bearer_token()

    if not expected or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid token")

    return provided


def _extract_bearer(header_value: str) -> Optional[str]:
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, public_paths: Optional[Set[str]] = None):
        super().__init__(app)
        self.public_paths = public_paths or set()

    async def dispatch(self, request: Request, call_next):
        if not is_auth_enabled():
            return await call_next(request)

        if request.url.path in self.public_paths:
            return await call_next(request)

        token = get_bearer_token()
        auth_header = request.headers.get("authorization", "")
        provided = _extract_bearer(auth_header)

        if not provided or not token or provided != token:
            return Response("Unauthorized", status_code=401)

        return await call_next(request)
