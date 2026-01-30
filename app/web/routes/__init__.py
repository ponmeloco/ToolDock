"""Web GUI API Routes."""

from app.web.routes.folders import router as folders_router
from app.web.routes.tools import router as tools_router
from app.web.routes.servers import router as servers_router
from app.web.routes.reload import router as reload_router
from app.web.routes.admin import router as admin_router

__all__ = ["folders_router", "tools_router", "servers_router", "reload_router", "admin_router"]
