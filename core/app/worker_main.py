from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.registry.loader import load_tools_from_file
from app.registry.models import ToolEntry
from app.workers.protocol import error_response, success_response


@dataclass(slots=True)
class RuntimeTool:
    entry: ToolEntry
    fn: Any


class WorkerRuntime:
    def __init__(self, namespace: str, tools_dir: Path):
        self.namespace = namespace
        self.tools_dir = tools_dir
        self.tools: dict[str, RuntimeTool] = {}

    async def load(self) -> None:
        loaded_modules: dict[str, Any] = {}

        for py_file in sorted(self.tools_dir.glob("*.py"), key=lambda p: p.name):
            entries = load_tools_from_file(self.namespace, py_file)
            if not entries:
                continue

            module = loaded_modules.get(py_file.name)
            if module is None:
                module = _import_module(py_file)
                loaded_modules[py_file.name] = module

            for entry in entries:
                fn = getattr(module, entry.function_name, None)
                if fn is None or not callable(fn):
                    continue
                self.tools[entry.name] = RuntimeTool(entry=entry, fn=fn)

    async def handle(self, req: dict[str, Any]) -> dict[str, Any]:
        req_id = str(req.get("id") or "")
        op = req.get("op")
        start = time.monotonic()

        try:
            if op == "ping":
                return success_response(req_id, {"pong": True}, _latency_ms(start))
            if op == "shutdown":
                return success_response(req_id, {"shutdown": True}, _latency_ms(start))
            if op == "tools.list":
                result = [tool.entry.to_mcp_tool() for tool in self.tools.values()]
                return success_response(req_id, result, _latency_ms(start))
            if op == "tools.get_schema":
                tool_name = str(req.get("tool") or "")
                tool = self.tools.get(tool_name)
                if tool is None:
                    return error_response(req_id, "tool_not_found", f"Unknown tool: {tool_name}")
                return success_response(req_id, tool.entry.to_mcp_tool(), _latency_ms(start))
            if op == "tools.call":
                tool_name = str(req.get("tool") or "")
                args = req.get("arguments") or {}
                if not isinstance(args, dict):
                    return error_response(req_id, "invalid_arguments", "arguments must be an object")
                tool = self.tools.get(tool_name)
                if tool is None:
                    return error_response(req_id, "tool_not_found", f"Unknown tool: {tool_name}")
                result = await _invoke(tool.fn, args)
                return success_response(req_id, result, _latency_ms(start))
            return error_response(req_id, "invalid_request", f"Unsupported op: {op}")
        except TypeError as exc:
            return error_response(req_id, "invalid_arguments", str(exc))
        except TimeoutError:
            return error_response(req_id, "execution_timeout", "Tool execution timed out")
        except Exception as exc:  # noqa: BLE001
            return error_response(req_id, "internal_error", str(exc))


async def serve(namespace: str, socket_path: Path, tools_dir: Path) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)

    runtime = WorkerRuntime(namespace, tools_dir)
    await runtime.load()

    stop_event = asyncio.Event()

    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readline()
            if not raw:
                return
            req = json.loads(raw.decode("utf-8"))
            if not isinstance(req, dict):
                payload = error_response("", "invalid_request", "Request must be an object")
            else:
                payload = await runtime.handle(req)
            wire = json.dumps(payload, separators=(",", ":")) + "\n"
            writer.write(wire.encode("utf-8"))
            await writer.drain()

            if req.get("op") == "shutdown" and payload.get("ok"):
                stop_event.set()
        except json.JSONDecodeError:
            payload = error_response("", "invalid_json", "Invalid JSON")
            writer.write((json.dumps(payload) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = None
    try:
        server = await asyncio.start_unix_server(on_client, path=str(socket_path))
    except (PermissionError, OSError):
        # Some restricted environments disallow Unix domain sockets; fallback to loopback TCP.
        host = os.environ.get("TOOLDOCK_WORKER_HOST", "127.0.0.1")
        port = int(os.environ.get("TOOLDOCK_WORKER_PORT", "0"))
        server = await asyncio.start_server(on_client, host=host, port=port)

    try:
        await stop_event.wait()
    finally:
        server.close()
        await server.wait_closed()
        socket_path.unlink(missing_ok=True)


def _import_module(file_path: Path):
    module_name = f"tooldock_worker_{file_path.stem}_{abs(hash(file_path))}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _invoke(fn, arguments: dict[str, Any]) -> Any:
    value = fn(**arguments)
    if inspect.isawaitable(value):
        return await value
    return value


def _latency_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--tools-dir", required=True)
    args = parser.parse_args()

    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    os.environ["TOOLDOCK_WORKER_HOST"] = args.host
    os.environ["TOOLDOCK_WORKER_PORT"] = str(args.port)

    asyncio.run(serve(args.namespace, Path(args.socket), Path(args.tools_dir)))


if __name__ == "__main__":
    main()
