"""
MCP Server Proxy.

Manages connections to external MCP servers via STDIO transport.
"""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPServerProxy:
    """
    Proxy for a single external MCP server.

    Manages the subprocess lifecycle and provides tool discovery and execution.
    """

    def __init__(self, server_id: str, config: Dict[str, Any]):
        """
        Initialize the proxy.

        Args:
            server_id: Unique identifier for this server
            config: Server configuration dict with command, args, env, etc.
        """
        self.server_id = server_id
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if the proxy is connected."""
        return self._connected and self.session is not None

    async def connect(self) -> None:
        """
        Connect to the MCP server and discover tools.

        Raises:
            RuntimeError: If connection fails
        """
        if self._connected:
            logger.warning(f"Server {self.server_id} already connected")
            return

        server_type = self.config.get("type", "stdio")

        if server_type == "http":
            raise NotImplementedError(
                f"HTTP transport not yet implemented for server {self.server_id}"
            )

        # STDIO transport
        command = self.config.get("command")
        args = self.config.get("args", [])
        env = self._build_env()

        if not command:
            raise ValueError(f"No command specified for server {self.server_id}")

        logger.info(f"Connecting to server {self.server_id}: {command} {' '.join(args)}")

        try:
            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env,
            )

            self._exit_stack = AsyncExitStack()

            # Start the server process and get streams
            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport

            # Create and initialize session
            self.session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self.session.initialize()

            # Discover tools
            await self._discover_tools()

            self._connected = True
            logger.info(
                f"Connected to {self.server_id} with {len(self.tools)} tools"
            )

        except Exception as e:
            logger.error(f"Failed to connect to {self.server_id}: {e}")
            await self.disconnect()
            raise RuntimeError(f"Connection failed for {self.server_id}: {e}") from e

    async def _discover_tools(self) -> None:
        """Discover available tools from the server."""
        if not self.session:
            return

        try:
            response = await self.session.list_tools()

            self.tools = {}
            for tool in response.tools:
                self.tools[tool.name] = {
                    "name": tool.name,
                    "description": tool.description or "",
                    "inputSchema": tool.inputSchema if hasattr(tool, 'inputSchema') else {},
                }

            logger.debug(
                f"Discovered tools from {self.server_id}: {list(self.tools.keys())}"
            )

        except Exception as e:
            logger.error(f"Failed to discover tools from {self.server_id}: {e}")
            raise

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool on the external server.

        Args:
            name: Tool name (without server prefix)
            arguments: Tool arguments

        Returns:
            Tool execution result

        Raises:
            RuntimeError: If not connected or tool execution fails
        """
        if not self.is_connected or not self.session:
            raise RuntimeError(f"Server {self.server_id} not connected")

        if name not in self.tools:
            raise ValueError(f"Tool {name} not found on server {self.server_id}")

        logger.debug(f"Calling {self.server_id}:{name} with {arguments}")

        try:
            result = await self.session.call_tool(name, arguments)

            # Convert MCP result to dict format
            content = []
            for item in result.content:
                if hasattr(item, "text"):
                    content.append({"type": "text", "text": item.text})
                elif hasattr(item, "data"):
                    content.append({"type": "data", "data": item.data})
                else:
                    content.append({"type": "unknown", "value": str(item)})

            return {
                "content": content,
                "isError": getattr(result, "isError", False),
            }

        except Exception as e:
            logger.error(f"Tool call failed for {self.server_id}:{name}: {e}")
            return {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            }

    async def disconnect(self) -> None:
        """Disconnect from the server and cleanup resources."""
        logger.info(f"Disconnecting from server {self.server_id}")

        self._connected = False
        self.session = None
        self.tools = {}

        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(f"Error during disconnect of {self.server_id}: {e}")
            finally:
                self._exit_stack = None

    def _build_env(self) -> Dict[str, str]:
        """Build environment variables for the subprocess."""
        # Start with current environment
        env = dict(os.environ)

        # Add configured env vars
        config_env = self.config.get("env", {})
        for key, value in config_env.items():
            if isinstance(value, str):
                # Substitute ${VAR} references
                if value.startswith("${") and value.endswith("}"):
                    var_name = value[2:-1]
                    env[key] = os.environ.get(var_name, "")
                else:
                    env[key] = value

        return env

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for all tools with server prefix."""
        return [
            {
                "name": f"{self.server_id}:{tool['name']}",
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
                "server_id": self.server_id,
                "original_name": tool["name"],
            }
            for tool in self.tools.values()
        ]
