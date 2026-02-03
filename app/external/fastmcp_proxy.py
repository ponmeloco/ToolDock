"""FastMCP Streamable HTTP proxy for external servers."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, Optional

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


class FastMCPHttpProxy:
    """Proxy for an external FastMCP server over Streamable HTTP."""

    def __init__(self, server_id: str, url: str, headers: Optional[Dict[str, str]] = None):
        self.server_id = server_id
        self.url = url.rstrip("/")
        self.headers = headers or {}
        self.session: Optional[ClientSession] = None
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._exit_stack: Optional[AsyncExitStack] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.session is not None

    async def connect(self) -> None:
        if self._connected:
            return

        logger.info(f"Connecting to FastMCP server {self.server_id} at {self.url}")

        try:
            self._exit_stack = AsyncExitStack()
            http_client = httpx.AsyncClient(headers=self.headers, timeout=httpx.Timeout(10.0, read=30.0))

            read_stream, write_stream, _ = await self._exit_stack.enter_async_context(
                streamable_http_client(self.url, http_client=http_client)
            )

            self.session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self.session.initialize()
            await self._discover_tools()
            self._connected = True
            logger.info(f"Connected to {self.server_id} with {len(self.tools)} tools")
        except Exception as exc:
            logger.error(f"Failed to connect to {self.server_id}: {exc}")
            await self.disconnect()
            raise RuntimeError(f"Connection failed for {self.server_id}: {exc}") from exc

    async def _discover_tools(self) -> None:
        if not self.session:
            return
        response = await self.session.list_tools()
        self.tools = {}
        for tool in response.tools:
            self.tools[tool.name] = {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            }

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected or not self.session:
            raise RuntimeError(f"Server {self.server_id} not connected")
        if name not in self.tools:
            raise ValueError(f"Tool {name} not found on server {self.server_id}")

        try:
            result = await self.session.call_tool(name, arguments)
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
        except Exception as exc:
            logger.error(f"Tool call failed for {self.server_id}:{name}: {exc}")
            return {
                "content": [{"type": "text", "text": f"Error: {exc}"}],
                "isError": True,
            }

    async def disconnect(self) -> None:
        self._connected = False
        self.session = None
        self.tools = {}

        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as exc:
                logger.warning(f"Error during disconnect of {self.server_id}: {exc}")
            finally:
                self._exit_stack = None

    def get_tool_schemas(self, namespace: str) -> list[Dict[str, Any]]:
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
