"""
Integration tests for Admin API endpoints.

Tests:
- System health aggregation
- Log viewing
- System info
- Tool content update (PUT)
"""

import pytest

from tests.utils.sync_client import SyncASGIClient


class TestAdminHealth:
    """Tests for /api/admin/health endpoint."""

    def test_health_requires_auth(self, web_client: SyncASGIClient):
        """Health endpoint requires authentication."""
        response = web_client.get("/api/admin/health")
        assert response.status_code == 401

    def test_health_returns_services(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Health endpoint returns service statuses."""
        response = web_client.get("/api/admin/health", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "timestamp" in data
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_health_includes_web_service(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Health includes web service which is always healthy."""
        response = web_client.get("/api/admin/health", headers=auth_headers)
        data = response.json()

        web_service = next(
            (s for s in data["services"] if s["name"] == "web"), None
        )
        assert web_service is not None
        assert web_service["status"] == "healthy"


class TestAdminLogs:
    """Tests for /api/admin/logs endpoint."""

    def test_logs_requires_auth(self, web_client: SyncASGIClient):
        """Logs endpoint requires authentication."""
        response = web_client.get("/api/admin/logs")
        assert response.status_code == 401

    def test_logs_returns_entries(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Logs endpoint returns log entries."""
        response = web_client.get("/api/admin/logs", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "logs" in data
        assert "total" in data
        assert "has_more" in data
        assert isinstance(data["logs"], list)

    def test_logs_respects_limit(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Logs endpoint respects limit parameter."""
        response = web_client.get(
            "/api/admin/logs?limit=5", headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data["logs"]) <= 5

    def test_logs_filters_by_level(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Logs endpoint filters by level."""
        response = web_client.get(
            "/api/admin/logs?level=ERROR", headers=auth_headers
        )
        assert response.status_code == 200

        data = response.json()
        # All returned logs should be ERROR level (if any)
        for log in data["logs"]:
            assert log["level"] == "ERROR"


class TestAdminInfo:
    """Tests for /api/admin/info endpoint."""

    def test_info_requires_auth(self, web_client: SyncASGIClient):
        """Info endpoint requires authentication."""
        response = web_client.get("/api/admin/info")
        assert response.status_code == 401

    def test_info_returns_system_info(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Info endpoint returns system information."""
        response = web_client.get("/api/admin/info", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "version" in data
        assert "python_version" in data
        assert "data_dir" in data
        assert "namespaces" in data
        assert "environment" in data
        assert "mcp_protocol_version" in data["environment"]
        assert "mcp_protocol_versions" in data["environment"]
        assert "host_data_dir" in data["environment"]

    def test_info_includes_namespaces(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Info endpoint includes namespace list."""
        response = web_client.get("/api/admin/info", headers=auth_headers)
        data = response.json()

        assert isinstance(data["namespaces"], list)


class TestToolUpdate:
    """Tests for PUT /api/folders/{ns}/tools/{file} endpoint."""

    def test_update_requires_auth(self, web_client: SyncASGIClient):
        """Update endpoint requires authentication."""
        response = web_client.put(
            "/api/folders/shared/tools/example.py",
            json={"content": "# test"},
        )
        assert response.status_code == 401

    def test_update_nonexistent_tool(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Update returns 404 for nonexistent tool."""
        response = web_client.put(
            "/api/folders/shared/tools/nonexistent.py",
            json={"content": "# test"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_update_invalid_namespace(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Update returns 400 or 404 for invalid namespace."""
        response = web_client.put(
            "/api/folders/../etc/tools/test.py",
            json={"content": "# test"},
            headers=auth_headers,
        )
        # Both 400 and 404 are valid security responses
        assert response.status_code in [400, 404]

    def test_update_requires_valid_json(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Update endpoint requires valid JSON body."""
        # Test with invalid JSON format
        response = web_client.put(
            "/api/folders/shared/tools/test.py",
            content="not json",
            headers={**auth_headers, "Content-Type": "application/json"},
        )

        # Should return 422 for validation error or 400 for bad request
        assert response.status_code in [400, 422]


class TestLogFiles:
    """Tests for /api/admin/logs/files endpoints."""

    def test_list_log_files_requires_auth(self, web_client: SyncASGIClient):
        """Log files listing requires authentication."""
        response = web_client.get("/api/admin/logs/files")
        assert response.status_code == 401

    def test_list_log_files_returns_info(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Log files listing returns file information."""
        response = web_client.get("/api/admin/logs/files", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "files" in data
        assert "total_size_bytes" in data
        assert "retention_days" in data
        assert "log_dir" in data
        assert isinstance(data["files"], list)
        assert data["retention_days"] > 0

    def test_get_log_file_content_requires_auth(self, web_client: SyncASGIClient):
        """Log file content requires authentication."""
        response = web_client.get("/api/admin/logs/files/2024-01-01")
        assert response.status_code == 401

    def test_get_log_file_not_found(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Nonexistent log file returns 404."""
        response = web_client.get(
            "/api/admin/logs/files/1999-01-01", headers=auth_headers
        )
        assert response.status_code == 404


class TestNamespaces:
    """Tests for /api/admin/namespaces endpoint."""

    def test_namespaces_requires_auth(self, web_client: SyncASGIClient):
        """Namespaces endpoint requires authentication."""
        response = web_client.get("/api/admin/namespaces")
        assert response.status_code == 401

    def test_namespaces_returns_list(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Namespaces endpoint returns unified namespace list."""
        response = web_client.get("/api/admin/namespaces", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert "namespaces" in data
        assert "total" in data
        assert isinstance(data["namespaces"], list)
        assert data["total"] == len(data["namespaces"])

    def test_namespaces_include_type(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Namespaces include type field (native, fastmcp, external)."""
        response = web_client.get("/api/admin/namespaces", headers=auth_headers)
        data = response.json()

        for ns in data["namespaces"]:
            assert "name" in ns
            assert "type" in ns
            assert ns["type"] in ["native", "fastmcp", "external"]
            assert "tool_count" in ns

    def test_namespaces_include_endpoint(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Namespaces include endpoint field."""
        response = web_client.get("/api/admin/namespaces", headers=auth_headers)
        data = response.json()

        for ns in data["namespaces"]:
            if ns.get("endpoint"):
                assert ns["endpoint"].startswith("/mcp/")


class TestMetrics:
    """Tests for /api/admin/metrics endpoint."""

    def test_metrics_requires_auth(self, web_client: SyncASGIClient):
        response = web_client.get("/api/admin/metrics")
        assert response.status_code == 401

    def test_metrics_returns_structure(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        response = web_client.get("/api/admin/metrics", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "services" in data
        assert "tool_calls" in data
        for window in ["last_5m", "last_1h", "last_24h", "last_7d"]:
            assert window in data["tool_calls"]


class TestSecurityHeaders:
    """Tests for security-related behavior."""

    def test_path_traversal_blocked(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Path traversal attempts are blocked."""
        # Try various path traversal patterns
        patterns = [
            "../etc/passwd",
            "..%2F..%2Fetc",
            "....//....//etc",
        ]

        for pattern in patterns:
            response = web_client.get(
                f"/api/folders/{pattern}/tools",
                headers=auth_headers,
            )
            # Both 400 (bad request) and 404 (not found) are valid security responses
            # 404 is preferable as it doesn't leak information about valid paths
            assert response.status_code in [400, 404], f"Pattern {pattern} was not blocked"

    def test_invalid_filename_blocked(
        self, web_client: SyncASGIClient, auth_headers: dict
    ):
        """Invalid filenames are blocked."""
        # Note: Null bytes (\x00) cannot be tested because httpx rejects them at URL level
        invalid_names = [
            "../../../etc/passwd",
            "test.py; rm -rf /",
        ]

        for name in invalid_names:
            response = web_client.get(
                f"/api/folders/shared/tools/{name}",
                headers=auth_headers,
            )
            # Should return 400 or 404, not 200
            assert response.status_code in [400, 404], f"Name {name} was not blocked"
