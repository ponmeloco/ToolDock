"""
Integration tests for Playground API (/api/playground).
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

    async def test_handler(payload: TestInput) -> dict:
        return {"echo": payload.value, "status": "ok"}

    TestInput.model_rebuild(force=True)
    reg.register(
        ToolDefinition(
            name="playground_test_tool",
            description="Test tool for playground",
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

    reset_reloader()
    init_reloader(registry, str(tools_dir))

    app = create_web_app(registry)
    yield TestClient(app)

    reset_reloader()


@pytest.fixture
def auth_headers() -> dict:
    """Bearer auth headers."""
    return {"Authorization": "Bearer test_token"}


# ==================== List Tools Tests ====================


class TestPlaygroundListTools:
    """Tests for GET /api/playground/tools endpoint."""

    def test_list_tools_success(self, client: TestClient, auth_headers: dict):
        """Test listing playground tools."""
        response = client.get("/api/playground/tools", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert "total" in data
        assert data["total"] >= 1

        # Check tool structure
        tool = next((t for t in data["tools"] if t["name"] == "playground_test_tool"), None)
        assert tool is not None
        assert tool["description"] == "Test tool for playground"
        assert "input_schema" in tool
        assert tool["namespace"] == "shared"

    def test_list_tools_requires_auth(self, client: TestClient):
        """Test listing tools requires authentication."""
        response = client.get("/api/playground/tools")
        assert response.status_code == 401


# ==================== Execute Tool Tests ====================


class TestPlaygroundExecute:
    """Tests for POST /api/playground/execute endpoint."""

    def test_execute_tool_direct(self, client: TestClient, auth_headers: dict):
        """Test executing a tool directly."""
        response = client.post(
            "/api/playground/execute",
            headers=auth_headers,
            json={
                "tool_name": "playground_test_tool",
                "arguments": {"value": "hello"},
                "transport": "direct",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["tool"] == "playground_test_tool"
        assert data["transport"] == "direct"
        assert data["result"]["echo"] == "hello"

    def test_execute_tool_mcp(self, client: TestClient, auth_headers: dict):
        """Test executing a tool via MCP format."""
        response = client.post(
            "/api/playground/execute",
            headers=auth_headers,
            json={
                "tool_name": "playground_test_tool",
                "arguments": {"value": "mcp_test"},
                "transport": "mcp",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["transport"] == "mcp"
        # MCP format wraps result in content array
        assert "content" in data["result"]

    def test_execute_tool_not_found(self, client: TestClient, auth_headers: dict):
        """Test executing non-existent tool."""
        response = client.post(
            "/api/playground/execute",
            headers=auth_headers,
            json={
                "tool_name": "nonexistent_tool",
                "arguments": {},
            },
        )

        assert response.status_code == 404

    def test_execute_tool_default_transport(self, client: TestClient, auth_headers: dict):
        """Test default transport is 'direct'."""
        response = client.post(
            "/api/playground/execute",
            headers=auth_headers,
            json={
                "tool_name": "playground_test_tool",
                "arguments": {},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["transport"] == "direct"

    def test_execute_tool_requires_auth(self, client: TestClient):
        """Test execution requires authentication."""
        response = client.post(
            "/api/playground/execute",
            json={"tool_name": "test", "arguments": {}},
        )
        assert response.status_code == 401


# ==================== MCP Test Endpoint ====================


class TestPlaygroundMCP:
    """Tests for POST /api/playground/mcp endpoint."""

    def test_mcp_initialize(self, client: TestClient, auth_headers: dict):
        """Test MCP initialize method."""
        response = client.post(
            "/api/playground/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        assert "protocolVersion" in data["result"]
        assert "capabilities" in data["result"]

    def test_mcp_tools_list(self, client: TestClient, auth_headers: dict):
        """Test MCP tools/list method."""
        response = client.post(
            "/api/playground/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 2
        assert "result" in data
        assert "tools" in data["result"]
        assert len(data["result"]["tools"]) >= 1

    def test_mcp_tools_call(self, client: TestClient, auth_headers: dict):
        """Test MCP tools/call method."""
        response = client.post(
            "/api/playground/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "playground_test_tool",
                    "arguments": {"value": "mcp_call"},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 3
        assert "result" in data
        assert "content" in data["result"]
        assert data["result"]["isError"] is False

    def test_mcp_tools_call_missing_name(self, client: TestClient, auth_headers: dict):
        """Test MCP tools/call without name returns error."""
        response = client.post(
            "/api/playground/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"arguments": {}},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602

    def test_mcp_unknown_method(self, client: TestClient, auth_headers: dict):
        """Test MCP with unknown method returns error."""
        response = client.post(
            "/api/playground/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "unknown/method",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32601
        assert "not found" in data["error"]["message"].lower()

    def test_mcp_tool_not_found(self, client: TestClient, auth_headers: dict):
        """Test MCP tools/call with non-existent tool."""
        response = client.post(
            "/api/playground/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "nonexistent_tool",
                    "arguments": {},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data

    def test_mcp_requires_auth(self, client: TestClient):
        """Test MCP endpoint requires authentication."""
        response = client.post(
            "/api/playground/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        )
        assert response.status_code == 401
