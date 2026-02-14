from __future__ import annotations

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import ManagerSettings


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: ManagerSettings):
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


def _unauthorized():
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": "Unauthorized"},
        headers={"WWW-Authenticate": "Bearer"},
    )
