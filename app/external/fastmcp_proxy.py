"""FastMCP HTTP proxy for external servers.

This proxy communicates with MCP servers over HTTP using JSON-RPC.
It supports both the full Streamable HTTP protocol (via MCP SDK) and
a simpler JSON-RPC over HTTP mode for compatibility with various servers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class FastMCPHttpProxy:
    """Proxy for an external MCP server over HTTP.

    This proxy uses simple JSON-RPC over HTTP for communication,
    which is compatible with both the http_wrapper bridge and
    native FastMCP servers.
    """

    def __init__(self, server_id: str, url: str, headers: Optional[Dict[str, str]] = None):
        self.server_id = server_id
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._connected = False
        self._message_id = 0
        self._client: Optional[httpx.AsyncClient] = None
        self._client_loop_id: Optional[int] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Get an AsyncClient bound to the current event loop."""
        loop = asyncio.get_running_loop()
        loop_id = id(loop)

        client_closed = bool(self._client and getattr(self._client, "is_closed", False))
        if self._client is None or client_closed or self._client_loop_id != loop_id:
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    pass
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=httpx.Timeout(10.0, read=30.0),
            )
            self._client_loop_id = loop_id

        return self._client

    async def connect(self) -> None:
        """Connect to the server and discover tools."""
        if self._connected:
            return

        logger.info(f"Connecting to MCP server {self.server_id} at {self.url}")

        try:
            await self._ensure_client()

            # Initialize the session
            await self._initialize()

            # Discover tools
            await self._discover_tools()

            self._connected = True
            logger.info(f"Connected to {self.server_id} with {len(self.tools)} tools")
        except Exception as exc:
            logger.error(f"Failed to connect to {self.server_id}: {exc}")
            await self.disconnect()
            raise RuntimeError(f"Connection failed for {self.server_id}: {exc}") from exc

    async def _initialize(self) -> None:
        """Initialize the MCP session."""
        result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "tooldock-proxy",
                "version": "1.0.0",
            },
        })
        logger.debug(f"Initialize result: {result}")

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

    async def _discover_tools(self) -> None:
        """Discover available tools from the server."""
        result = await self._send_request("tools/list", {})
        self.tools = {}
        for tool in result.get("tools", []):
            self.tools[tool["name"]] = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
            }

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send a JSON-RPC request and wait for response."""
        client = await self._ensure_client()

        self._message_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._message_id,
            "method": method,
            "params": params,
        }

        response = await client.post(
            self.url,
            json=request,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()

        data = response.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Unknown error"))
        return data.get("result")

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        client = await self._ensure_client()

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        # Notifications may return 202 (no content) or an empty response
        await client.post(
            self.url,
            json=notification,
            headers={"Accept": "application/json"},
        )

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the server."""
        if not self.is_connected or not self._client:
            raise RuntimeError(f"Server {self.server_id} not connected")
        if name not in self.tools:
            raise ValueError(f"Tool {name} not found on server {self.server_id}")

        try:
            result = await self._send_request("tools/call", {
                "name": name,
                "arguments": arguments,
            })
            return {
                "content": result.get("content", []),
                "isError": result.get("isError", False),
            }
        except Exception as exc:
            logger.error(f"Tool call failed for {self.server_id}:{name}: {exc}")
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False
        self.tools = {}

        if self._client:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.warning(f"Error during disconnect of {self.server_id}: {exc}")
            finally:
                self._client = None
                self._client_loop_id = None

    def get_tool_schemas(self, namespace: str) -> list[Dict[str, Any]]:
        """Get tool schemas with namespace prefix."""
        return [
            {
                "name": f"{namespace}:{tool['name']}",
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
                "server_id": self.server_id,
                "original_name": tool["name"],
            }
            for tool in self.tools.values()
        ]
