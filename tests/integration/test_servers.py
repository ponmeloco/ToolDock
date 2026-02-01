"""
Integration tests for External Servers API (/api/servers).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.web.server import create_web_app
from app.reload import init_reloader, reset_reloader


# ==================== Fixtures ====================


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh registry."""
    reset_registry()
    reg = ToolRegistry()
    yield reg
    reset_registry()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Temporary data directory."""
    # Create required subdirectories
    (tmp_path / "tools" / "shared").mkdir(parents=True)
    (tmp_path / "external").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def client(
    registry: ToolRegistry,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Test client with auth enabled."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    monkeypatch.setenv("DATA_DIR", str(data_dir))

    reset_reloader()
    init_reloader(registry, str(data_dir / "tools"))

    app = create_web_app(registry)
    yield TestClient(app)

    reset_reloader()


@pytest.fixture
def auth_headers() -> dict:
    """Bearer auth headers."""
    return {"Authorization": "Bearer test_token"}


# ==================== List Servers Tests ====================


class TestListServers:
    """Tests for GET /api/servers endpoint."""

    def test_list_servers_empty(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing servers when none configured."""
        response = client.get("/api/servers", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["servers"] == []
        assert data["total"] == 0

    def test_list_servers_with_config(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test listing servers with config file."""
        config = {
            "servers": {
                "github": {
                    "source": "custom",
                    "command": "npx",
                    "args": ["-y", "@github/mcp-server"],
                    "enabled": True,
                },
                "disabled-server": {
                    "source": "custom",
                    "command": "echo",
                    "enabled": False,
                },
            }
        }
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        response = client.get("/api/servers", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2

        # Check servers are sorted by ID
        server_ids = [s["server_id"] for s in data["servers"]]
        assert "github" in server_ids
        assert "disabled-server" in server_ids

    def test_list_servers_masks_sensitive_data(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test sensitive config values are masked."""
        config = {
            "servers": {
                "test": {
                    "source": "custom",
                    "command": "echo",
                    "env": {
                        "API_KEY": "secret123",
                        "GITHUB_TOKEN": "ghp_xxxxx",
                        "NORMAL_VAR": "visible",
                    },
                }
            }
        }
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        response = client.get("/api/servers", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        server = data["servers"][0]

        # Sensitive values should be masked
        assert server["config"]["env"]["API_KEY"] == "***MASKED***"
        assert server["config"]["env"]["GITHUB_TOKEN"] == "***MASKED***"
        # Normal values should be visible
        assert server["config"]["env"]["NORMAL_VAR"] == "visible"

    def test_list_servers_requires_auth(self, client: TestClient):
        """Test listing servers requires authentication."""
        response = client.get("/api/servers")
        assert response.status_code == 401


# ==================== Get Server Tests ====================


class TestGetServer:
    """Tests for GET /api/servers/{server_id} endpoint."""

    def test_get_server_success(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test getting a specific server."""
        config = {
            "servers": {
                "myserver": {
                    "source": "custom",
                    "command": "python",
                    "args": ["-m", "myserver"],
                    "enabled": True,
                }
            }
        }
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        response = client.get("/api/servers/myserver", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == "myserver"
        assert data["namespace"] == "myserver"
        assert data["endpoint"] == "/mcp/myserver"

    def test_get_server_not_found(
        self, client: TestClient, auth_headers: dict
    ):
        """Test getting non-existent server."""
        response = client.get("/api/servers/nonexistent", headers=auth_headers)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_server_requires_auth(self, client: TestClient):
        """Test getting server requires authentication."""
        response = client.get("/api/servers/test")
        assert response.status_code == 401


# ==================== Add Server Tests ====================


class TestAddServer:
    """Tests for POST /api/servers endpoint."""

    def test_add_server_custom(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test adding a custom server."""
        request = {
            "server_id": "newserver",
            "config": {
                "source": "custom",
                "command": "npx",
                "args": ["-y", "@test/server"],
                "enabled": True,
            },
        }

        response = client.post("/api/servers", headers=auth_headers, json=request)

        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == "newserver"
        assert data["enabled"] is True

        # Verify config was saved
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "r") as f:
            saved_config = yaml.safe_load(f)
        assert "newserver" in saved_config["servers"]

    def test_add_server_registry(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test adding a registry-sourced server."""
        request = {
            "server_id": "github",
            "config": {
                "source": "registry",
                "name": "io.github.modelcontextprotocol/server-github",
                "enabled": True,
            },
        }

        response = client.post("/api/servers", headers=auth_headers, json=request)

        assert response.status_code == 200
        data = response.json()
        assert data["server_id"] == "github"
        assert data["config"]["source"] == "registry"

    def test_add_server_duplicate(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test adding duplicate server returns 409."""
        # Create existing server
        config = {"servers": {"existing": {"enabled": True}}}
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        request = {
            "server_id": "existing",
            "config": {"source": "custom", "command": "echo"},
        }

        response = client.post("/api/servers", headers=auth_headers, json=request)

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_add_server_invalid_id(
        self, client: TestClient, auth_headers: dict
    ):
        """Test adding server with invalid ID."""
        request = {
            "server_id": "Invalid-ID!",  # Invalid characters
            "config": {"source": "custom", "command": "echo"},
        }

        response = client.post("/api/servers", headers=auth_headers, json=request)

        assert response.status_code == 422  # Validation error

    def test_add_server_requires_auth(self, client: TestClient):
        """Test adding server requires authentication."""
        response = client.post(
            "/api/servers", json={"server_id": "test", "config": {}}
        )
        assert response.status_code == 401


# ==================== Update Server Tests ====================


class TestUpdateServer:
    """Tests for PUT /api/servers/{server_id} endpoint."""

    def test_update_server_success(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test updating a server."""
        # Create existing server
        config = {
            "servers": {
                "test": {
                    "source": "custom",
                    "command": "echo",
                    "enabled": True,
                }
            }
        }
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        # Update with new config
        new_config = {
            "source": "custom",
            "command": "python",
            "args": ["-m", "updated"],
            "enabled": False,
        }

        response = client.put(
            "/api/servers/test", headers=auth_headers, json=new_config
        )

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False

        # Verify config was updated
        with open(config_path, "r") as f:
            saved_config = yaml.safe_load(f)
        assert saved_config["servers"]["test"]["command"] == "python"

    def test_update_server_not_found(
        self, client: TestClient, auth_headers: dict
    ):
        """Test updating non-existent server."""
        response = client.put(
            "/api/servers/nonexistent",
            headers=auth_headers,
            json={"source": "custom", "command": "echo"},
        )

        assert response.status_code == 404

    def test_update_server_requires_auth(self, client: TestClient):
        """Test updating server requires authentication."""
        response = client.put(
            "/api/servers/test", json={"source": "custom", "command": "echo"}
        )
        assert response.status_code == 401


# ==================== Delete Server Tests ====================


class TestDeleteServer:
    """Tests for DELETE /api/servers/{server_id} endpoint."""

    def test_delete_server_success(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test deleting a server."""
        # Create existing server
        config = {"servers": {"todelete": {"enabled": True}}}
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        response = client.delete("/api/servers/todelete", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify server was removed
        with open(config_path, "r") as f:
            saved_config = yaml.safe_load(f)
        assert "todelete" not in saved_config.get("servers", {})

    def test_delete_server_not_found(
        self, client: TestClient, auth_headers: dict
    ):
        """Test deleting non-existent server."""
        response = client.delete("/api/servers/nonexistent", headers=auth_headers)

        assert response.status_code == 404

    def test_delete_server_requires_auth(self, client: TestClient):
        """Test deleting server requires authentication."""
        response = client.delete("/api/servers/test")
        assert response.status_code == 401


# ==================== Enable/Disable Server Tests ====================


class TestEnableDisableServer:
    """Tests for enable/disable server endpoints."""

    def test_enable_server(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test enabling a disabled server."""
        config = {"servers": {"test": {"enabled": False}}}
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        response = client.post("/api/servers/test/enable", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify server was enabled
        with open(config_path, "r") as f:
            saved_config = yaml.safe_load(f)
        assert saved_config["servers"]["test"]["enabled"] is True

    def test_disable_server(
        self, client: TestClient, auth_headers: dict, data_dir: Path
    ):
        """Test disabling an enabled server."""
        config = {"servers": {"test": {"enabled": True}}}
        config_path = data_dir / "external" / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f)

        response = client.post("/api/servers/test/disable", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify server was disabled
        with open(config_path, "r") as f:
            saved_config = yaml.safe_load(f)
        assert saved_config["servers"]["test"]["enabled"] is False

    def test_enable_nonexistent_server(
        self, client: TestClient, auth_headers: dict
    ):
        """Test enabling non-existent server."""
        response = client.post("/api/servers/nonexistent/enable", headers=auth_headers)
        assert response.status_code == 404

    def test_disable_nonexistent_server(
        self, client: TestClient, auth_headers: dict
    ):
        """Test disabling non-existent server."""
        response = client.post("/api/servers/nonexistent/disable", headers=auth_headers)
        assert response.status_code == 404
