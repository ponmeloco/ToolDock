"""
Integration tests for MCP HTTP transport.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.transports.mcp_http_server import create_mcp_http_app


# ==================== Fixtures ====================


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh registry with test tools in multiple namespaces."""
    reset_registry()
    reg = ToolRegistry()

    # Tool in 'shared' namespace
    class GreetInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str = Field(default="World", description="Name to greet")

    async def greet_handler(payload: GreetInput) -> str:
        return f"Hello, {payload.name}!"

    GreetInput.model_rebuild(force=True)
    reg.register(
        ToolDefinition(
            name="greet",
            description="Greet someone",
            input_model=GreetInput,
            handler=greet_handler,
        ),
        namespace="shared",
    )

    # Tool in 'team' namespace
    class TeamInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: int = Field(default=1, description="A number")

    async def team_handler(payload: TeamInput) -> int:
        return payload.value * 10

    TeamInput.model_rebuild(force=True)
    reg.register(
        ToolDefinition(
            name="multiply_ten",
            description="Multiply by 10",
            input_model=TeamInput,
            handler=team_handler,
        ),
        namespace="team",
    )

    yield reg
    reset_registry()


@pytest.fixture
def client(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client with auth enabled."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    app = create_mcp_http_app(registry)
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
        assert data["transport"] == "mcp-streamable-http"

    def test_health_includes_tool_stats(self, client: TestClient):
        """Test health endpoint includes tool stats."""
        response = client.get("/health")

        data = response.json()
        assert "tools" in data
        assert data["tools"]["total"] >= 2

    def test_strict_get_mcp_returns_405(self, client: TestClient, auth_headers: dict):
        """GET /mcp is not used in strict mode."""
        response = client.get("/mcp", headers=auth_headers)
        assert response.status_code == 405

    def test_strict_get_mcp_namespace_returns_405(self, client: TestClient, auth_headers: dict):
        """GET /mcp/{namespace} is not used in strict mode."""
        response = client.get("/mcp/shared", headers=auth_headers)
        assert response.status_code == 405


# ==================== Initialize Tests ====================


class TestMCPInitialize:
    """Tests for MCP initialize method."""

    def test_initialize_global_endpoint(
        self, client: TestClient, auth_headers: dict
    ):
        """Test initialize on global /mcp endpoint."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    "capabilities": {},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == 1
        assert "result" in data
        assert "protocolVersion" in data["result"]
        assert "serverInfo" in data["result"]

    def test_initialize_namespace_endpoint(
        self, client: TestClient, auth_headers: dict
    ):
        """Test initialize on namespace-specific endpoint."""
        response = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "clientInfo": {"name": "test-client"},
                    "capabilities": {},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["serverInfo"]["name"].endswith("/shared")

    def test_initialize_invalid_protocol_version(
        self, client: TestClient, auth_headers: dict
    ):
        """Test initialize rejects unsupported protocol versions."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "1900-01-01",
                    "clientInfo": {"name": "test-client"},
                    "capabilities": {},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32602


# ==================== List Tools Tests ====================


class TestMCPListTools:
    """Tests for MCP tools/list method."""

    def test_list_tools_global(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing all tools via global endpoint."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 200
        data = response.json()
        tools = data["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        # Should see tools from both namespaces
        assert "greet" in tool_names
        assert "multiply_ten" in tool_names

    def test_list_tools_namespace_specific(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing tools for a specific namespace."""
        response = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 200
        data = response.json()
        tools = data["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        # Should only see 'shared' namespace tools
        assert "greet" in tool_names
        assert "multiply_ten" not in tool_names

    def test_list_tools_includes_schema(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that tools include input schemas."""
        response = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        data = response.json()
        greet_tool = next(t for t in data["result"]["tools"] if t["name"] == "greet")

        assert "inputSchema" in greet_tool
        assert greet_tool["inputSchema"]["type"] == "object"


# ==================== Call Tool Tests ====================


class TestMCPCallTool:
    """Tests for MCP tools/call method."""

    def test_call_tool_success(
        self, client: TestClient, auth_headers: dict
    ):
        """Test successful tool execution."""
        response = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "greet",
                    "arguments": {"name": "Alice"},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["isError"] is False
        content = data["result"]["content"][0]
        assert content["type"] == "text"
        assert "Hello, Alice!" in content["text"]

    def test_call_tool_with_defaults(
        self, client: TestClient, auth_headers: dict
    ):
        """Test tool call with default arguments."""
        response = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "greet",
                    "arguments": {},
                },
            },
        )

        data = response.json()
        assert "Hello, World!" in data["result"]["content"][0]["text"]

    def test_call_tool_wrong_namespace(
        self, client: TestClient, auth_headers: dict
    ):
        """Test calling a tool from wrong namespace fails."""
        # Try to call 'multiply_ten' (team namespace) from 'shared' endpoint
        response = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "multiply_ten",
                    "arguments": {"value": 5},
                },
            },
        )

        data = response.json()
        assert "error" in data
        assert "not found" in data["error"]["message"].lower()

    def test_call_tool_global_endpoint(
        self, client: TestClient, auth_headers: dict
    ):
        """Test calling any tool from global endpoint."""
        # Can call tools from any namespace via global /mcp
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "multiply_ten",
                    "arguments": {"value": 5},
                },
            },
        )

        data = response.json()
        assert data["result"]["isError"] is False
        assert "50" in data["result"]["content"][0]["text"]


# ==================== Namespace Routing Tests ====================


class TestNamespaceRouting:
    """Tests for namespace-based routing."""

    def test_list_namespaces(
        self, client: TestClient, auth_headers: dict
    ):
        """Test listing available namespaces."""
        response = client.get("/mcp/namespaces", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "shared" in data["namespaces"]
        assert "team" in data["namespaces"]

    def test_mcp_info_global(
        self, client: TestClient, auth_headers: dict
    ):
        """Test non-standard global discovery endpoint."""
        response = client.get("/mcp/info", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["protocol"] == "MCP"
        assert "namespace_endpoints" in data

    def test_namespace_info(
        self, client: TestClient, auth_headers: dict
    ):
        """Test getting namespace info via non-standard endpoint."""
        response = client.get("/mcp/shared/info", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["namespace"] == "shared"
        assert data["protocol"] == "MCP"

    def test_unknown_namespace(
        self, client: TestClient, auth_headers: dict
    ):
        """Test accessing unknown namespace info returns 404."""
        response = client.get("/mcp/nonexistent/info", headers=auth_headers)

        assert response.status_code == 404
        data = response.json()
        assert "unknown namespace" in data["error"].lower()


# ==================== Authentication Tests ====================


class TestMCPAuthentication:
    """Tests for MCP authentication."""

    def test_mcp_requires_auth(self, client: TestClient):
        """Test that MCP endpoints require authentication."""
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 401

    def test_namespaces_requires_auth(self, client: TestClient):
        """Test that namespace listing requires auth."""
        response = client.get("/mcp/namespaces")

        assert response.status_code == 401

    def test_auth_disabled_allows_access(
        self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that disabling auth allows access."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        app = create_mcp_http_app(registry)
        client = TestClient(app)

        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 200

    def test_origin_rejected(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        """Invalid Origin header is rejected."""
        monkeypatch.setenv("CORS_ORIGINS", "http://allowed.example")
        response = client.post(
            "/mcp",
            headers={**auth_headers, "Origin": "http://blocked.example"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
            },
        )
        assert response.status_code == 403

    def test_protocol_header_rejected(self, client: TestClient, auth_headers: dict):
        """Unsupported MCP-Protocol-Version header is rejected."""
        response = client.post(
            "/mcp",
            headers={**auth_headers, "MCP-Protocol-Version": "1900-01-01"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
            },
        )
        assert response.status_code == 400


# ==================== JSON-RPC Error Handling Tests ====================


class TestJSONRPCErrors:
    """Tests for JSON-RPC error handling."""

    def test_invalid_jsonrpc_version(
        self, client: TestClient, auth_headers: dict
    ):
        """Test error for invalid JSON-RPC version."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "1.0",  # Wrong version
                "id": 1,
                "method": "tools/list",
            },
        )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32600

    def test_missing_method(
        self, client: TestClient, auth_headers: dict
    ):
        """Test error for missing method."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
            },
        )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32600

    def test_unknown_method(
        self, client: TestClient, auth_headers: dict
    ):
        """Test error for unknown method."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "unknown/method",
            },
        )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32601

    def test_invalid_json(
        self, client: TestClient, auth_headers: dict
    ):
        """Test error for invalid JSON."""
        headers = {"Content-Type": "application/json", **auth_headers}
        response = client.post(
            "/mcp",
            headers=headers,
            content="not valid json{",
        )

        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32700  # Parse error


# ==================== Ping Tests ====================


class TestMCPPing:
    """Tests for MCP ping method."""

    def test_ping(
        self, client: TestClient, auth_headers: dict
    ):
        """Test ping returns empty result."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
                "params": {},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"] == {}


# ==================== Notification Tests ====================


class TestMCPNotifications:
    """Tests for MCP notifications (no response expected)."""

    def test_initialized_notification(
        self, client: TestClient, auth_headers: dict
    ):
        """Test initialized notification returns 202."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                # No "id" field makes this a notification
                "method": "initialized",
                "params": {},
            },
        )

        assert response.status_code == 202

    def test_notifications_initialized_supported(
        self, client: TestClient, auth_headers: dict
    ):
        """notifications/initialized is supported."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )

        assert response.status_code == 202
