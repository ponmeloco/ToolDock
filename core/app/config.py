from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    bearer_token: str
    manager_internal_token: str
    data_dir: str = "/data"
    log_level: str = "info"
    cors_origins: str = "*"
    mcp_session_ttl_hours: int = 24
    mcp_supported_versions: str = "2025-11-25,2025-06-18,2025-03-26"
    enable_legacy_mcp: bool = True
    secrets_key: str | None = None
    allow_insecure_secrets: bool = False
    tool_call_timeout_seconds: int = 60
    namespace_max_concurrency: int = 20
    port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def supported_protocol_versions(self) -> list[str]:
        return [v.strip() for v in self.mcp_supported_versions.split(",") if v.strip()]


@lru_cache(maxsize=1)
def get_settings() -> CoreSettings:
    return CoreSettings()
