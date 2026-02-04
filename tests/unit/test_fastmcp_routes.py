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


# ==================== Registry Endpoints ====================


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


def test_registry_health(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.get("/api/fastmcp/registry/health", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_registry_health_offline(
    web_client: SyncASGIClient,
    auth_headers: dict,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(fastmcp_routes, "_fastmcp_manager", _FailingFastMCPManager())

    response = web_client.get("/api/fastmcp/registry/health", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "offline"


# ==================== Server List/Get ====================


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

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_get_single_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"test_get_{uuid4().hex[:8]}"
    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="test-server",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            command_args=["-m", "myserver"],
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    response = web_client.get(f"/api/fastmcp/servers/{server_id}", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace"] == unique_namespace
    assert payload["command"] == "python"
    assert payload["args"] == ["-m", "myserver"]

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_get_server_not_found(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    response = web_client.get("/api/fastmcp/servers/99999", headers=auth_headers)
    assert response.status_code == 404


# ==================== Optional Auth ====================


def test_list_servers_without_auth(
    web_client: SyncASGIClient,
    fastmcp_stub: _StubFastMCPManager,
):
    """GET endpoints should work without auth header."""
    response = web_client.get("/api/fastmcp/servers")
    assert response.status_code == 200


def test_registry_servers_without_auth(
    web_client: SyncASGIClient,
    fastmcp_stub: _StubFastMCPManager,
):
    """Registry list should work without auth."""
    response = web_client.get("/api/fastmcp/registry/servers")
    assert response.status_code == 200


def test_post_requires_auth(
    web_client: SyncASGIClient,
    fastmcp_stub: _StubFastMCPManager,
):
    """POST endpoints should require auth."""
    response = web_client.post(
        "/api/fastmcp/servers",
        json={"server_id": "test", "server_name": "test", "namespace": "testns"},
    )
    assert response.status_code == 401


# ==================== Add Server from Registry ====================


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


# ==================== Manual Server ====================


def test_add_manual_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"manual_{uuid4().hex[:8]}"

    response = web_client.post(
        "/api/fastmcp/servers/manual",
        headers=auth_headers,
        json={
            "namespace": unique_namespace,
            "server_name": "My Manual Server",
            "command": "npx",
            "args": ["-y", "@mcp/server-test"],
            "env": {"API_KEY": "secret"},
            "auto_start": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace"] == unique_namespace
    assert payload["server_name"] == "My Manual Server"
    assert payload["command"] == "npx"
    assert payload["args"] == ["-y", "@mcp/server-test"]
    assert payload["env"] == {"API_KEY": "secret"}
    assert payload["install_method"] == "manual"
    assert payload["status"] == "stopped"

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_add_manual_server_with_config(
    web_client: SyncASGIClient,
    auth_headers: dict,
    data_dir,
):
    init_db()
    unique_namespace = f"config_{uuid4().hex[:8]}"

    response = web_client.post(
        "/api/fastmcp/servers/manual",
        headers=auth_headers,
        json={
            "namespace": unique_namespace,
            "server_name": "Config Server",
            "command": "python",
            "args": ["-m", "server"],
            "config_file": "debug: true\nport: 8000",
            "config_filename": "config.yaml",
        },
    )

    assert response.status_code == 200
    assert response.json()["config_path"] is not None

    # Check config file was created
    config_path = data_dir / "external" / "servers" / unique_namespace / "config.yaml"
    assert config_path.exists()
    assert "debug: true" in config_path.read_text()

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_add_manual_server_duplicate_namespace(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"dup_{uuid4().hex[:8]}"

    # Create first server
    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="existing",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            status="stopped",
        )
        db.add(record)
        db.commit()

    # Try to create another with same namespace
    response = web_client.post(
        "/api/fastmcp/servers/manual",
        headers=auth_headers,
        json={
            "namespace": unique_namespace,
            "server_name": "Duplicate",
            "command": "python",
        },
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


# ==================== Update Server ====================


def test_update_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"update_{uuid4().hex[:8]}"

    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="original",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    response = web_client.put(
        f"/api/fastmcp/servers/{server_id}",
        headers=auth_headers,
        json={
            "server_name": "updated",
            "command": "node",
            "args": ["server.js"],
            "auto_start": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["server_name"] == "updated"
    assert payload["command"] == "node"
    assert payload["args"] == ["server.js"]
    assert payload["auto_start"] is True

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_update_server_not_found(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    response = web_client.put(
        "/api/fastmcp/servers/99999",
        headers=auth_headers,
        json={"server_name": "updated"},
    )
    assert response.status_code == 404


# ==================== Config File Endpoints ====================


def test_get_config_file(
    web_client: SyncASGIClient,
    auth_headers: dict,
    data_dir,
):
    init_db()
    unique_namespace = f"cfg_{uuid4().hex[:8]}"

    # Create server and config file
    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="config-test",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    config_dir = data_dir / "external" / "servers" / unique_namespace
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("key: value\n")

    response = web_client.get(
        f"/api/fastmcp/servers/{server_id}/config",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace"] == unique_namespace
    assert payload["content"] == "key: value\n"
    assert payload["filename"] == "config.yaml"

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_get_config_file_empty(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"empty_{uuid4().hex[:8]}"

    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="empty-config",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    response = web_client.get(
        f"/api/fastmcp/servers/{server_id}/config",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["content"] == ""

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_update_config_file(
    web_client: SyncASGIClient,
    auth_headers: dict,
    data_dir,
):
    init_db()
    unique_namespace = f"putcfg_{uuid4().hex[:8]}"

    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="put-config",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    response = web_client.put(
        f"/api/fastmcp/servers/{server_id}/config",
        headers=auth_headers,
        json={
            "content": "# New config\ndebug: true",
            "filename": "config.yaml",
        },
    )

    assert response.status_code == 200
    assert response.json()["content"] == "# New config\ndebug: true"

    # Verify file was written
    config_path = data_dir / "external" / "servers" / unique_namespace / "config.yaml"
    assert config_path.exists()
    assert "debug: true" in config_path.read_text()

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_list_config_files(
    web_client: SyncASGIClient,
    auth_headers: dict,
    data_dir,
):
    init_db()
    unique_namespace = f"files_{uuid4().hex[:8]}"

    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="files-test",
            namespace=unique_namespace,
            install_method="manual",
            startup_command="python",
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    # Create multiple config files
    config_dir = data_dir / "external" / "servers" / unique_namespace
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text("yaml: true")
    (config_dir / "settings.json").write_text('{"json": true}')
    (config_dir / ".env").write_text("ENV=prod")

    response = web_client.get(
        f"/api/fastmcp/servers/{server_id}/config/files",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    filenames = [f["filename"] for f in payload["files"]]
    assert "config.yaml" in filenames
    assert "settings.json" in filenames
    assert ".env" in filenames

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


# ==================== Start/Stop/Delete ====================


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


# ==================== Error Cases ====================


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


def test_manual_server_missing_command(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    """Manual server requires a command field."""
    response = web_client.post(
        "/api/fastmcp/servers/manual",
        headers=auth_headers,
        json={
            "namespace": "test_ns",
            "server_name": "Test",
            # Missing command field
        },
    )
    assert response.status_code == 422
