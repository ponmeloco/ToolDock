"""HTTP wrapper for stdio-based MCP servers.

This module runs an MCP server as a subprocess (using stdio transport) and
exposes it via Streamable HTTP using the MCP SDK's transport layer.

Usage:
    python http_wrapper.py /path/to/server.py

Environment variables:
    FASTMCP_HOST: Host to bind to (default: 127.0.0.1)
    FASTMCP_PORT: Port to listen on (default: 8000)
    FASTMCP_STREAMABLE_HTTP_PATH: URL path for MCP endpoint (default: /mcp)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse, JSONResponse

logger = logging.getLogger(__name__)


class StdioToHttpBridge:
    """Bridge an MCP server subprocess (stdio) to HTTP clients.

    This creates an HTTP server that implements the Streamable HTTP protocol
    and forwards requests to a subprocess communicating via JSON-RPC over stdio.
    """

    def __init__(
        self,
        entrypoint: str,
        host: str = "127.0.0.1",
        port: int = 8000,
        path: str = "/mcp",
        python_path: Optional[str] = None,
    ):
        self.entrypoint = entrypoint
        self.host = host
        self.port = port
        self.path = path
        self.python_path = python_path or sys.executable
        self.process: Optional[asyncio.subprocess.Process] = None
        self._message_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._session_id: Optional[str] = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def start(self) -> None:
        """Start the subprocess and HTTP server."""
        import uvicorn

        # Start the subprocess
        await self._start_subprocess()

        # Initialize the MCP session
        await self._initialize_session()

        # Create the HTTP server
        async def handle_mcp(request: Request) -> Response:
            """Handle MCP requests (POST for JSON-RPC, GET for SSE)."""
            if request.method == "POST":
                return await self._handle_post(request)
            elif request.method == "GET":
                return await self._handle_get(request)
            return Response(status_code=405)

        async def handle_health(request: Request) -> Response:
            return JSONResponse({"status": "ok"})

        app = Starlette(
            routes=[
                Route(self.path, handle_mcp, methods=["GET", "POST", "DELETE"]),
                Route(f"{self.path}/sse", handle_mcp, methods=["GET"]),
                Route("/health", handle_health, methods=["GET"]),
            ],
        )

        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)

        try:
            await server.serve()
        finally:
            await self._stop_subprocess()

    async def _start_subprocess(self) -> None:
        """Start the MCP server subprocess."""
        cmd = self._build_command()
        logger.info(f"Starting subprocess: {' '.join(cmd)}")

        env = os.environ.copy()
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

        self._read_task = asyncio.create_task(self._read_responses())
        asyncio.create_task(self._log_stderr())

    async def _initialize_session(self) -> None:
        """Initialize the MCP session with the subprocess."""
        self._session_id = str(uuid.uuid4())

        result = await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "tooldock-http-bridge", "version": "1.0.0"},
        })
        logger.info(f"Initialized session: {result}")

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})
        self._initialized = True

    async def _handle_post(self, request: Request) -> Response:
        """Handle POST requests (JSON-RPC calls)."""
        try:
            body = await request.json()
        except Exception:
            return Response(
                content='{"jsonrpc":"2.0","error":{"code":-32700,"message":"Parse error"},"id":null}',
                media_type="application/json",
                status_code=400,
            )

        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id")

        # Handle notifications (no id)
        if req_id is None:
            await self._send_notification(method, params)
            return Response(status_code=202)

        try:
            result = await self._send_request(method, params)
            response_data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except Exception as e:
            logger.error(f"Request failed: {e}")
            response_data = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

        # Check Accept header for response format
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            # Return as SSE
            async def sse_response():
                event_id = str(uuid.uuid4())
                yield f"id: {event_id}\n"
                yield f"data: {json.dumps(response_data)}\n\n"

            return StreamingResponse(
                sse_response(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Mcp-Session-Id": self._session_id or "",
                },
            )
        else:
            return Response(
                content=json.dumps(response_data),
                media_type="application/json",
                headers={"Mcp-Session-Id": self._session_id or ""},
            )

    async def _handle_get(self, request: Request) -> Response:
        """Handle GET requests (SSE stream)."""
        async def event_stream():
            # Send priming event
            yield f"event: open\ndata: {{}}\n\n"

            # Keep connection alive with periodic heartbeats
            while True:
                await asyncio.sleep(15)
                yield ": heartbeat\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Mcp-Session-Id": self._session_id or "",
            },
        )

    async def _send_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send a JSON-RPC request to the subprocess and wait for response."""
        async with self._lock:
            self._message_id += 1
            msg_id = self._message_id

        request = {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[msg_id] = future

        await self._write_message(request)

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_requests.pop(msg_id, None)
            raise TimeoutError(f"Request {method} timed out")

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification to the subprocess."""
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._write_message(notification)

    async def _write_message(self, message: Dict[str, Any]) -> None:
        """Write a JSON-RPC message to the subprocess stdin."""
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

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        response = json.loads(line.decode())
                        msg_id = response.get("id")
                        if msg_id is not None and msg_id in self._pending_requests:
                            future = self._pending_requests.pop(msg_id)
                            if "error" in response:
                                future.set_exception(
                                    RuntimeError(response["error"].get("message", "Unknown error"))
                                )
                            else:
                                future.set_result(response.get("result"))
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON: {line}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading: {e}")
                break

    async def _log_stderr(self) -> None:
        """Log stderr from subprocess."""
        if not self.process or not self.process.stderr:
            return
        while True:
            try:
                line = await self.process.stderr.readline()
                if not line:
                    break
                logger.info(f"[subprocess] {line.decode().rstrip()}")
            except:
                break

    def _build_command(self) -> list[str]:
        """Build command to run the MCP server."""
        path = Path(self.entrypoint).resolve()
        if path.name == "__init__.py":
            return [self.python_path, "-m", path.parent.name]
        return [self.python_path, str(path)]

    async def _stop_subprocess(self) -> None:
        """Stop the subprocess."""
        if self._read_task:
            self._read_task.cancel()
        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except:
                self.process.kill()


def main() -> None:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Run MCP server with HTTP transport")
    parser.add_argument("module", help="Path to MCP server module")
    parser.add_argument("--host", default=os.getenv("FASTMCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FASTMCP_PORT", "8000")))
    parser.add_argument("--path", default=os.getenv("FASTMCP_STREAMABLE_HTTP_PATH", "/mcp"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    bridge = StdioToHttpBridge(args.module, args.host, args.port, args.path)
    try:
        asyncio.run(bridge.start())
    except KeyboardInterrupt:
        logger.info("Server stopped")
    except Exception as e:
        logger.error(f"Server failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
