from __future__ import annotations

import secrets
import time
from dataclasses import dataclass


@dataclass(slots=True)
class SessionInfo:
    session_id: str
    protocol_version: str
    created_at: float
    last_seen_at: float
    initialized: bool = False


class SessionManager:
    def __init__(self, ttl_seconds: int, supported_versions: list[str]):
        self._ttl_seconds = ttl_seconds
        self._supported = supported_versions
        self._sessions: dict[str, SessionInfo] = {}

    def create(self, protocol_version: str) -> SessionInfo:
        now = time.time()
        sid = secrets.token_hex(16)
        info = SessionInfo(
            session_id=sid,
            protocol_version=protocol_version,
            created_at=now,
            last_seen_at=now,
            initialized=False,
        )
        self._sessions[sid] = info
        return info

    def get(self, session_id: str) -> SessionInfo | None:
        self.evict_expired()
        info = self._sessions.get(session_id)
        if info:
            info.last_seen_at = time.time()
        return info

    def validate(self, session_id: str, protocol_version: str | None) -> bool:
        info = self.get(session_id)
        if info is None:
            return False
        if protocol_version and info.protocol_version != protocol_version:
            return False
        return True

    def resolve_protocol(self, provided: str | None, session_id: str | None) -> str:
        if provided:
            return provided
        if session_id and (info := self.get(session_id)) is not None:
            return info.protocol_version
        return "2025-03-26"

    def terminate(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def mark_initialized(self, session_id: str) -> None:
        info = self._sessions.get(session_id)
        if info:
            info.initialized = True
            info.last_seen_at = time.time()

    def evict_expired(self) -> int:
        now = time.time()
        expired = [sid for sid, info in self._sessions.items() if now - info.last_seen_at > self._ttl_seconds]
        for sid in expired:
            self._sessions.pop(sid, None)
        return len(expired)

    @property
    def supported_versions(self) -> list[str]:
        return self._supported
