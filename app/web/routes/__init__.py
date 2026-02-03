"""Web GUI API Routes."""

from app.web.routes.folders import router as folders_router
from app.web.routes.tools import router as tools_router
from app.web.routes.servers import router as servers_router
try:
    from app.web.routes.fastmcp import router as fastmcp_router
except Exception:  # pragma: no cover - optional dependency
    fastmcp_router = None
from app.web.routes.reload import router as reload_router
from app.web.routes.admin import router as admin_router
from app.web.routes.playground import router as playground_router

__all__ = [
    "folders_router",
    "tools_router",
    "servers_router",
    "fastmcp_router",
    "reload_router",
    "admin_router",
    "playground_router",
]
