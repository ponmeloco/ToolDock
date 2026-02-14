from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ManagerSettings(BaseSettings):
    bearer_token: str
    core_url: str = "http://172.30.0.11:8000"
    manager_internal_token: str
    data_dir: str = "/data"
    log_level: str = "info"
    enable_legacy_mcp: bool = True
    enable_fs_watcher: bool = False
    fs_watcher_debounce_ms: int = 1500
    mcp_session_ttl_hours: int = 24
    mcp_supported_versions: str = "2025-11-25,2025-06-18,2025-03-26"
    secrets_key: str | None = None
    allow_insecure_secrets: bool = False
    port: int = 8001

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def supported_protocol_versions(self) -> list[str]:
        return [v.strip() for v in self.mcp_supported_versions.split(",") if v.strip()]


@lru_cache(maxsize=1)
def get_settings() -> ManagerSettings:
    return ManagerSettings()
