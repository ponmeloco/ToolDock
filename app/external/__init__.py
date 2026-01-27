"""
External MCP Server Integration Module.

Provides functionality to:
- Connect to external MCP servers from the registry
- Proxy tool calls to external servers
- Manage server lifecycle
"""

from app.external.registry_client import MCPRegistryClient
from app.external.server_manager import ExternalServerManager
from app.external.proxy import MCPServerProxy
from app.external.config import ExternalServerConfig

__all__ = [
    "MCPRegistryClient",
    "ExternalServerManager",
    "MCPServerProxy",
    "ExternalServerConfig",
]
