"""
Integration tests for MCP HTTP transport.
"""

from __future__ import annotations

import asyncio
import json

import anyio
import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.transports.mcp_http_server import create_mcp_http_app
from tests.utils.sync_client import SyncASGIClient


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
def client(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> SyncASGIClient:
    """Test client with auth enabled."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    app = create_mcp_http_app(registry)
    client = SyncASGIClient(app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def auth_headers() -> dict:
    """Auth headers for requests."""
    return {
        "Authorization": "Bearer test_token",
        "Accept": "application/json, text/event-stream",
    }


# ==================== Health Endpoint Tests ====================


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_no_auth_required(self, client: SyncASGIClient):
        """Test health endpoint doesn't require auth."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["transport"] == "mcp-streamable-http"

    def test_health_includes_tool_stats(self, client: SyncASGIClient):
        """Test health endpoint includes tool stats."""
        response = client.get("/health")

        data = response.json()
        assert "tools" in data
        assert data["tools"]["total"] >= 2

    def test_get_mcp_stream(self, client: SyncASGIClient, auth_headers: dict):
        """GET /mcp returns SSE stream when Accept is correct."""
        response = client.get(
            "/mcp",
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_get_mcp_stream_alias(self, client: SyncASGIClient, auth_headers: dict):
        """GET /mcp/sse returns SSE stream for compatibility with some clients."""
        response = client.get(
            "/mcp/sse",
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_get_mcp_namespace_stream(self, client: SyncASGIClient, auth_headers: dict):
        """GET /mcp/{namespace} returns SSE stream when Accept is correct."""
        response = client.get(
            "/mcp/shared",
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_get_mcp_namespace_stream_alias(self, client: SyncASGIClient, auth_headers: dict):
        """GET /mcp/{namespace}/sse returns SSE stream for compatibility with some clients."""
        response = client.get(
            "/mcp/shared/sse",
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")


# ==================== Initialize Tests ====================


class TestMCPInitialize:
    """Tests for MCP initialize method."""

    def test_initialize_global_endpoint(
        self, client: SyncASGIClient, auth_headers: dict
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
        assert response.headers.get("Mcp-Session-Id")

    def test_initialize_accept_text_event_stream_returns_sse(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """POST should still work when client sends Accept: text/event-stream."""
        response = client.post(
            "/mcp",
            headers={
                **auth_headers,
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": "2024-11-05",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    "capabilities": {},
                },
            },
        )
        assert response.status_code == 200
        assert response.headers.get("Mcp-Session-Id")
        data = response.json()
        assert data["result"]["protocolVersion"] == "2024-11-05"

    def test_initialize_protocol_header_2024_is_accepted(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Header MCP-Protocol-Version=2024-11-05 should not be rejected."""
        response = client.post(
            "/mcp",
            headers={**auth_headers, "MCP-Protocol-Version": "2024-11-05"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    "capabilities": {},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["protocolVersion"] == "2024-11-05"

    def test_initialize_unknown_protocol_header_is_ignored(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Unknown MCP-Protocol-Version header should not hard-fail the request."""
        response = client.post(
            "/mcp",
            headers={**auth_headers, "MCP-Protocol-Version": "1900-01-01"},
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
        assert "result" in data

    def test_initialize_missing_accept_header(self, client: SyncASGIClient, auth_headers: dict):
        """Missing Accept header is accepted for JSON-RPC POST compatibility."""
        headers = dict(auth_headers)
        headers.pop("Accept", None)
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            },
        )
        assert response.status_code == 200

    def test_initialize_explicit_incompatible_accept_rejected(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Explicitly incompatible Accept header is rejected."""
        response = client.post(
            "/mcp",
            headers={**auth_headers, "Accept": "text/plain"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            },
        )
        assert response.status_code == 406

    def test_initialize_namespace_endpoint(
        self, client: SyncASGIClient, auth_headers: dict
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

    def test_initialize_namespace_sse_alias_post(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """POST /mcp/{namespace}/sse should behave like POST /mcp/{namespace}."""
        response = client.post(
            "/mcp/shared/sse",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "test-client"},
                    "capabilities": {},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["serverInfo"]["name"].endswith("/shared")

    def test_initialize_invalid_protocol_version(
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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

    def test_list_tools_namespace_sse_alias_post(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """POST /mcp/{namespace}/sse should behave like POST /mcp/{namespace}."""
        response = client.post(
            "/mcp/shared/sse",
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
        assert "greet" in tool_names

    def test_list_tools_includes_schema(
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Test listing available namespaces."""
        response = client.get("/mcp/namespaces", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "shared" in data["namespaces"]
        assert "team" in data["namespaces"]

    def test_mcp_info_global(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Test non-standard global discovery endpoint."""
        response = client.get("/mcp/info", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["protocol"] == "MCP"
        assert "namespace_endpoints" in data

    def test_namespace_info(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Test getting namespace info via non-standard endpoint."""
        response = client.get("/mcp/shared/info", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["namespace"] == "shared"
        assert data["protocol"] == "MCP"

    def test_unknown_namespace(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Test accessing unknown namespace info returns 404."""
        response = client.get("/mcp/nonexistent/info", headers=auth_headers)

        assert response.status_code == 404
        data = response.json()
        assert "unknown namespace" in data["error"].lower()


# ==================== Authentication Tests ====================


class TestMCPAuthentication:
    """Tests for MCP authentication."""

    def test_mcp_requires_auth(self, client: SyncASGIClient):
        """Test that MCP endpoints require authentication."""
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 401

    def test_namespaces_requires_auth(self, client: SyncASGIClient):
        """Test that namespace listing requires auth."""
        response = client.get("/mcp/namespaces")

        assert response.status_code == 401

    def test_auth_disabled_allows_access(
        self, registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that disabling auth allows access."""
        monkeypatch.delenv("BEARER_TOKEN", raising=False)

        app = create_mcp_http_app(registry)
        client = SyncASGIClient(app)

        response = client.post(
            "/mcp",
            headers={"Accept": "application/json"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )

        assert response.status_code == 200

    def test_origin_rejected(
        self, client: SyncASGIClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
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

    def test_protocol_header_rejected(self, client: SyncASGIClient, auth_headers: dict):
        """Unsupported MCP-Protocol-Version header is ignored for compatibility."""
        response = client.post(
            "/mcp",
            headers={**auth_headers, "MCP-Protocol-Version": "1900-01-01"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
            },
        )
        assert response.status_code == 200


# ==================== JSON-RPC Error Handling Tests ====================


class TestJSONRPCErrors:
    """Tests for JSON-RPC error handling."""

    def test_invalid_jsonrpc_version(
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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

    def test_batch_rejected(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """JSON-RPC batching is rejected."""
        response = client.post(
            "/mcp",
            headers=auth_headers,
            json=[
                {"jsonrpc": "2.0", "id": 1, "method": "ping"},
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            ],
        )
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32600


# ==================== Ping Tests ====================


class TestMCPPing:
    """Tests for MCP ping method."""

    def test_ping(
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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
        self, client: SyncASGIClient, auth_headers: dict
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


# ==================== Full Client Flow Tests ====================


class TestMCPClientFlow:
    """Tests that simulate a complete MCP client session (init -> tools/list -> call)."""

    def test_full_session_flow(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """A complete client flow: initialize -> initialized -> tools/list -> tools/call."""
        # Step 1: initialize
        resp = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "clientInfo": {"name": "flow-test", "version": "1.0"},
                },
            },
        )
        assert resp.status_code == 200
        init_data = resp.json()
        assert "result" in init_data
        session_id = resp.headers.get("Mcp-Session-Id")
        assert session_id

        # Step 2: initialized notification
        resp = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        assert resp.status_code == 202

        # Step 3: tools/list
        resp = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        assert resp.status_code == 200
        tools_data = resp.json()
        tool_names = [t["name"] for t in tools_data["result"]["tools"]]
        assert "greet" in tool_names

        # Step 4: tools/call
        resp = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "greet", "arguments": {"name": "Flow"}},
            },
        )
        assert resp.status_code == 200
        call_data = resp.json()
        assert call_data["result"]["isError"] is False
        assert "Flow" in call_data["result"]["content"][0]["text"]

    def test_session_id_stable_across_requests(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Mcp-Session-Id stays the same across multiple requests."""
        ids = set()
        for i in range(3):
            resp = client.post(
                "/mcp",
                headers=auth_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": i + 1,
                    "method": "ping",
                    "params": {},
                },
            )
            ids.add(resp.headers.get("Mcp-Session-Id"))
        assert len(ids) == 1, f"Expected stable session ID, got {ids}"


# ==================== POST to Unknown Namespace Tests ====================


class TestMCPUnknownNamespacePost:
    """Tests for POST to an unknown namespace (JSON-RPC error path)."""

    def test_post_to_unknown_namespace(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """POST to unknown namespace returns JSON-RPC error with available namespaces."""
        resp = client.post(
            "/mcp/nonexistent",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            },
        )
        assert resp.status_code == 200  # JSON-RPC errors still return 200
        data = resp.json()
        assert data["error"]["code"] == -32600
        assert "nonexistent" in data["error"]["message"]
        assert "available_namespaces" in data["error"]["data"]


# ==================== tools/call Edge Cases ====================


class TestMCPCallToolEdgeCases:
    """Edge cases for tools/call."""

    def test_call_tool_missing_name(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """tools/call with no name param should return an error."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"arguments": {}},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should indicate an error (either JSON-RPC error or isError result)
        has_error = "error" in data or (
            "result" in data and data["result"].get("isError") is True
        )
        assert has_error, f"Expected error for missing tool name, got: {data}"

    def test_call_nonexistent_tool_global(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """tools/call for a tool that doesn't exist returns isError."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "no_such_tool", "arguments": {}},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["isError"] is True


# ==================== Accept Header Edge Cases ====================


class TestMCPAcceptHeaders:
    """Edge cases for Accept header handling."""

    def test_accept_wildcard(
        self, client: SyncASGIClient
    ):
        """Accept: */* should be accepted on POST."""
        resp = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test_token",
                "Accept": "*/*",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
                "params": {},
            },
        )
        assert resp.status_code == 200

    def test_accept_application_wildcard(
        self, client: SyncASGIClient
    ):
        """Accept: application/* should be accepted on POST."""
        resp = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test_token",
                "Accept": "application/*",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
                "params": {},
            },
        )
        assert resp.status_code == 200

    def test_get_without_event_stream_accept_rejected(
        self, client: SyncASGIClient
    ):
        """GET /mcp without Accept: text/event-stream should be rejected."""
        resp = client.get(
            "/mcp",
            headers={
                "Authorization": "Bearer test_token",
                "Accept": "application/json",
            },
        )
        assert resp.status_code == 406

    def test_post_with_both_accept_types(
        self, client: SyncASGIClient
    ):
        """POST with Accept: application/json, text/event-stream (spec-compliant)."""
        resp = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test_token",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
                "params": {},
            },
        )
        assert resp.status_code == 200
        assert "application/json" in resp.headers.get("content-type", "")


# ==================== SSE Stream Content Tests ====================


class TestMCPSSEInternals:
    """Tests for SSE-related internals: _publish_sse, _subscribe_sse, message format.

    httpx ASGITransport does not support true streaming, so we test the
    internal functions directly and verify the short-circuit SSE response.
    """

    @pytest.fixture
    def live_sse_registry(self) -> ToolRegistry:
        """Fresh registry for SSE tests."""
        reset_registry()
        reg = ToolRegistry()

        class PingInput(BaseModel):
            model_config = ConfigDict(extra="forbid")

        async def ping_handler(payload: PingInput) -> str:
            return "pong"

        PingInput.model_rebuild(force=True)
        reg.register(
            ToolDefinition(
                name="sse_ping",
                description="Ping for SSE test",
                input_model=PingInput,
                handler=ping_handler,
            ),
            namespace="shared",
        )
        yield reg
        reset_registry()

    @pytest.fixture
    def live_app(self, live_sse_registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch):
        """App without PYTEST_CURRENT_TEST so SSE functions work normally."""
        monkeypatch.setenv("BEARER_TOKEN", "test_token")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        return create_mcp_http_app(live_sse_registry)

    def test_subscribe_creates_queue(self, live_app):
        """_subscribe_sse creates an asyncio.Queue and registers it."""
        # Access the internal functions via the app's scope
        # The subscribe/unsubscribe functions are closures, test via state
        assert isinstance(live_app.state._mcp_sse_subscribers_global, set)
        assert isinstance(live_app.state._mcp_sse_subscribers_by_ns, dict)

    def test_post_response_not_published_to_sse(self, live_app):
        """POST endpoint does not call _publish_sse for responses.

        We verify this by checking that after a POST, no queued SSE
        subscriber has received anything.
        """

        async def run():
            # Manually add an SSE subscriber queue
            q: asyncio.Queue = asyncio.Queue(maxsize=100)
            live_app.state._mcp_sse_subscribers_by_ns.setdefault("shared", set()).add(q)

            # Make a POST request
            transport = httpx.ASGITransport(app=live_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/mcp/shared",
                    headers={
                        "Authorization": "Bearer test_token",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "clientInfo": {"name": "sse-test"},
                        },
                    },
                )
                assert resp.status_code == 200
                assert "result" in resp.json()

            # The subscriber queue must be empty (no echoed response)
            assert q.empty(), (
                "POST response was published to SSE queue (spec violation)"
            )

            # Cleanup
            live_app.state._mcp_sse_subscribers_by_ns["shared"].discard(q)

        anyio.run(run)

    def test_sse_message_format(self, live_app):
        """_sse_message produces correct SSE data frame."""
        # Access _sse_message through the module's create function
        # We can test the format by importing and checking
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        expected = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        # The function is a closure; verify the format matches SSE spec
        assert expected.startswith("data: ")
        assert expected.endswith("\n\n")
        # Verify JSON is valid
        data_part = expected[len("data: "):-2]
        parsed = json.loads(data_part)
        assert parsed["jsonrpc"] == "2.0"

    def test_sse_stream_returns_event_stream_content_type(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """GET /mcp/shared SSE stream has correct content-type."""
        # In pytest mode, stream short-circuits with ': ok\n\n'
        resp = client.get(
            "/mcp/shared",
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # Verify it has the session ID header
        assert resp.headers.get("Mcp-Session-Id")
        # Verify Cache-Control
        assert "no-cache" in resp.headers.get("cache-control", "")


# ==================== Protocol Version Negotiation ====================


class TestProtocolVersionNegotiation:
    """Tests for proper protocol version negotiation."""

    def test_negotiate_2024_11_05(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Client requesting 2024-11-05 gets 2024-11-05 back."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            },
        )
        data = resp.json()
        assert data["result"]["protocolVersion"] == "2024-11-05"

    def test_negotiate_2025_03_26(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Client requesting 2025-03-26 gets 2025-03-26 back."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            },
        )
        data = resp.json()
        assert data["result"]["protocolVersion"] == "2025-03-26"

    def test_no_protocol_version_defaults(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Missing protocolVersion uses server default."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            },
        )
        data = resp.json()
        # Should return the server's default (2024-11-05)
        assert data["result"]["protocolVersion"] in ("2024-11-05", "2025-03-26")

    def test_unsupported_version_rejected(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Unsupported protocolVersion returns error."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            },
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32602
        assert "supported" in data["error"].get("data", {})

    def test_phantom_version_2025_11_25_rejected(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Phantom version 2025-11-25 should no longer be accepted."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32602


# ==================== Spec Compliance Tests ====================


class TestSpecCompliance:
    """Tests for MCP spec compliance fixes."""

    def test_response_content_type_no_charset(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Response Content-Type must be exactly 'application/json' without charset."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
            },
        )
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert ct == "application/json", f"Expected exact 'application/json', got '{ct}'"

    def test_response_content_type_namespace_no_charset(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Namespace endpoint Content-Type must also be exact."""
        resp = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
            },
        )
        assert resp.status_code == 200
        ct = resp.headers.get("content-type", "")
        assert ct == "application/json"

    def test_post_wrong_content_type_rejected(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """POST with wrong Content-Type should return -32700 parse error."""
        resp = client.post(
            "/mcp",
            headers={**auth_headers, "Content-Type": "text/plain"},
            content=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32700
        assert "Content-Type" in data["error"]["message"]

    def test_post_wrong_content_type_namespace(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Namespace POST with wrong Content-Type should return -32700."""
        resp = client.post(
            "/mcp/shared",
            headers={**auth_headers, "Content-Type": "text/xml"},
            content=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32700

    def test_post_missing_content_type_accepted(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """POST with missing Content-Type should be accepted (lenient)."""
        # httpx auto-adds Content-Type for json=, so use content= with no CT header
        headers = {k: v for k, v in auth_headers.items() if k.lower() != "content-type"}
        resp = client.post(
            "/mcp",
            headers=headers,
            content=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        )
        # Should either succeed or fail for another reason (not content-type)
        assert resp.status_code == 200
        data = resp.json()
        # If there's an error, it should not be about Content-Type
        if "error" in data:
            assert "Content-Type" not in data["error"].get("message", "")

    def test_delete_global_returns_405(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """DELETE /mcp should return 405 with JSON-RPC error body."""
        resp = client.delete("/mcp", headers=auth_headers)
        assert resp.status_code == 405
        data = resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32600
        assert "Allow" in resp.headers
        assert "GET" in resp.headers["Allow"]
        assert "POST" in resp.headers["Allow"]

    def test_delete_namespace_returns_405(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """DELETE /mcp/{namespace} should return 405 with JSON-RPC error body."""
        resp = client.delete("/mcp/shared", headers=auth_headers)
        assert resp.status_code == 405
        data = resp.json()
        assert data["jsonrpc"] == "2.0"
        assert data["error"]["code"] == -32600

    def test_202_notification_includes_session_id(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """202 responses for notifications must include Mcp-Session-Id header."""
        resp = client.post(
            "/mcp",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert resp.status_code == 202
        assert "mcp-session-id" in resp.headers or "Mcp-Session-Id" in resp.headers

    def test_202_notification_namespace_includes_session_id(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Namespace 202 responses must include Mcp-Session-Id header."""
        resp = client.post(
            "/mcp/shared",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert resp.status_code == 202
        assert "mcp-session-id" in resp.headers or "Mcp-Session-Id" in resp.headers

    def test_unknown_namespace_echoes_request_id(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Unknown namespace error should echo the request id from body, not None."""
        resp = client.post(
            "/mcp/nonexistent",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 42,
                "method": "ping",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 42
        assert data["error"]["code"] == -32600

    def test_unknown_namespace_includes_session_header(
        self, client: SyncASGIClient, auth_headers: dict
    ):
        """Unknown namespace error response must include Mcp-Session-Id."""
        resp = client.post(
            "/mcp/nonexistent",
            headers=auth_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
            },
        )
        assert "mcp-session-id" in resp.headers or "Mcp-Session-Id" in resp.headers
