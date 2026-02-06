"""
External MCP Server Integration Module.

Provides functionality to:
- Connect to external MCP servers from the registry
- Proxy tool calls to external servers
- Manage server lifecycle
"""

from app.external.registry_client import MCPRegistryClient
from app.external.fastmcp_manager import FastMCPServerManager
from app.external.fastmcp_proxy import FastMCPHttpProxy

__all__ = [
    "MCPRegistryClient",
    "FastMCPServerManager",
    "FastMCPHttpProxy",
]
