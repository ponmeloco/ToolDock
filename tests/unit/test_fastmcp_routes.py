"""Unit tests for FastMCP routes."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.database import get_db, init_db
from app.db.models import ExternalFastMCPServer
from app.web.routes import fastmcp as fastmcp_routes
from tests.utils.sync_client import SyncASGIClient


class _StubFastMCPManager:
    def __init__(self):
        self.calls = {}
        self.deleted = None

    async def list_registry_servers(self, limit=30, cursor=None, search=None):
        self.calls["list_registry_servers"] = {
            "limit": limit,
            "cursor": cursor,
            "search": search,
        }
        return {"servers": [{"name": "demo"}], "next_cursor": None}

    async def add_server_from_registry(self, server_name, namespace, version=None, server_id=None):
        self.calls["add_server_from_registry"] = {
            "server_name": server_name,
            "namespace": namespace,
            "version": version,
            "server_id": server_id,
        }
        return SimpleNamespace(
            id=1,
            server_name=server_name,
            namespace=namespace,
            version=version,
            install_method="package",
            repo_url=None,
            entrypoint="demo:main",
            port=9100,
            status="stopped",
            pid=None,
            last_error=None,
        )

    def start_server(self, server_id):
        self.calls["start_server"] = {"server_id": server_id}
        return SimpleNamespace(
            id=server_id,
            server_name="demo",
            namespace="demo_ns",
            version="1.0.0",
            install_method="package",
            repo_url=None,
            entrypoint="demo:main",
            port=9100,
            status="running",
            pid=1234,
            last_error=None,
        )

    def stop_server(self, server_id):
        self.calls["stop_server"] = {"server_id": server_id}
        return SimpleNamespace(
            id=server_id,
            server_name="demo",
            namespace="demo_ns",
            version="1.0.0",
            install_method="package",
            repo_url=None,
            entrypoint="demo:main",
            port=9100,
            status="stopped",
            pid=None,
            last_error=None,
        )

    def delete_server(self, server_id):
        self.deleted = server_id


class _FailingFastMCPManager:
    async def list_registry_servers(self, limit=30, cursor=None, search=None):
        raise RuntimeError("registry unavailable")

    async def add_server_from_registry(self, server_name, namespace, version=None, server_id=None):
        raise RuntimeError("install failed")

    def start_server(self, server_id):
        raise RuntimeError("start failed")

    def stop_server(self, server_id):
        raise RuntimeError("stop failed")

    def delete_server(self, server_id):
        raise RuntimeError("delete failed")


@pytest.fixture
def fastmcp_stub(monkeypatch: pytest.MonkeyPatch) -> _StubFastMCPManager:
    stub = _StubFastMCPManager()
    monkeypatch.setattr(fastmcp_routes, "_fastmcp_manager", stub)
    return stub


def test_list_fastmcp_registry_servers(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.get(
        "/api/fastmcp/registry/servers?limit=5&search=demo",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["servers"][0]["name"] == "demo"
    assert fastmcp_stub.calls["list_registry_servers"]["limit"] == 5
    assert fastmcp_stub.calls["list_registry_servers"]["search"] == "demo"


def test_list_fastmcp_servers_from_db(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"demo_ns_{uuid4().hex[:8]}"
    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="demo",
            namespace=unique_namespace,
            version="1.2.3",
            install_method="package",
            repo_url=None,
            entrypoint="demo:main",
            port=9100,
            status="stopped",
            pid=None,
            last_error=None,
        )
        db.add(record)
        db.commit()

    response = web_client.get("/api/fastmcp/servers", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert any(row["server_name"] == "demo" and row["namespace"] == unique_namespace for row in payload)

    # Cleanup the inserted record to avoid polluting a shared DB.
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_add_fastmcp_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post(
        "/api/fastmcp/servers",
        headers=auth_headers,
        json={"server_id": "server-1234", "server_name": "demo", "namespace": "demo_ns"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_name"] == "demo"
    assert payload["namespace"] == "demo_ns"
    assert fastmcp_stub.calls["add_server_from_registry"]["server_name"] == "demo"
    assert fastmcp_stub.calls["add_server_from_registry"]["server_id"] == "server-1234"


def test_start_fastmcp_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post("/api/fastmcp/servers/42/start", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert fastmcp_stub.calls["start_server"]["server_id"] == 42


def test_stop_fastmcp_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post("/api/fastmcp/servers/42/stop", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert fastmcp_stub.calls["stop_server"]["server_id"] == 42


def test_delete_fastmcp_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.delete("/api/fastmcp/servers/42", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert fastmcp_stub.deleted == 42


def test_fastmcp_requires_manager(
    web_client: SyncASGIClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(fastmcp_routes, "_fastmcp_manager", None)

    response = web_client.get("/api/fastmcp/registry/servers", headers=auth_headers)
    assert response.status_code == 500


def test_fastmcp_validation_error(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post(
        "/api/fastmcp/servers",
        headers=auth_headers,
        json={"server_name": "demo", "namespace": "INVALID!"},
    )

    assert response.status_code == 422

    response = web_client.post(
        "/api/fastmcp/servers",
        headers=auth_headers,
        json={"namespace": "demo_ns"},
    )

    assert response.status_code == 422


def test_fastmcp_error_paths(
    web_client: SyncASGIClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(fastmcp_routes, "_fastmcp_manager", _FailingFastMCPManager())

    response = web_client.get("/api/fastmcp/registry/servers", headers=auth_headers)
    assert response.status_code == 500

    response = web_client.post(
        "/api/fastmcp/servers",
        headers=auth_headers,
        json={"server_id": "server-1234", "server_name": "demo", "namespace": "demo_ns"},
    )
    assert response.status_code == 400

    response = web_client.post("/api/fastmcp/servers/1/start", headers=auth_headers)
    assert response.status_code == 400

    response = web_client.post("/api/fastmcp/servers/1/stop", headers=auth_headers)
    assert response.status_code == 400

    response = web_client.delete("/api/fastmcp/servers/1", headers=auth_headers)
    assert response.status_code == 400
