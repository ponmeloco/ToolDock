"""
Unit tests for app.utils module.
"""

from __future__ import annotations

import pytest

from app.utils import (
    clear_request_context,
    generate_request_id,
    get_cors_origins,
    get_request_id,
    get_tool_name,
    set_request_context,
)


# ==================== CORS Tests ====================


class TestGetCorsOrigins:
    """Tests for CORS origin configuration."""

    def test_cors_origins_default(self, monkeypatch):
        """Test default CORS origins when not configured."""
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        origins = get_cors_origins()
        assert origins == ["*"]

    def test_cors_origins_wildcard(self, monkeypatch):
        """Test CORS origins set to wildcard."""
        monkeypatch.setenv("CORS_ORIGINS", "*")
        origins = get_cors_origins()
        assert origins == ["*"]

    def test_cors_origins_single(self, monkeypatch):
        """Test single CORS origin."""
        monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
        origins = get_cors_origins()
        assert origins == ["https://example.com"]

    def test_cors_origins_multiple(self, monkeypatch):
        """Test multiple CORS origins."""
        monkeypatch.setenv("CORS_ORIGINS", "https://a.com, https://b.com, https://c.com")
        origins = get_cors_origins()
        assert origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_cors_origins_strips_whitespace(self, monkeypatch):
        """Test that whitespace is stripped from origins."""
        monkeypatch.setenv("CORS_ORIGINS", "  https://a.com  ,  https://b.com  ")
        origins = get_cors_origins()
        assert origins == ["https://a.com", "https://b.com"]

    def test_cors_origins_empty_string(self, monkeypatch):
        """Test empty CORS origins string."""
        monkeypatch.setenv("CORS_ORIGINS", "")
        origins = get_cors_origins()
        assert origins == ["*"]


# ==================== Request Context Tests ====================


class TestRequestContext:
    """Tests for request context (correlation IDs)."""

    def setup_method(self):
        """Clear context before each test."""
        clear_request_context()

    def teardown_method(self):
        """Clear context after each test."""
        clear_request_context()

    def test_generate_request_id(self):
        """Test request ID generation."""
        id1 = generate_request_id()
        id2 = generate_request_id()

        # Should be 8 hex characters
        assert len(id1) == 8
        assert all(c in "0123456789abcdef" for c in id1)

        # Should be unique
        assert id1 != id2

    def test_set_and_get_request_id(self):
        """Test setting and getting request ID."""
        assert get_request_id() is None

        set_request_context(request_id="abc12345")

        assert get_request_id() == "abc12345"

    def test_set_and_get_tool_name(self):
        """Test setting and getting tool name."""
        assert get_tool_name() is None

        set_request_context(tool_name="my_tool")

        assert get_tool_name() == "my_tool"

    def test_set_both_context_values(self):
        """Test setting both request ID and tool name."""
        set_request_context(request_id="req123", tool_name="test_tool")

        assert get_request_id() == "req123"
        assert get_tool_name() == "test_tool"

    def test_clear_request_context(self):
        """Test clearing request context."""
        set_request_context(request_id="req123", tool_name="test_tool")

        clear_request_context()

        assert get_request_id() is None
        assert get_tool_name() is None

    def test_partial_set_preserves_other_values(self):
        """Test that setting one value doesn't clear the other."""
        set_request_context(request_id="req123")
        set_request_context(tool_name="my_tool")

        assert get_request_id() == "req123"
        assert get_tool_name() == "my_tool"
