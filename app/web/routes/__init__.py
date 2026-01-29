"""Web GUI API Routes."""

from app.web.routes.folders import router as folders_router
from app.web.routes.tools import router as tools_router
from app.web.routes.servers import router as servers_router

__all__ = ["folders_router", "tools_router", "servers_router"]
