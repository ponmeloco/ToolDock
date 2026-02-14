from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.auth import BearerAuthMiddleware
from app.config import ManagerSettings
from app.mcp.handler import ManagerMcpHandler
from app.mcp.legacy import ManagerLegacyMcpAdapter
from app.mcp.methods import ManagerMcpMethods
from app.mcp.session import SessionManager
from app.mcp.stream import StreamManager
from app.tools.service import ManagerToolService
from app.watcher import FileSystemWatcher


class ManagerState:
    def __init__(self, settings: ManagerSettings):
        self.settings = settings
        self.started_at = time.time()
        self.service = ManagerToolService(settings, started_at=self.started_at)
        self.sessions = SessionManager(
            ttl_seconds=settings.mcp_session_ttl_hours * 3600,
            supported_versions=settings.supported_protocol_versions,
        )
        self.streams = StreamManager()
        self.methods = ManagerMcpMethods(self.service, self.sessions, self.streams)
        self.handler = ManagerMcpHandler(settings, self.methods, self.sessions, self.streams)
        self.legacy = ManagerLegacyMcpAdapter(self.methods, self.sessions, self.streams)
        self.watcher = FileSystemWatcher(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: ManagerState = app.state.tooldock
    state.watcher.start()
    try:
        yield
    finally:
        await state.watcher.stop()


def create_app(settings: ManagerSettings) -> FastAPI:
    app = FastAPI(title="ToolDock Manager", lifespan=lifespan)
    app.state.tooldock = ManagerState(settings)

    app.add_middleware(BearerAuthMiddleware, settings=settings)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/mcp")
    async def mcp_post(request: Request):
        return await app.state.tooldock.handler.handle_post(request)

    @app.get("/mcp")
    async def mcp_get(request: Request):
        return await app.state.tooldock.handler.handle_get(request)

    @app.delete("/mcp")
    async def mcp_delete(request: Request):
        return await app.state.tooldock.handler.handle_delete(request)

    if settings.enable_legacy_mcp:

        @app.get("/sse")
        async def legacy_sse(request: Request):
            return await app.state.tooldock.legacy.handle_sse(request)

        @app.post("/messages")
        async def legacy_messages(request: Request):
            return await app.state.tooldock.legacy.handle_messages(request)

    return app
