"""Stdio proxy for MCP servers.

This module provides a proxy that communicates with MCP servers via stdio
and exposes them via the ToolDock registry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StdioMCPProxy:
    """Proxy for an MCP server running as a subprocess via stdio."""

    def __init__(
        self,
        server_id: str,
        entrypoint: str,
        python_path: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        self.server_id = server_id
        self.entrypoint = entrypoint
        self.python_path = python_path or sys.executable
        self.env = env or {}
        self.process: Optional[asyncio.subprocess.Process] = None
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._message_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Start the subprocess and initialize the MCP session."""
        if self.process is not None:
            return

        cmd = self._build_command()
        logger.info(f"Starting MCP server {self.server_id}: {' '.join(cmd)}")

        # Set up environment
        env = os.environ.copy()
        env.update(self.env)

        # Add entrypoint directory to PYTHONPATH
        entrypoint_dir = str(Path(self.entrypoint).parent)
        existing_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{entrypoint_dir}:{existing_path}" if existing_path else entrypoint_dir

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=entrypoint_dir,
            env=env,
        )

        # Start reading responses
        self._read_task = asyncio.create_task(self._read_responses())

        # Start logging stderr
        asyncio.create_task(self._log_stderr())

        # Initialize the session
        await self._initialize()

        # Discover tools
        await self._discover_tools()

        logger.info(f"Connected to {self.server_id} with {len(self.tools)} tools")

    async def _initialize(self) -> None:
        """Send initialize request to the server."""
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
        self._initialized = True

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

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the server."""
        if not self._initialized:
            raise RuntimeError(f"Server {self.server_id} not initialized")
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

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send a JSON-RPC request and wait for response."""
        async with self._lock:
            self._message_id += 1
            msg_id = self._message_id

        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }

        # Create future for response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[msg_id] = future

        # Send request
        await self._write_message(request)

        # Wait for response
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            raise TimeoutError(f"Request {method} timed out")

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._write_message(notification)

    async def _write_message(self, message: Dict[str, Any]) -> None:
        """Write a JSON-RPC message to the subprocess."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Process not started")

        line = json.dumps(message) + "\n"
        self.process.stdin.write(line.encode())
        await self.process.stdin.drain()

    async def _read_responses(self) -> None:
        """Read JSON-RPC responses from subprocess stdout."""
        if not self.process or not self.process.stdout:
            return

        buffer = b""
        while True:
            try:
                chunk = await self.process.stdout.read(4096)
                if not chunk:
                    break

                buffer += chunk

                # Process complete lines
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        response = json.loads(line.decode())
                        await self._handle_response(response)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from subprocess: {line}")
                    except Exception as e:
                        logger.error(f"Error processing response: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading from subprocess: {e}")
                break

    async def _handle_response(self, response: Dict[str, Any]) -> None:
        """Handle a JSON-RPC response."""
        msg_id = response.get("id")

        if msg_id is not None and msg_id in self._pending_requests:
            future = self._pending_requests.pop(msg_id)
            if "error" in response:
                error = response["error"]
                future.set_exception(RuntimeError(error.get("message", "Unknown error")))
            else:
                future.set_result(response.get("result"))
        elif "method" in response:
            # This is a notification from the server
            logger.debug(f"Received notification: {response.get('method')}")

    async def _log_stderr(self) -> None:
        """Log stderr from subprocess."""
        if not self.process or not self.process.stderr:
            return

        while True:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                logger.info(f"[{self.server_id}] {line.decode().rstrip()}")
            except asyncio.CancelledError:
                break
            except Exception:
                break

    def _build_command(self) -> list[str]:
        """Build the command to run the MCP server."""
        entrypoint_path = Path(self.entrypoint).resolve()

        # Check if it's a package __init__.py
        if entrypoint_path.name == "__init__.py":
            package_name = entrypoint_path.parent.name
            return [self.python_path, "-m", package_name]
        elif entrypoint_path.name == "__main__.py":
            package_name = entrypoint_path.parent.name
            return [self.python_path, "-m", package_name]
        else:
            return [self.python_path, str(entrypoint_path)]

    async def disconnect(self) -> None:
        """Stop the subprocess."""
        self._initialized = False
        self.tools = {}

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        # Cancel pending requests
        for future in self._pending_requests.values():
            future.cancel()
        self._pending_requests.clear()

        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
            except Exception:
                pass
            self.process = None

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

    @property
    def is_connected(self) -> bool:
        """Check if the proxy is connected."""
        return self._initialized and self.process is not None
