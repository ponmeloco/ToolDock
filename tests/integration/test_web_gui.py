"""
Integration tests for Web GUI.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.web.server import create_web_app
from app.reload import init_reloader, reset_reloader


# ==================== Fixtures ====================


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh registry with test tools."""
    reset_registry()
    reg = ToolRegistry()

    class TestInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: str = Field(default="test", description="Test value")

    async def test_handler(payload: TestInput) -> str:
        return f"Value: {payload.value}"

    TestInput.model_rebuild(force=True)
    reg.register(
        ToolDefinition(
            name="web_test_tool",
            description="Test tool for web GUI",
            input_model=TestInput,
            handler=test_handler,
        ),
        namespace="shared",
    )

    yield reg
    reset_registry()


@pytest.fixture
def tools_dir(tmp_path: Path) -> Path:
    """Temporary tools directory."""
    tools = tmp_path / "tools" / "shared"
    tools.mkdir(parents=True)
    return tools.parent


@pytest.fixture
def client(
    registry: ToolRegistry,
    tools_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Test client with auth enabled."""
    monkeypatch.setenv("BEARER_TOKEN", "test_password")
    monkeypatch.setenv("DATA_DIR", str(tools_dir.parent))

    # Initialize reloader
    reset_reloader()
    init_reloader(registry, str(tools_dir))

    app = create_web_app(registry)
    yield TestClient(app)

    reset_reloader()


@pytest.fixture
def basic_auth_headers() -> dict:
    """Basic auth headers (username: admin, password: test_password)."""
    credentials = base64.b64encode(b"admin:test_password").decode("utf-8")
    return {"Authorization": f"Basic {credentials}"}


@pytest.fixture
def bearer_auth_headers() -> dict:
    """Bearer auth headers."""
    return {"Authorization": "Bearer test_password"}


# ==================== Health Endpoint Tests ====================


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_no_auth_required(self, client: TestClient):
        """Test health endpoint doesn't require auth."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "web-gui"

    def test_health_includes_stats(self, client: TestClient):
        """Test health includes tool statistics."""
        response = client.get("/health")

        data = response.json()
        assert "tools" in data
        assert data["tools"]["total"] >= 1


# ==================== Dashboard Tests ====================


class TestDashboard:
    """Tests for dashboard endpoints."""

    def test_dashboard_api(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test dashboard API returns overview data."""
        response = client.get("/api/dashboard", headers=basic_auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "namespaces" in data
        assert "endpoints" in data

    def test_dashboard_requires_auth(self, client: TestClient):
        """Test dashboard requires authentication."""
        response = client.get("/api/dashboard")

        assert response.status_code == 401

    def test_dashboard_html(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test HTML dashboard is served."""
        response = client.get("/", headers=basic_auth_headers)

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "OmniMCP" in response.text


# ==================== Folders API Tests ====================


class TestFoldersAPI:
    """Tests for folders/namespaces API."""

    def test_list_folders(
        self, client: TestClient, bearer_auth_headers: dict
    ):
        """Test listing folders/namespaces."""
        # Note: folders API uses verify_token dependency which requires Bearer token
        response = client.get("/api/folders", headers=bearer_auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "folders" in data
        # Should have at least 'shared' from our test tool
        folder_names = [f["name"] for f in data["folders"]]
        assert "shared" in folder_names

    def test_list_folders_requires_auth(self, client: TestClient):
        """Test listing folders requires auth."""
        response = client.get("/api/folders")

        assert response.status_code == 401

    def test_list_folders_accepts_bearer(
        self, client: TestClient, bearer_auth_headers: dict
    ):
        """Test folders API accepts bearer token."""
        response = client.get("/api/folders", headers=bearer_auth_headers)

        assert response.status_code == 200


# ==================== Reload API Tests ====================


class TestReloadAPI:
    """Tests for reload API endpoints."""

    def test_reload_status(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test getting reload status."""
        response = client.get("/api/reload/status", headers=basic_auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert "namespaces" in data

    def test_reload_all(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test reloading all namespaces."""
        response = client.post("/api/reload", headers=basic_auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "message" in data

    def test_reload_namespace(
        self,
        client: TestClient,
        basic_auth_headers: dict,
        tools_dir: Path,
    ):
        """Test reloading a specific namespace."""
        # Create a tool file in the namespace
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class ReloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "reloaded"

def register_tools(registry):
    ReloadInput.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="reloaded_tool",
        description="Tool loaded via reload",
        input_model=ReloadInput,
        handler=handler,
    ))
'''
        (shared_dir / "reload_test.py").write_text(tool_code)

        response = client.post(
            "/api/reload/shared",
            headers=basic_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_reload_invalid_namespace(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test reloading invalid namespace name (with special characters)."""
        # Namespace with special characters should be rejected
        response = client.post(
            "/api/reload/invalid@namespace!",
            headers=basic_auth_headers,
        )

        assert response.status_code == 400

    def test_reload_nonexistent_namespace(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test reloading nonexistent namespace."""
        response = client.post(
            "/api/reload/nonexistent_ns",
            headers=basic_auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    def test_reload_requires_auth(self, client: TestClient):
        """Test reload requires authentication."""
        response = client.post("/api/reload")

        assert response.status_code == 401


# ==================== Authentication Tests ====================


class TestWebGUIAuthentication:
    """Tests for Web GUI authentication."""

    def test_basic_auth_works(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test basic auth works for web GUI."""
        response = client.get("/api/dashboard", headers=basic_auth_headers)

        assert response.status_code == 200

    def test_bearer_auth_works(
        self, client: TestClient, bearer_auth_headers: dict
    ):
        """Test bearer auth works for API endpoints."""
        response = client.get("/api/folders", headers=bearer_auth_headers)

        assert response.status_code == 200

    def test_invalid_basic_auth(self, client: TestClient):
        """Test invalid basic auth is rejected."""
        credentials = base64.b64encode(b"admin:wrong_password").decode("utf-8")
        headers = {"Authorization": f"Basic {credentials}"}

        response = client.get("/api/dashboard", headers=headers)

        assert response.status_code == 401

    def test_invalid_bearer_token(self, client: TestClient):
        """Test invalid bearer token is rejected."""
        headers = {"Authorization": "Bearer wrong_token"}

        response = client.get("/api/folders", headers=headers)

        assert response.status_code == 401

    def test_auth_disabled_allows_access(
        self, registry: ToolRegistry, tools_dir: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Test disabling auth allows access."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        reset_reloader()
        init_reloader(registry, str(tools_dir))

        app = create_web_app(registry)
        client = TestClient(app)

        response = client.get("/api/dashboard")

        assert response.status_code == 200
        reset_reloader()


# ==================== Error Handling Tests ====================


class TestErrorHandling:
    """Tests for error handling."""

    def test_unknown_endpoint_404(
        self, client: TestClient, basic_auth_headers: dict
    ):
        """Test unknown endpoint returns 404."""
        response = client.get("/api/unknown", headers=basic_auth_headers)

        assert response.status_code == 404
