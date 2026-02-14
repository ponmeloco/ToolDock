"""
Integration tests for namespace-first URL routing.

Tests the /{namespace}/mcp and /{namespace}/openapi patterns,
reserved prefix guards, and global endpoint backward compatibility.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.transports.mcp_http_server import create_mcp_http_app, RESERVED_PREFIXES
from app.transports.openapi_server import create_openapi_app
from tests.utils.sync_client import SyncASGIClient


# ==================== Fixtures ====================


@pytest.fixture
def registry() -> ToolRegistry:
    """Fresh registry with test tools in multiple namespaces."""
    reset_registry()
    reg = ToolRegistry()

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
def mcp_client(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> SyncASGIClient:
    """MCP test client."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    app = create_mcp_http_app(registry)
    client = SyncASGIClient(app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def openapi_client(registry: ToolRegistry, monkeypatch: pytest.MonkeyPatch) -> SyncASGIClient:
    """OpenAPI test client."""
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    app = create_openapi_app(registry)
    client = SyncASGIClient(app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def auth_headers() -> dict:
    return {
        "Authorization": "Bearer test_token",
        "Accept": "application/json, text/event-stream",
    }


@pytest.fixture
def auth_headers_json() -> dict:
    return {"Authorization": "Bearer test_token"}


def _jsonrpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    """Build a JSON-RPC 2.0 request."""
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


# ==================== MCP: /{namespace}/mcp (new pattern) ====================


class TestMCPNamespaceFirst:
    """Tests for the new /{namespace}/mcp URL pattern."""

    def test_initialize(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {"name": "test"}})
        resp = mcp_client.post("/shared/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["protocolVersion"] == "2024-11-05"
        assert "shared" in data["result"]["serverInfo"]["name"]

    def test_tools_list(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post("/shared/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "greet" in names
        # team tools should NOT appear in shared namespace
        assert "multiply_ten" not in names

    def test_tools_call(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("tools/call", {"name": "greet", "arguments": {"name": "Test"}})
        resp = mcp_client.post("/shared/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        assert "Hello, Test!" in result["content"][0]["text"]

    def test_team_namespace(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post("/team/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "multiply_ten" in names
        assert "greet" not in names

    def test_unknown_namespace(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post("/nonexistent/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]["code"] == -32600
        assert "nonexistent" in data["error"]["message"]

    def test_sse_endpoint(self, mcp_client: SyncASGIClient, auth_headers: dict):
        headers = {**auth_headers, "Accept": "text/event-stream"}
        resp = mcp_client.get("/shared/mcp", headers=headers)
        assert resp.status_code == 200

    def test_sse_alias(self, mcp_client: SyncASGIClient, auth_headers: dict):
        headers = {**auth_headers, "Accept": "text/event-stream"}
        resp = mcp_client.get("/shared/mcp/sse", headers=headers)
        assert resp.status_code == 200

    def test_sse_alias_post(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post("/shared/mcp/sse", json=body, headers=auth_headers)
        assert resp.status_code == 200
        assert "tools" in resp.json()["result"]

    def test_delete_without_session_returns_400(self, mcp_client: SyncASGIClient, auth_headers: dict):
        resp = mcp_client.request("DELETE", "/shared/mcp", headers=auth_headers)
        assert resp.status_code == 400

    def test_info_endpoint(self, mcp_client: SyncASGIClient, auth_headers: dict):
        resp = mcp_client.get("/shared/mcp/info", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "shared"
        assert data["endpoint"] == "/shared/mcp"

    def test_no_deprecation_header(self, mcp_client: SyncASGIClient, auth_headers: dict):
        """New pattern should NOT have deprecation headers."""
        body = _jsonrpc("tools/list")
        resp = mcp_client.post("/shared/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        assert "deprecation" not in resp.headers


# ==================== MCP: Reserved Prefix Guard ====================


class TestMCPReservedPrefixes:
    """Ensure reserved prefixes return 404 for /{namespace}/mcp pattern."""

    @pytest.mark.parametrize("prefix", sorted(RESERVED_PREFIXES))
    def test_reserved_prefix_returns_404(
        self, mcp_client: SyncASGIClient, auth_headers: dict, prefix: str
    ):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post(f"/{prefix}/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 404


# ==================== OpenAPI: /{namespace}/openapi/* (new pattern) ====================


class TestOpenAPINamespaceFirst:
    """Tests for the new /{namespace}/openapi/* URL pattern."""

    def test_health(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.get("/shared/openapi/health")  # no auth needed
        # Actually our ns health doesn't require auth because it's a GET health
        # but it does validate namespace
        # Wait - it doesn't have auth dependency, but RESERVED check happens
        # Let's test: shared is not reserved
        # Actually looking at the code - ns_openapi_health does NOT have Depends(bearer_auth_dependency)
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "shared"
        assert data["status"] == "healthy"

    def test_list_tools(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.get("/shared/openapi/tools", headers=auth_headers_json)
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "shared"
        names = [t["name"] for t in data["tools"]]
        assert "greet" in names
        assert "multiply_ten" not in names

    def test_list_tools_team(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.get("/team/openapi/tools", headers=auth_headers_json)
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"] == "team"
        names = [t["name"] for t in data["tools"]]
        assert "multiply_ten" in names
        assert "greet" not in names

    def test_execute_tool(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.post(
            "/shared/openapi/tools/greet",
            json={"name": "Routing"},
            headers=auth_headers_json,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool"] == "greet"
        assert "Hello, Routing!" in str(data["result"])

    def test_execute_tool_wrong_namespace(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        """Tool from shared should not be callable via team namespace."""
        resp = openapi_client.post(
            "/team/openapi/tools/greet",
            json={"name": "Wrong"},
            headers=auth_headers_json,
        )
        assert resp.status_code == 404

    def test_unknown_namespace(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.get("/nonexistent/openapi/tools", headers=auth_headers_json)
        assert resp.status_code == 404

    def test_unknown_tool(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.post(
            "/shared/openapi/tools/nonexistent",
            json={},
            headers=auth_headers_json,
        )
        assert resp.status_code == 404


# ==================== OpenAPI: Reserved Prefix Guard ====================


class TestOpenAPIReservedPrefixes:
    """Ensure reserved prefixes return 404 for /{namespace}/openapi pattern."""

    @pytest.mark.parametrize("prefix", ["api", "docs", "assets", "static"])
    def test_reserved_prefix_returns_404(
        self, openapi_client: SyncASGIClient, auth_headers_json: dict, prefix: str
    ):
        resp = openapi_client.get(f"/{prefix}/openapi/tools", headers=auth_headers_json)
        assert resp.status_code == 404


# ==================== OpenAPI: Global routes still work ====================


class TestOpenAPIGlobalBackwardCompat:
    """Ensure global /tools and /health continue to work."""

    def test_global_health(self, openapi_client: SyncASGIClient):
        resp = openapi_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_global_tools_list(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.get("/tools", headers=auth_headers_json)
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        # Global list should include all tools from all namespaces
        names = [t["name"] for t in tools]
        assert "greet" in names
        assert "multiply_ten" in names

    def test_global_tool_execution(self, openapi_client: SyncASGIClient, auth_headers_json: dict):
        resp = openapi_client.post("/tools/greet", json={"name": "Global"}, headers=auth_headers_json)
        assert resp.status_code == 200
        assert "Hello, Global!" in str(resp.json()["result"])


# ==================== MCP: Global /mcp still works ====================


class TestMCPGlobalBackwardCompat:
    """Ensure global /mcp endpoint still works."""

    def test_global_tools_list(self, mcp_client: SyncASGIClient, auth_headers: dict):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post("/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        tools = resp.json()["result"]["tools"]
        names = [t["name"] for t in tools]
        assert "greet" in names
        assert "multiply_ten" in names

    def test_global_sse(self, mcp_client: SyncASGIClient, auth_headers: dict):
        headers = {**auth_headers, "Accept": "text/event-stream"}
        resp = mcp_client.get("/mcp", headers=headers)
        assert resp.status_code == 200


# ==================== MCP: Session Management (namespace routes) ====================


class TestMCPNamespaceSessionManagement:
    """Session management tests for namespace-scoped MCP endpoints."""

    def test_namespace_initialize_returns_session(
        self, mcp_client: SyncASGIClient, auth_headers: dict
    ):
        body = _jsonrpc("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {"name": "ns-test"}})
        resp = mcp_client.post("/shared/mcp", json=body, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers.get("Mcp-Session-Id")

    def test_namespace_delete_with_valid_session(
        self, mcp_client: SyncASGIClient, auth_headers: dict
    ):
        # Create session
        body = _jsonrpc("initialize", {"protocolVersion": "2024-11-05", "clientInfo": {"name": "del-test"}})
        resp = mcp_client.post("/shared/mcp", json=body, headers=auth_headers)
        session_id = resp.headers.get("Mcp-Session-Id")

        # Delete it
        resp = mcp_client.request(
            "DELETE", "/shared/mcp",
            headers={**auth_headers, "Mcp-Session-Id": session_id},
        )
        assert resp.status_code == 200

    def test_namespace_invalid_session_rejected(
        self, mcp_client: SyncASGIClient, auth_headers: dict
    ):
        body = _jsonrpc("tools/list")
        resp = mcp_client.post(
            "/shared/mcp",
            json=body,
            headers={**auth_headers, "Mcp-Session-Id": "invalid-id"},
        )
        assert resp.status_code == 404
