"""
Web GUI Module for ToolDock.

Provides a web interface for:
- Server management (add/remove external MCP servers)
- Tool management (upload/validate tools)
- Namespace/folder management
"""

from app.web.server import create_web_app

__all__ = ["create_web_app"]
