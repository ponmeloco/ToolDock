"""
Synchronous wrapper around httpx.AsyncClient for ASGI apps.

FastAPI's TestClient can hang in this environment; this wrapper runs requests
via anyio and returns normal httpx.Response objects.
"""

from __future__ import annotations

from typing import Any

import anyio
import httpx


async def _run_request(
    transport: httpx.ASGITransport,
    base_url: str,
    method: str,
    url: str,
    kwargs: dict[str, Any],
    timeout_s: float,
) -> httpx.Response:
    async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
        with anyio.fail_after(timeout_s):
            return await client.request(method, url, **kwargs)


class SyncASGIClient:
    """Synchronous client interface backed by httpx.AsyncClient + ASGITransport."""

    def __init__(self, app, base_url: str = "http://test", timeout_s: float = 10.0) -> None:
        self._transport = httpx.ASGITransport(app=app)
        self._base_url = base_url
        self._timeout_s = timeout_s

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return anyio.run(
            _run_request,
            self._transport,
            self._base_url,
            method,
            url,
            kwargs,
            self._timeout_s,
        )

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", url, **kwargs)

    def close(self) -> None:
        return None
