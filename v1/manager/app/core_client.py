from __future__ import annotations

from typing import Any

import httpx

from app.config import ManagerSettings


class CoreClient:
    def __init__(self, settings: ManagerSettings):
        self._settings = settings

    async def reload_core(self) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._settings.bearer_token}",
            "X-Manager-Token": self._settings.manager_internal_token,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{self._settings.core_url}/reload", headers=headers)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return {"reloaded": False, "detail": "Invalid core response"}
            return data

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self._settings.core_url}/health")
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data
            return {"status": "unknown"}
