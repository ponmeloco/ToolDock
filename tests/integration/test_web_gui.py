"""
Integration tests for Backend API.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.web.server import create_web_app
from app.reload import init_reloader, reset_reloader
from tests.utils.sync_client import SyncASGIClient


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
) -> SyncASGIClient:
    """Test client with auth enabled."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    monkeypatch.setenv("DATA_DIR", str(tools_dir.parent))

    # Initialize reloader
    reset_reloader()
    init_reloader(registry, str(tools_dir))

    app = create_web_app(registry)
    client = SyncASGIClient(app)
    try:
        yield client
    finally:
        client.close()

    reset_reloader()


@pytest.fixture
def auth_headers() -> dict:
    """Bearer auth headers."""
    return {"Authorization": "Bearer test_token"}


# ==================== Health Endpoint Tests ====================


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_no_auth_required(self, client: SyncASGIClient):
        """Test health endpoint doesn't require auth."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "backend-api"

    def test_health_includes_stats(self, client: SyncASGIClient):
        """Test health includes tool statistics."""
        response = client.get("/health")

        data = response.json()
        assert "tools" in data
        assert data["tools"]["total"] >= 1


# ==================== Root Endpoint Tests ====================


class TestRootEndpoint:
    """Tests for / root endpoint."""

    def test_root_redirects_to_docs(self, client: SyncASGIClient):
        """Test root redirects to API docs."""
        response = client.get("/", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == "/docs"


# ==================== Dashboard Tests ====================


class TestDashboard:
    """Tests for dashboard API endpoint."""

    def test_dashboard_api(self, client: SyncASGIClient, auth_headers: dict):
        """Test dashboard API returns overview data."""
        response = client.get("/api/dashboard", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "namespaces" in data
        assert "endpoints" in data

    def test_dashboard_requires_auth(self, client: SyncASGIClient):
        """Test dashboard requires authentication."""
        response = client.get("/api/dashboard")

        assert response.status_code == 401


# ==================== Folders API Tests ====================


class TestFoldersAPI:
    """Tests for folders/namespaces API."""

    def test_list_folders(self, client: SyncASGIClient, auth_headers: dict):
        """Test listing folders/namespaces."""
        response = client.get("/api/folders", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "folders" in data
        folder_names = [f["name"] for f in data["folders"]]
        assert "shared" in folder_names

    def test_list_folders_requires_auth(self, client: SyncASGIClient):
        """Test listing folders requires auth."""
        response = client.get("/api/folders")

        assert response.status_code == 401


# ==================== Reload API Tests ====================


class TestReloadAPI:
    """Tests for reload API endpoints."""

    def test_reload_status(self, client: SyncASGIClient, auth_headers: dict):
        """Test getting reload status."""
        response = client.get("/api/reload/status", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert "namespaces" in data

    def test_reload_all(self, client: SyncASGIClient, auth_headers: dict):
        """Test reloading all namespaces."""
        response = client.post("/api/reload", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "message" in data

    def test_reload_namespace(
        self,
        client: SyncASGIClient,
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
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Test reloading invalid namespace returns error."""
        response = client.post(
            "/api/reload/invalid@namespace!", headers=auth_headers
        )

        assert response.status_code == 400

    def test_reload_requires_auth(self, client: SyncASGIClient):
        """Test reload requires authentication."""
        response = client.post("/api/reload")

        assert response.status_code == 401


# ==================== Tools API Tests ====================


class TestToolsAPI:
    """Tests for tools API endpoints."""

    def test_list_tools(self, client: SyncASGIClient, auth_headers: dict):
        """Test listing tools in a namespace."""
        response = client.get("/api/folders/shared/tools", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert data["namespace"] == "shared"

    def test_list_tools_requires_auth(self, client: SyncASGIClient):
        """Test listing tools requires auth."""
        response = client.get("/api/folders/shared/tools")

        assert response.status_code == 401

    def test_list_tools_nonexistent_namespace(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Test listing tools in nonexistent namespace."""
        response = client.get(
            "/api/folders/nonexistent/tools", headers=auth_headers
        )

        assert response.status_code == 404


# ==================== Security Tests ====================


class TestSecurity:
    """Security-related tests."""

    def test_invalid_bearer_token(self, client: SyncASGIClient):
        """Test invalid bearer token is rejected."""
        response = client.get(
            "/api/folders",
            headers={"Authorization": "Bearer wrong_token"},
        )

        assert response.status_code == 401

    def test_missing_auth_header(self, client: SyncASGIClient):
        """Test missing auth header is rejected."""
        response = client.get("/api/folders")

        assert response.status_code == 401

    def test_malformed_auth_header(self, client: SyncASGIClient):
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
        client: SyncASGIClient,
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
        client: SyncASGIClient,
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
        client: SyncASGIClient,
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
        client: SyncASGIClient,
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

    def test_create_tool_requires_auth(self, client: SyncASGIClient):
        """Test create-from-template requires authentication."""
        response = client.post(
            "/api/folders/shared/tools/create-from-template",
            json={"name": "test_tool"},
        )

        assert response.status_code == 401

    def test_create_tool_nonexistent_namespace(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test creating tool in nonexistent namespace."""
        response = client.post(
            "/api/folders/nonexistent/tools/create-from-template",
            headers=auth_headers,
            json={"name": "test_tool"},
        )

        assert response.status_code == 404


# ==================== Get Tool Tests ====================


class TestGetTool:
    """Tests for GET /api/folders/{namespace}/tools/{filename} endpoint."""

    def test_get_tool_success(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test getting a tool file."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        tool_content = '''
from pydantic import BaseModel, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = ""

async def handler(payload): return "test"

def register_tools(registry):
    registry.register(ToolDefinition(name="test", description="Test", input_model=TestInput, handler=handler))
'''
        (shared_dir / "test_tool.py").write_text(tool_content)

        response = client.get(
            "/api/folders/shared/tools/test_tool.py",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test_tool.py"
        assert data["namespace"] == "shared"
        assert "content" in data
        assert "validation" in data

    def test_get_tool_not_found(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test getting non-existent tool."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        response = client.get(
            "/api/folders/shared/tools/nonexistent.py",
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_get_tool_path_traversal(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test path traversal is blocked."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        # Try various path traversal attempts in filename
        traversal_attempts = [
            "../secret.py",
            "..%2Fsecret.py",
            "test/../secret.py",
        ]

        for attempt in traversal_attempts:
            response = client.get(
                f"/api/folders/shared/tools/{attempt}",
                headers=auth_headers,
            )
            # Should be blocked - either as invalid filename (400) or not found (404)
            # The important thing is it doesn't return 200 or leak information
            assert response.status_code in (400, 404), f"Path traversal not blocked: {attempt}"

    def test_get_tool_invalid_filename(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test invalid filename is rejected."""
        response = client.get(
            "/api/folders/shared/tools/not_python.txt",
            headers=auth_headers,
        )

        assert response.status_code == 400


# ==================== Update Tool Tests ====================


class TestUpdateTool:
    """Tests for PUT /api/folders/{namespace}/tools/{filename} endpoint."""

    def test_update_tool_success(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test updating a tool file."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        original_content = '''
from pydantic import BaseModel, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

async def handler(payload): return "original"

def register_tools(registry):
    registry.register(ToolDefinition(name="test", description="Test", input_model=TestInput, handler=handler))
'''
        (shared_dir / "update_test.py").write_text(original_content)

        new_content = '''
from pydantic import BaseModel, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_field: str = "updated"

async def handler(payload): return "updated"

def register_tools(registry):
    registry.register(ToolDefinition(name="test", description="Updated test", input_model=TestInput, handler=handler))
'''

        response = client.put(
            "/api/folders/shared/tools/update_test.py",
            headers=auth_headers,
            json={"content": new_content, "skip_validation": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify file was updated
        updated_content = (shared_dir / "update_test.py").read_text()
        assert "updated" in updated_content

    def test_update_tool_not_found(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test updating non-existent tool."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        response = client.put(
            "/api/folders/shared/tools/nonexistent.py",
            headers=auth_headers,
            json={"content": "# test", "skip_validation": True},
        )

        assert response.status_code == 404

    def test_update_tool_validation_failure(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test updating with invalid content fails validation."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        (shared_dir / "validate_test.py").write_text("# original")

        invalid_content = "def broken syntax("

        response = client.put(
            "/api/folders/shared/tools/validate_test.py",
            headers=auth_headers,
            json={"content": invalid_content, "skip_validation": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert data["validation"]["is_valid"] is False

    def test_update_requires_valid_json(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test update requires valid JSON body."""
        response = client.put(
            "/api/folders/shared/tools/test.py",
            headers=auth_headers,
            content="not json",
        )

        assert response.status_code == 422


# ==================== Delete Tool Tests ====================


class TestDeleteTool:
    """Tests for DELETE /api/folders/{namespace}/tools/{filename} endpoint."""

    def test_delete_tool_success(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test deleting a tool file."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)
        tool_file = shared_dir / "to_delete.py"
        tool_file.write_text("# delete me")

        assert tool_file.exists()

        response = client.delete(
            "/api/folders/shared/tools/to_delete.py",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify file was deleted
        assert not tool_file.exists()

    def test_delete_tool_not_found(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test deleting non-existent tool."""
        shared_dir = tools_dir / "shared"
        shared_dir.mkdir(exist_ok=True)

        response = client.delete(
            "/api/folders/shared/tools/nonexistent.py",
            headers=auth_headers,
        )

        assert response.status_code == 404


# ==================== Validate Tool Tests ====================


class TestValidateTool:
    """Tests for POST /api/folders/{namespace}/tools/validate endpoint."""

    def test_validate_valid_tool(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test validating a valid tool file."""
        valid_content = '''
from pydantic import BaseModel, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

async def handler(payload): return "test"

def register_tools(registry):
    registry.register(ToolDefinition(name="test", description="Test", input_model=TestInput, handler=handler))
'''
        response = client.post(
            "/api/folders/shared/tools/validate",
            headers=auth_headers,
            files={"file": ("test.py", valid_content, "text/plain")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is True

    def test_validate_invalid_tool(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test validating an invalid tool file."""
        invalid_content = "def broken("

        response = client.post(
            "/api/folders/shared/tools/validate",
            headers=auth_headers,
            files={"file": ("test.py", invalid_content, "text/plain")},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0


# ==================== Folders CRUD Tests ====================


class TestFoldersCRUD:
    """Tests for folder/namespace CRUD operations."""

    def test_create_folder(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test creating a new folder."""
        response = client.post(
            "/api/folders",
            headers=auth_headers,
            json={"name": "my_new_namespace"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "my_new_namespace"
        assert data["tool_count"] == 0

    def test_create_folder_reserved_name(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test creating folder with reserved name fails."""
        response = client.post(
            "/api/folders",
            headers=auth_headers,
            json={"name": "external"},  # Reserved name
        )

        assert response.status_code == 400
        assert "reserved" in response.json()["detail"].lower()

    def test_create_folder_duplicate(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test creating duplicate folder fails."""
        # Create first
        client.post(
            "/api/folders",
            headers=auth_headers,
            json={"name": "duplicate_test"},
        )

        # Try to create again
        response = client.post(
            "/api/folders",
            headers=auth_headers,
            json={"name": "duplicate_test"},
        )

        assert response.status_code == 409

    def test_get_folder(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test getting folder info."""
        # Create folder with tools
        test_dir = tools_dir / "test_ns"
        test_dir.mkdir(parents=True)
        (test_dir / "tool1.py").write_text("# tool1")
        (test_dir / "tool2.py").write_text("# tool2")

        response = client.get("/api/folders/test_ns", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_ns"
        assert data["tool_count"] == 2

    def test_get_folder_not_found(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test getting non-existent folder."""
        response = client.get("/api/folders/nonexistent", headers=auth_headers)

        assert response.status_code == 404

    def test_delete_folder_empty(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test deleting empty folder."""
        # Create empty folder
        test_dir = tools_dir / "to_delete"
        test_dir.mkdir(parents=True)

        response = client.delete(
            "/api/folders/to_delete",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert not test_dir.exists()

    def test_delete_folder_with_tools_requires_force(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test deleting folder with tools requires force flag."""
        # Create folder with tool
        test_dir = tools_dir / "has_tools"
        test_dir.mkdir(parents=True)
        (test_dir / "tool.py").write_text("# tool")

        response = client.delete(
            "/api/folders/has_tools",
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "force" in response.json()["detail"].lower()

        # With force=true
        response = client.delete(
            "/api/folders/has_tools?force=true",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert not test_dir.exists()

    def test_delete_reserved_folder(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
    ):
        """Test deleting reserved folder fails."""
        response = client.delete(
            "/api/folders/shared",
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "reserved" in response.json()["detail"].lower()

    def test_namespace_info(
        self,
        client: SyncASGIClient,
        auth_headers: dict,
        tools_dir: Path,
    ):
        """Test namespace info includes correct endpoint."""
        test_dir = tools_dir / "myns"
        test_dir.mkdir(parents=True)

        response = client.get("/api/folders/myns", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["endpoint"] == "/mcp/myns"
