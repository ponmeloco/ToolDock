from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.config import CoreSettings


def require_internal_reload(request: Request, settings: CoreSettings) -> None:
    manager_token = request.headers.get("x-manager-token", "")
    if manager_token != settings.manager_internal_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid manager token")
