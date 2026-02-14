from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.auth import BearerAuthMiddleware
from app.config import CoreSettings
from app.engine import NamespaceNotFound, ToolEngine
from app.mcp.handler import McpHttpHandler
from app.mcp.legacy import LegacyMcpAdapter
from app.mcp.methods import McpMethods
from app.mcp.session import SessionManager
from app.mcp.stream import StreamManager
from app.openapi.routes import create_router
from app.security import require_internal_reload
from app.secrets import SecretsStore
from app.workers.supervisor import WorkerSupervisor


class AppState:
    def __init__(self, settings: CoreSettings):
        self.settings = settings
        self.secrets = SecretsStore(settings)
        self.supervisor = WorkerSupervisor(settings)
        self.engine = ToolEngine(Path(settings.data_dir), self.secrets, self.supervisor)

        self.sessions = SessionManager(
            ttl_seconds=settings.mcp_session_ttl_hours * 3600,
            supported_versions=settings.supported_protocol_versions,
        )
        self.streams = StreamManager()
        self.mcp_methods = McpMethods(self.engine, self.sessions, self.streams, server_name="tooldock-core")
        self.mcp_handler = McpHttpHandler(settings, self.mcp_methods, self.sessions, self.streams)
        self.legacy_handler = LegacyMcpAdapter(settings, self.mcp_methods, self.sessions, self.streams)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: AppState = app.state.tooldock
    await state.engine.reload()
    try:
        yield
    finally:
        await state.supervisor.shutdown()


def create_app(settings: CoreSettings) -> FastAPI:
    app = FastAPI(title="ToolDock Core", lifespan=lifespan)
    app.state.tooldock = AppState(settings)

    app.add_middleware(BearerAuthMiddleware, settings=settings)

    cors_origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(create_router(app.state.tooldock.engine))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/namespaces")
    async def namespaces():
        return await app.state.tooldock.engine.list_namespaces()

    @app.post("/reload")
    async def reload_route(request: Request):
        require_internal_reload(request, settings)
        return await app.state.tooldock.engine.reload()

    @app.post("/mcp")
    async def mcp_post(request: Request, x_namespace: str = Header(alias="X-Namespace")):
        if not x_namespace:
            raise HTTPException(status_code=400, detail="X-Namespace header is required")
        return await app.state.tooldock.mcp_handler.handle_mcp_post(request, x_namespace)

    @app.get("/mcp")
    async def mcp_get(request: Request, x_namespace: str = Header(alias="X-Namespace")):
        if not x_namespace:
            raise HTTPException(status_code=400, detail="X-Namespace header is required")
        return await app.state.tooldock.mcp_handler.handle_mcp_get(request, x_namespace)

    @app.delete("/mcp")
    async def mcp_delete(request: Request, x_namespace: str = Header(alias="X-Namespace")):
        if not x_namespace:
            raise HTTPException(status_code=400, detail="X-Namespace header is required")
        return await app.state.tooldock.mcp_handler.handle_mcp_delete(request, x_namespace)

    if settings.enable_legacy_mcp:

        @app.get("/sse")
        async def legacy_sse(request: Request, x_namespace: str = Header(alias="X-Namespace")):
            if not x_namespace:
                raise HTTPException(status_code=400, detail="X-Namespace header is required")
            return await app.state.tooldock.legacy_handler.handle_legacy_sse(request, x_namespace)

        @app.post("/messages")
        async def legacy_messages(request: Request, x_namespace: str = Header(alias="X-Namespace")):
            if not x_namespace:
                raise HTTPException(status_code=400, detail="X-Namespace header is required")
            return await app.state.tooldock.legacy_handler.handle_legacy_messages(request, x_namespace)

    return app
