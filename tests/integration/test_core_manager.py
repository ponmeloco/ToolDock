from __future__ import annotations

import types

import asyncio

from tests.helpers import import_manager


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_core_client_reload_headers(monkeypatch):
    config = import_manager("app.config")
    monkeypatch.setenv("BEARER_TOKEN", "token-a")
    monkeypatch.setenv("MANAGER_INTERNAL_TOKEN", "token-b")
    settings = config.ManagerSettings()

    captured = {}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _Resp({"reloaded": True})

    core_client_mod = import_manager("app.core_client")
    monkeypatch.setattr(core_client_mod.httpx, "AsyncClient", DummyClient)

    client = core_client_mod.CoreClient(settings)
    result = asyncio.run(client.reload_core())

    assert result["reloaded"] is True
    assert captured["headers"]["Authorization"] == "Bearer token-a"
    assert captured["headers"]["X-Manager-Token"] == "token-b"
