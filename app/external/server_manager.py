"""
External Server Manager.

Manages the lifecycle of all external MCP server connections.

Each external server becomes its own namespace, accessible via /mcp/{server_id}.
Tools are registered WITHOUT prefix since namespaces provide isolation.

Security:
- Sensitive configuration data (tokens, passwords) is masked in API responses
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.external.proxy import MCPServerProxy

if TYPE_CHECKING:
    from app.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Patterns for sensitive keys that should be masked
SENSITIVE_PATTERNS = [
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*key.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r".*connection.*string.*", re.IGNORECASE),
]


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive data."""
    for pattern in SENSITIVE_PATTERNS:
        if pattern.match(key):
            return True
    return False


def _mask_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a safe version of config for API responses.

    Masks sensitive values like tokens and passwords.
    """
    safe_config = {}

    for key, value in config.items():
        if key == "env" and isinstance(value, dict):
            # Mask environment variables that look sensitive
            safe_config[key] = {
                k: "***MASKED***" if _is_sensitive_key(k) and v else v
                for k, v in value.items()
            }
        elif _is_sensitive_key(key):
            safe_config[key] = "***MASKED***" if value else None
        elif isinstance(value, dict):
            safe_config[key] = _mask_config(value)
        else:
            safe_config[key] = value

    return safe_config


class ExternalServerManager:
    """
    Manages all external MCP server connections.

    Provides methods to add, remove, and query external servers,
    and registers their tools with the central ToolRegistry.

    Each server becomes its own namespace:
    - server_id='github' -> namespace 'github' -> endpoint /mcp/github
    - Tools are registered WITHOUT prefix (since namespace provides isolation)
    """

    def __init__(self, registry: "ToolRegistry"):
        """
        Initialize the manager.

        Args:
            registry: The central ToolRegistry for tool registration
        """
        self.registry = registry
        self.servers: Dict[str, MCPServerProxy] = {}

    async def add_server(
        self,
        server_id: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Add and connect to an external server.

        The server becomes a namespace accessible via /mcp/{server_id}.
        Tools are registered under this namespace.

        Args:
            server_id: Unique identifier for the server (becomes namespace)
            config: Server configuration

        Returns:
            Dict with server info and tool count (sensitive data masked)

        Raises:
            ValueError: If server_id already exists
            RuntimeError: If connection fails
        """
        if server_id in self.servers:
            raise ValueError(f"Server {server_id} already exists")

        logger.info(f"Adding external server: {server_id}")

        proxy = MCPServerProxy(server_id, config)

        try:
            await proxy.connect()

            # Register all tools from this server under its namespace
            tool_count = self._register_tools(proxy)

            self.servers[server_id] = proxy

            logger.info(f"Server {server_id} added with {tool_count} tools (namespace: {server_id})")

            return {
                "server_id": server_id,
                "namespace": server_id,
                "status": "connected",
                "tools": tool_count,
                "tool_names": list(proxy.tools.keys()),
                "endpoint": f"/mcp/{server_id}",
            }

        except Exception as e:
            logger.error(f"Failed to add server {server_id}: {e}")
            await proxy.disconnect()
            raise

    async def remove_server(self, server_id: str) -> bool:
        """
        Remove and disconnect an external server.

        Args:
            server_id: Server identifier to remove

        Returns:
            True if removed, False if not found
        """
        if server_id not in self.servers:
            logger.warning(f"Server {server_id} not found")
            return False

        logger.info(f"Removing external server: {server_id}")

        proxy = self.servers[server_id]

        # Unregister all tools from this server
        self._unregister_tools(proxy)

        # Disconnect
        await proxy.disconnect()

        del self.servers[server_id]

        logger.info(f"Server {server_id} removed (namespace removed)")
        return True

    def _register_tools(self, proxy: MCPServerProxy) -> int:
        """
        Register all tools from a proxy with the registry.

        Tools are registered WITHOUT prefix - the namespace provides isolation.
        """
        count = 0

        for original_name, tool_info in proxy.tools.items():
            self.registry.register_external_tool(
                name=original_name,  # No prefix - namespace provides isolation
                description=tool_info.get("description", ""),
                schema=tool_info.get("inputSchema", {}),
                server_id=proxy.server_id,
                original_name=original_name,
                proxy=proxy,
                namespace=proxy.server_id,  # Server ID is the namespace
            )
            count += 1

        return count

    def _unregister_tools(self, proxy: MCPServerProxy) -> None:
        """Unregister all tools from a proxy."""
        for tool_name in proxy.tools.keys():
            # Tools are registered without prefix now
            self.registry.unregister_tool(tool_name)

    def list_servers(self) -> List[Dict[str, Any]]:
        """
        List all connected servers.

        Returns:
            List of server info dicts (sensitive data masked)
        """
        return [
            {
                "server_id": server_id,
                "namespace": server_id,
                "endpoint": f"/mcp/{server_id}",
                "status": "connected" if proxy.is_connected else "disconnected",
                "tools": len(proxy.tools),
                "tool_names": list(proxy.tools.keys()),
                "config": _mask_config({
                    "type": proxy.config.get("type", "stdio"),
                    "command": proxy.config.get("command"),
                }),
            }
            for server_id, proxy in self.servers.items()
        ]

    def get_server(self, server_id: str) -> Optional[MCPServerProxy]:
        """
        Get a server proxy by ID.

        Args:
            server_id: Server identifier

        Returns:
            MCPServerProxy or None if not found
        """
        return self.servers.get(server_id)

    def has_server(self, server_id: str) -> bool:
        """Check if a server exists."""
        return server_id in self.servers

    async def shutdown_all(self) -> None:
        """Disconnect and cleanup all servers."""
        logger.info(f"Shutting down {len(self.servers)} external servers")

        for server_id in list(self.servers.keys()):
            try:
                await self.remove_server(server_id)
            except Exception as e:
                logger.error(f"Error shutting down {server_id}: {e}")

        logger.info("All external servers shut down")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about external servers."""
        total_tools = sum(len(proxy.tools) for proxy in self.servers.values())
        connected = sum(1 for proxy in self.servers.values() if proxy.is_connected)

        return {
            "total_servers": len(self.servers),
            "connected_servers": connected,
            "total_tools": total_tools,
            "namespaces": list(self.servers.keys()),
        }
