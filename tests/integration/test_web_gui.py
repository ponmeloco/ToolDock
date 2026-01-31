"""
Integration tests for Backend API.
"""

from __future__ import annotations

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
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    monkeypatch.setenv("DATA_DIR", str(tools_dir.parent))

    # Initialize reloader
    reset_reloader()
    init_reloader(registry, str(tools_dir))

    app = create_web_app(registry)
    yield TestClient(app)

    reset_reloader()


@pytest.fixture
def auth_headers() -> dict:
    """Bearer auth headers."""
    return {"Authorization": "Bearer test_token"}


# ==================== Health Endpoint Tests ====================


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_no_auth_required(self, client: TestClient):
        """Test health endpoint doesn't require auth."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "backend-api"

    def test_health_includes_stats(self, client: TestClient):
        """Test health includes tool statistics."""
        response = client.get("/health")

        data = response.json()
        assert "tools" in data
        assert data["tools"]["total"] >= 1


# ==================== Root Endpoint Tests ====================


class TestRootEndpoint:
    """Tests for / root endpoint."""

    def test_root_redirects_to_docs(self, client: TestClient):
        """Test root redirects to API docs."""
        response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/docs"


# ==================== Dashboard Tests ====================


class TestDashboard:
    """Tests for dashboard API endpoint."""

    def test_dashboard_api(self, client: TestClient, auth_headers: dict):
        """Test dashboard API returns overview data."""
        response = client.get("/api/dashboard", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "namespaces" in data
        assert "endpoints" in data

    def test_dashboard_requires_auth(self, client: TestClient):
        """Test dashboard requires authentication."""
        response = client.get("/api/dashboard")

        assert response.status_code == 401


# ==================== Folders API Tests ====================


class TestFoldersAPI:
    """Tests for folders/namespaces API."""

    def test_list_folders(self, client: TestClient, auth_headers: dict):
        """Test listing folders/namespaces."""
        response = client.get("/api/folders", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "folders" in data
        folder_names = [f["name"] for f in data["folders"]]
        assert "shared" in folder_names

    def test_list_folders_requires_auth(self, client: TestClient):
        """Test listing folders requires auth."""
        response = client.get("/api/folders")

        assert response.status_code == 401


# ==================== Reload API Tests ====================


class TestReloadAPI:
    """Tests for reload API endpoints."""

    def test_reload_status(self, client: TestClient, auth_headers: dict):
        """Test getting reload status."""
        response = client.get("/api/reload/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert "namespaces" in data

    def test_reload_all(self, client: TestClient, auth_headers: dict):
        """Test reloading all namespaces."""
        response = client.post("/api/reload", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "message" in data

    def test_reload_namespace(
        self,
        client: TestClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test reloading a specific namespace."""
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

        response = client.post("/api/reload/shared", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_reload_invalid_namespace(
        self, client: TestClient, auth_headers: dict
    ):
        """Test reloading invalid namespace returns error."""
        response = client.post(
            "/api/reload/invalid@namespace!", headers=auth_headers
        )

        assert response.status_code == 400

    def test_reload_requires_auth(self, client: TestClient):
        """Test reload requires authentication."""
        response = client.post("/api/reload")

        assert response.status_code == 401


# ==================== Tools API Tests ====================


class TestToolsAPI:
    """Tests for tools API endpoints."""

    def test_list_tools(self, client: TestClient, auth_headers: dict):
        """Test listing tools in a namespace."""
        response = client.get("/api/folders/shared/tools", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert data["namespace"] == "shared"

    def test_list_tools_requires_auth(self, client: TestClient):
        """Test listing tools requires auth."""
        response = client.get("/api/folders/shared/tools")

        assert response.status_code == 401

    def test_list_tools_nonexistent_namespace(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing tools in nonexistent namespace."""
        response = client.get(
            "/api/folders/nonexistent/tools", headers=auth_headers
        )

        assert response.status_code == 404


# ==================== Security Tests ====================


class TestSecurity:
    """Security-related tests."""

    def test_invalid_bearer_token(self, client: TestClient):
        """Test invalid bearer token is rejected."""
        response = client.get(
            "/api/folders",
            headers={"Authorization": "Bearer wrong_token"},
        )

        assert response.status_code == 401

    def test_missing_auth_header(self, client: TestClient):
        """Test missing auth header is rejected."""
        response = client.get("/api/folders")

        assert response.status_code == 401

    def test_malformed_auth_header(self, client: TestClient):
        """Test malformed auth header is rejected."""
        response = client.get(
            "/api/folders",
            headers={"Authorization": "InvalidFormat token"},
        )

        assert response.status_code == 401


# ==================== Create Tool From Template Tests ====================


class TestCreateToolFromTemplate:
    """Tests for create-from-template API endpoint."""

    def test_create_tool_from_template(
        self,
        client: TestClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test creating a new tool from template."""
        # Ensure shared directory exists
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        response = client.post(
            "/api/folders/shared/tools/create-from-template",
            headers=auth_headers,
            json={"name": "my_new_tool"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["filename"] == "my_new_tool.py"
        assert "my_new_tool.py" in data["path"]

        # Verify file was created
        tool_file = tools_dir / "shared" / "my_new_tool.py"
        assert tool_file.exists()

        # Verify content has correct class name
        content = tool_file.read_text()
        assert "class MyNewToolInput" in content
        assert "async def my_new_tool_handler" in content
        assert 'name="my_new_tool"' in content

    def test_create_tool_requires_snake_case(
        self,
        client: TestClient,
        auth_headers: dict,
    ):
        """Test tool name must be snake_case."""
        response = client.post(
            "/api/folders/shared/tools/create-from-template",
            headers=auth_headers,
            json={"name": "MyTool"},  # PascalCase not allowed
        )

        assert response.status_code == 400
        assert "snake_case" in response.json()["detail"]

    def test_create_tool_rejects_invalid_chars(
        self,
        client: TestClient,
        auth_headers: dict,
    ):
        """Test tool name rejects invalid characters."""
        response = client.post(
            "/api/folders/shared/tools/create-from-template",
            headers=auth_headers,
            json={"name": "my-tool"},  # Hyphens not allowed
        )

        assert response.status_code == 400

    def test_create_tool_rejects_existing(
        self,
        client: TestClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test cannot create tool with existing name."""
        # Create existing file
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        (shared_dir / "existing_tool.py").write_text("# existing")

        response = client.post(
            "/api/folders/shared/tools/create-from-template",
            headers=auth_headers,
            json={"name": "existing_tool"},
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]

    def test_create_tool_requires_auth(self, client: TestClient):
        """Test create-from-template requires authentication."""
        response = client.post(
            "/api/folders/shared/tools/create-from-template",
            json={"name": "test_tool"},
        )

        assert response.status_code == 401

    def test_create_tool_nonexistent_namespace(
        self,
        client: TestClient,
        auth_headers: dict,
    ):
        """Test creating tool in nonexistent namespace."""
        response = client.post(
            "/api/folders/nonexistent/tools/create-from-template",
            headers=auth_headers,
            json={"name": "test_tool"},
        )

        assert response.status_code == 404
