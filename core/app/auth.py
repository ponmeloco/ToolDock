from __future__ import annotations

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import CoreSettings


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: CoreSettings):
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return _unauthorized()

        token = auth_header.removeprefix("Bearer ").strip()
        if token != self._settings.bearer_token:
            return _unauthorized()

        return await call_next(request)


def require_bearer(request: Request, settings: CoreSettings) -> None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header.removeprefix("Bearer ").strip()
    if token != settings.bearer_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _unauthorized():
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Unauthorized"},
        headers={"WWW-Authenticate": "Bearer"},
    )
