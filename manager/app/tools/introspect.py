from __future__ import annotations

import platform
import time
from typing import Any

from app.config import ManagerSettings
from app.core_client import CoreClient
from app.tools.namespaces import NamespaceTools


class IntrospectTools:
    def __init__(self, settings: ManagerSettings, started_at: float):
        self._settings = settings
        self._started_at = started_at
        self._core = CoreClient(settings)
        self._namespaces = NamespaceTools(settings)

    async def health(self) -> dict[str, Any]:
        uptime_seconds = int(time.time() - self._started_at)
        namespaces = self._namespaces.list_namespaces()

        core_reachable = False
        try:
            await self._core.health()
            core_reachable = True
        except Exception:  # noqa: BLE001
            core_reachable = False

        return {
            "manager_uptime": _format_uptime(uptime_seconds),
            "core_reachable": core_reachable,
            "python_version": platform.python_version(),
            "namespaces_loaded": len(namespaces),
            "total_tools": sum(item["tool_count"] for item in namespaces),
        }

    def server_config(self) -> dict[str, Any]:
        return {
            "core_url": self._settings.core_url,
            "manager_port": self._settings.port,
            "data_dir": self._settings.data_dir,
            "log_level": self._settings.log_level,
            "mcp_session_ttl_hours": self._settings.mcp_session_ttl_hours,
            "enable_legacy_mcp": self._settings.enable_legacy_mcp,
            "enable_fs_watcher": self._settings.enable_fs_watcher,
        }


def _format_uptime(seconds: int) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    return f"{hours}h {minutes}m"
