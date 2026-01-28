"""
External Server Manager.

Manages the lifecycle of all external MCP server connections.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.external.proxy import MCPServerProxy

if TYPE_CHECKING:
    from app.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ExternalServerManager:
    """
    Manages all external MCP server connections.

    Provides methods to add, remove, and query external servers,
    and registers their tools with the central ToolRegistry.
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

        Args:
            server_id: Unique identifier for the server
            config: Server configuration

        Returns:
            Dict with server info and tool count

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

            # Register all tools from this server
            tool_count = self._register_tools(proxy)

            self.servers[server_id] = proxy

            logger.info(f"Server {server_id} added with {tool_count} tools")

            return {
                "server_id": server_id,
                "status": "connected",
                "tools": tool_count,
                "tool_names": [f"{server_id}:{name}" for name in proxy.tools.keys()],
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

        logger.info(f"Server {server_id} removed")
        return True

    def _register_tools(self, proxy: MCPServerProxy) -> int:
        """Register all tools from a proxy with the registry."""
        count = 0

        for tool_schema in proxy.get_tool_schemas():
            prefixed_name = tool_schema["name"]

            self.registry.register_external_tool(
                name=prefixed_name,
                description=tool_schema["description"],
                schema=tool_schema["inputSchema"],
                server_id=proxy.server_id,
                original_name=tool_schema["original_name"],
                proxy=proxy,
            )
            count += 1

        return count

    def _unregister_tools(self, proxy: MCPServerProxy) -> None:
        """Unregister all tools from a proxy."""
        for tool_name in proxy.tools.keys():
            prefixed_name = f"{proxy.server_id}:{tool_name}"
            self.registry.unregister_tool(prefixed_name)

    def list_servers(self) -> List[Dict[str, Any]]:
        """
        List all connected servers.

        Returns:
            List of server info dicts
        """
        return [
            {
                "server_id": server_id,
                "status": "connected" if proxy.is_connected else "disconnected",
                "tools": len(proxy.tools),
                "tool_names": list(proxy.tools.keys()),
                "config": {
                    "type": proxy.config.get("type", "stdio"),
                    "command": proxy.config.get("command"),
                },
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
        }
