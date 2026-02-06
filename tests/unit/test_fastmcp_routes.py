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
        self.registry = SimpleNamespace(get_stats=lambda: {"external": 2})

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
            entrypoint=None,
            port=9100,
            status="stopped",
            pid=None,
            last_error=None,
            startup_command="python",
            command_args=["-m", "demo_module"],
            package_type="pypi",
            source_url="https://github.com/example/demo",
        )

    async def add_server_from_repo(self, repo_url, namespace, entrypoint=None, server_name=None, auto_start=True):
        self.calls["add_server_from_repo"] = {
            "repo_url": repo_url,
            "namespace": namespace,
            "entrypoint": entrypoint,
            "server_name": server_name,
            "auto_start": auto_start,
        }
        return SimpleNamespace(
            id=2,
            server_name=server_name or repo_url,
            namespace=namespace,
            version=None,
            install_method="repo",
            repo_url=repo_url,
            entrypoint=entrypoint,
            port=9200,
            status="stopped",
            pid=None,
            last_error=None,
            startup_command="python",
            command_args=["server.py"],
            package_type="repo",
            source_url=repo_url,
        )

    async def assess_installation_safety(self, **kwargs):
        self.calls["assess_installation_safety"] = kwargs
        return {
            "risk_level": "low",
            "risk_score": 0,
            "blocked": False,
            "summary": "Low risk",
            "checks": [],
            "resolved_server": {"id": "server-123", "name": "demo"},
            "required_env": [],
            "suggested_namespace": "demo",
        }

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

    async def sync_from_db(self):
        self.calls["sync_from_db"] = True
        return {"running": 0, "connected": 0}


class _FailingFastMCPManager:
    async def list_registry_servers(self, limit=30, cursor=None, search=None):
        raise RuntimeError("registry unavailable")

    async def add_server_from_registry(self, server_name, namespace, version=None, server_id=None):
        raise RuntimeError("install failed")

    async def add_server_from_repo(self, repo_url, namespace, entrypoint=None, server_name=None, auto_start=True):
        raise RuntimeError("repo install failed")

    async def assess_installation_safety(self, **kwargs):
        raise RuntimeError("safety failed")

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


@pytest.fixture(autouse=True)
def cleanup_test_servers(data_dir):
    """Clean up any test-created server records after each test."""
    yield
    # Cleanup runs after test completes (success or failure)
    with get_db() as db:
        # Delete any records with test-like namespaces
        db.query(ExternalFastMCPServer).filter(
            ExternalFastMCPServer.namespace.like("update_%") |
            ExternalFastMCPServer.namespace.like("config_%") |
            ExternalFastMCPServer.namespace.like("manual_%") |
            ExternalFastMCPServer.namespace.like("test_%") |
            ExternalFastMCPServer.namespace.like("provenance_%") |
            ExternalFastMCPServer.namespace.like("legacy_%")
        ).delete(synchronize_session=False)
        db.commit()


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
            package_type="pypi",
            source_url="https://github.com/example/test",
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
    assert payload["package_type"] == "pypi"
    assert payload["source_url"] == "https://github.com/example/test"

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
    """GET endpoints require auth when BEARER_TOKEN is set."""
    response = web_client.get("/api/fastmcp/servers")
    assert response.status_code == 401


def test_registry_servers_without_auth(
    web_client: SyncASGIClient,
    fastmcp_stub: _StubFastMCPManager,
):
    """Registry list requires auth when BEARER_TOKEN is set."""
    response = web_client.get("/api/fastmcp/registry/servers")
    assert response.status_code == 401


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
    assert payload["package_type"] == "pypi"
    assert payload["source_url"] == "https://github.com/example/demo"
    assert fastmcp_stub.calls["add_server_from_registry"]["server_name"] == "demo"
    assert fastmcp_stub.calls["add_server_from_registry"]["server_id"] == "server-1234"


def test_add_repo_fastmcp_server(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post(
        "/api/fastmcp/servers/repo",
        headers=auth_headers,
        json={
            "repo_url": "https://github.com/example/mcp-server.git",
            "namespace": "repo_demo",
            "entrypoint": "server.py",
            "server_name": "Repo Demo",
            "auto_start": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace"] == "repo_demo"
    assert payload["install_method"] == "repo"
    assert payload["source_url"] == "https://github.com/example/mcp-server.git"
    assert fastmcp_stub.calls["add_server_from_repo"]["namespace"] == "repo_demo"


def test_safety_check_endpoint(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post(
        "/api/fastmcp/safety/check",
        headers=auth_headers,
        json={"server_id": "server-1234"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_level"] == "low"
    assert fastmcp_stub.calls["assess_installation_safety"]["server_id"] == "server-1234"


def test_sync_fastmcp_servers(
    web_client: SyncASGIClient,
    auth_headers: dict,
    fastmcp_stub: _StubFastMCPManager,
):
    response = web_client.post("/api/fastmcp/sync", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["external_tools"] == 2
    assert fastmcp_stub.calls["sync_from_db"] is True


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
    assert payload["package_type"] == "manual"
    assert payload["status"] == "stopped"

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()


def test_add_from_config_server_without_pip_package(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    init_db()
    unique_namespace = f"fromcfg_{uuid4().hex[:8]}"

    response = web_client.post(
        "/api/fastmcp/servers/from-config",
        headers=auth_headers,
        json={
            "namespace": unique_namespace,
            "config": {
                "command": "python",
                "args": ["-m", "my_mcp_server"],
                "env": {"API_KEY": "test-key"},
            },
            "auto_start": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["namespace"] == unique_namespace
    assert payload["command"] == "python"
    assert payload["args"] == ["-m", "my_mcp_server"]
    assert payload["env"] == {"API_KEY": "test-key"}

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
    fastmcp_stub: _StubFastMCPManager,
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
    # Cleanup handled by cleanup_test_servers fixture


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


def test_reserved_namespace_rejected(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    response = web_client.post(
        "/api/fastmcp/servers/manual",
        headers=auth_headers,
        json={
            "namespace": "tooldock-installer",
            "server_name": "Reserved",
            "command": "python",
        },
    )
    assert response.status_code == 409
    assert "reserved" in response.json()["detail"].lower()


# ==================== Provenance Fields ====================


def test_provenance_fields_null_when_absent(
    web_client: SyncASGIClient,
    auth_headers: dict,
):
    """package_type and source_url are null for legacy records."""
    init_db()
    unique_namespace = f"legacy_{uuid4().hex[:8]}"

    with get_db() as db:
        record = ExternalFastMCPServer(
            server_name="legacy-server",
            namespace=unique_namespace,
            install_method="package",
            startup_command="npx",
            command_args=["-y", "some-package"],
            status="stopped",
        )
        db.add(record)
        db.commit()
        server_id = record.id

    response = web_client.get(f"/api/fastmcp/servers/{server_id}", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["package_type"] is None
    assert payload["source_url"] is None

    # Cleanup
    with get_db() as db:
        db.query(ExternalFastMCPServer).filter_by(namespace=unique_namespace).delete()
        db.commit()
