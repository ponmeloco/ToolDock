from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.workers.protocol import WorkerError


class WorkerRPCClient:
    def __init__(
        self,
        socket_path: Path | None = None,
        timeout_seconds: int = 60,
        host: str | None = None,
        port: int | None = None,
    ):
        self._socket_path = socket_path
        self._timeout = timeout_seconds
        self._host = host
        self._port = port

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        reader: asyncio.StreamReader
        writer: asyncio.StreamWriter
        reader, writer = await self._connect()

        try:
            wire = json.dumps(payload, separators=(",", ":")) + "\n"
            writer.write(wire.encode("utf-8"))
            await writer.drain()

            raw = await asyncio.wait_for(reader.readline(), timeout=self._timeout)
            if not raw:
                raise WorkerError("worker_protocol", "Worker closed connection without response")
            response = json.loads(raw.decode("utf-8"))
            if not isinstance(response, dict):
                raise WorkerError("worker_protocol", "Worker response must be an object")
            return response
        except TimeoutError as exc:
            raise WorkerError("execution_timeout", "Timed out waiting for worker response") from exc
        except json.JSONDecodeError as exc:
            raise WorkerError("worker_protocol", f"Invalid JSON from worker: {exc}") from exc
        finally:
            writer.close()
            await writer.wait_closed()

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        # Prefer Unix sockets when available; fallback to TCP for restricted runtimes.
        errors: list[Exception] = []

        if self._socket_path is not None and self._socket_path.exists():
            try:
                return await asyncio.wait_for(
                    asyncio.open_unix_connection(path=str(self._socket_path)),
                    timeout=self._timeout,
                )
            except (TimeoutError, OSError) as exc:
                errors.append(exc)

        if self._host and self._port:
            try:
                return await asyncio.wait_for(
                    asyncio.open_connection(host=self._host, port=self._port),
                    timeout=self._timeout,
                )
            except (TimeoutError, OSError) as exc:
                errors.append(exc)

        if errors and isinstance(errors[-1], TimeoutError):
            raise WorkerError("worker_timeout", "Timed out connecting to worker") from errors[-1]

        if errors:
            raise WorkerError("worker_unavailable", f"Cannot connect to worker: {errors[-1]}") from errors[-1]

        raise WorkerError("worker_unavailable", f"Socket does not exist: {self._socket_path}")
