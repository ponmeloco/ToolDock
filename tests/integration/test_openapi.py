"""
Integration tests for OpenAPI transport.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.transports.openapi_server import create_openapi_app


# ==================== Fixtures ====================


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh registry with test tools."""
    reset_registry()
    reg = ToolRegistry()

    class EchoInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        message: str = Field(default="hello", description="Message to echo")

    async def echo_handler(payload: EchoInput) -> str:
        return f"Echo: {payload.message}"

    EchoInput.model_rebuild(force=True)
    reg.register(
        ToolDefinition(
            name="echo",
            description="Echoes a message",
            input_model=EchoInput,
            handler=echo_handler,
        ),
        namespace="test",
    )

    class AddInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        a: int = Field(description="First number")
        b: int = Field(description="Second number")

    async def add_handler(payload: AddInput) -> int:
        return payload.a + payload.b

    AddInput.model_rebuild(force=True)
    reg.register(
        ToolDefinition(
            name="add",
            description="Adds two numbers",
            input_model=AddInput,
            handler=add_handler,
        ),
        namespace="test",
    )

    yield reg
    reset_registry()


@pytest.fixture
def client(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client with auth enabled."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    app = create_openapi_app(registry)
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    """Auth headers for requests."""
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
        assert data["transport"] == "openapi"

    def test_health_includes_stats(self, client: TestClient):
        """Test health endpoint includes tool stats."""
        response = client.get("/health")

        data = response.json()
        assert "tools" in data
        assert data["tools"]["native"] >= 2  # Our test tools


# ==================== Authentication Tests ====================


class TestAuthentication:
    """Tests for authentication behavior."""

    def test_list_tools_requires_auth(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that /tools requires authentication."""
        response = client.get("/tools")

        assert response.status_code == 401

    def test_list_tools_with_valid_auth(
        self, client: TestClient, auth_headers: dict
    ):
        """Test /tools works with valid auth."""
        response = client.get("/tools", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data

    def test_invalid_token_rejected(self, client: TestClient):
        """Test invalid token is rejected."""
        headers = {"Authorization": "Bearer wrong_token"}

        response = client.get("/tools", headers=headers)

        assert response.status_code == 401

    def test_missing_bearer_prefix_rejected(self, client: TestClient):
        """Test missing Bearer prefix is rejected."""
        headers = {"Authorization": "test_token"}

        response = client.get("/tools", headers=headers)

        assert response.status_code == 401

    def test_auth_disabled_allows_access(
        self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that disabling auth allows access without token."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        app = create_openapi_app(registry)
        client = TestClient(app)

        response = client.get("/tools")

        assert response.status_code == 200


# ==================== Tool Listing Tests ====================


class TestToolListing:
    """Tests for tool listing endpoint."""

    def test_list_tools_returns_all_tools(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that all registered tools are listed."""
        response = client.get("/tools", headers=auth_headers)

        data = response.json()
        tool_names = [t["name"] for t in data["tools"]]

        assert "echo" in tool_names
        assert "add" in tool_names

    def test_list_tools_includes_schema(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that tools include input schemas."""
        response = client.get("/tools", headers=auth_headers)

        data = response.json()
        echo_tool = next(t for t in data["tools"] if t["name"] == "echo")

        assert "input_schema" in echo_tool
        assert echo_tool["input_schema"]["type"] == "object"

    def test_list_tools_includes_descriptions(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that tools include descriptions."""
        response = client.get("/tools", headers=auth_headers)

        data = response.json()
        echo_tool = next(t for t in data["tools"] if t["name"] == "echo")

        assert echo_tool["description"] == "Echoes a message"


# ==================== Tool Execution Tests ====================


class TestToolExecution:
    """Tests for tool execution endpoints."""

    def test_call_tool_success(
        self, client: TestClient, auth_headers: dict
    ):
        """Test successful tool execution."""
        response = client.post(
            "/tools/echo",
            headers=auth_headers,
            json={"message": "Hello World"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tool"] == "echo"
        assert data["result"] == "Echo: Hello World"

    def test_call_tool_with_defaults(
        self, client: TestClient, auth_headers: dict
    ):
        """Test tool execution with default values."""
        response = client.post(
            "/tools/echo",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"] == "Echo: hello"

    def test_call_add_tool(
        self, client: TestClient, auth_headers: dict
    ):
        """Test calling the add tool."""
        response = client.post(
            "/tools/add",
            headers=auth_headers,
            json={"a": 5, "b": 3},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"] == 8

    def test_call_nonexistent_tool(
        self, client: TestClient, auth_headers: dict
    ):
        """Test calling a tool that doesn't exist."""
        response = client.post(
            "/tools/nonexistent",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 404

    def test_call_tool_requires_auth(
        self, client: TestClient
    ):
        """Test that tool execution requires auth."""
        response = client.post("/tools/echo", json={"message": "test"})

        assert response.status_code == 401

    def test_call_tool_invalid_payload(
        self, client: TestClient, auth_headers: dict
    ):
        """Test tool execution with invalid payload type."""
        response = client.post(
            "/tools/add",
            headers=auth_headers,
            json={"a": "not_a_number", "b": 3},
        )

        assert response.status_code == 422  # Validation error

    def test_call_tool_extra_field_rejected(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that extra fields are rejected (extra=forbid)."""
        response = client.post(
            "/tools/echo",
            headers=auth_headers,
            json={"message": "hello", "extra_field": "bad"},
        )

        assert response.status_code == 422


# ==================== Error Handling Tests ====================


class TestErrorHandling:
    """Tests for error handling."""

    def test_tool_not_found_error(
        self, client: TestClient, auth_headers: dict
    ):
        """Test error response for nonexistent tool."""
        response = client.post(
            "/tools/does_not_exist",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_validation_error_format(
        self, client: TestClient, auth_headers: dict
    ):
        """Test validation error response format."""
        response = client.post(
            "/tools/add",
            headers=auth_headers,
            json={"a": "invalid"},  # Should be int
        )

        assert response.status_code == 422
        data = response.json()
        assert "error" in data
