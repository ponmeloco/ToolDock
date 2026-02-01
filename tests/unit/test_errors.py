"""
Unit tests for app/errors.py - Custom error classes.
"""

import pytest

from app.errors import (
    ToolError,
    ToolNotFoundError,
    ToolValidationError,
    ToolUnauthorizedError,
    ToolInternalError,
    ToolTimeoutError,
)


class TestToolError:
    """Tests for base ToolError class."""

    def test_create_tool_error(self):
        """Test creating a basic ToolError."""
        error = ToolError(code="test_error", message="Test message")
        assert error.code == "test_error"
        assert error.message == "Test message"
        assert error.details is None

    def test_create_tool_error_with_details(self):
        """Test creating ToolError with details."""
        details = {"key": "value", "count": 42}
        error = ToolError(code="test_error", message="Test message", details=details)
        assert error.details == details

    def test_to_dict_without_details(self):
        """Test to_dict returns correct structure without details."""
        error = ToolError(code="my_code", message="My message")
        result = error.to_dict()

        assert result["code"] == "my_code"
        assert result["message"] == "My message"
        assert result["details"] == {}

    def test_to_dict_with_details(self):
        """Test to_dict includes details."""
        error = ToolError(
            code="my_code", message="My message", details={"info": "value"}
        )
        result = error.to_dict()

        assert result["details"] == {"info": "value"}

    def test_tool_error_is_exception(self):
        """Test ToolError is an Exception."""
        error = ToolError(code="test", message="test")
        assert isinstance(error, Exception)

    def test_tool_error_can_be_raised(self):
        """Test ToolError can be raised and caught."""
        with pytest.raises(ToolError) as exc_info:
            raise ToolError(code="raised", message="This was raised")

        assert exc_info.value.code == "raised"


class TestToolNotFoundError:
    """Tests for ToolNotFoundError."""

    def test_create_with_tool_name(self):
        """Test creating ToolNotFoundError with tool name."""
        error = ToolNotFoundError("my_tool")
        assert error.code == "tool_not_found"
        assert "my_tool" in error.message
        assert error.details["tool"] == "my_tool"

    def test_to_dict(self):
        """Test to_dict includes tool name in details."""
        error = ToolNotFoundError("missing_tool")
        result = error.to_dict()

        assert result["code"] == "tool_not_found"
        assert result["details"]["tool"] == "missing_tool"

    def test_is_tool_error(self):
        """Test ToolNotFoundError is a ToolError."""
        error = ToolNotFoundError("tool")
        assert isinstance(error, ToolError)


class TestToolValidationError:
    """Tests for ToolValidationError."""

    def test_create_with_message(self):
        """Test creating ToolValidationError with message."""
        error = ToolValidationError("Invalid input format")
        assert error.code == "validation_error"
        assert error.message == "Invalid input format"
        assert error.details is None

    def test_create_with_details(self):
        """Test creating ToolValidationError with details."""
        error = ToolValidationError(
            "Validation failed",
            details={"field": "name", "error": "required"},
        )
        assert error.details["field"] == "name"
        assert error.details["error"] == "required"

    def test_to_dict(self):
        """Test to_dict returns correct structure."""
        error = ToolValidationError("Invalid", details={"field": "x"})
        result = error.to_dict()

        assert result["code"] == "validation_error"
        assert result["message"] == "Invalid"
        assert result["details"]["field"] == "x"


class TestToolUnauthorizedError:
    """Tests for ToolUnauthorizedError."""

    def test_create_default_message(self):
        """Test creating ToolUnauthorizedError with default message."""
        error = ToolUnauthorizedError()
        assert error.code == "unauthorized"
        assert error.message == "Nicht autorisiert"
        assert error.details == {}

    def test_create_custom_message(self):
        """Test creating ToolUnauthorizedError with custom message."""
        error = ToolUnauthorizedError("Token expired")
        assert error.message == "Token expired"

    def test_to_dict(self):
        """Test to_dict returns correct structure."""
        error = ToolUnauthorizedError("Custom message")
        result = error.to_dict()

        assert result["code"] == "unauthorized"
        assert result["message"] == "Custom message"
        assert result["details"] == {}


class TestToolInternalError:
    """Tests for ToolInternalError."""

    def test_create_default_message(self):
        """Test creating ToolInternalError with default message."""
        error = ToolInternalError()
        assert error.code == "internal_error"
        assert error.message == "Interner Fehler"

    def test_create_custom_message(self):
        """Test creating ToolInternalError with custom message."""
        error = ToolInternalError("Database connection failed")
        assert error.message == "Database connection failed"

    def test_create_with_details(self):
        """Test creating ToolInternalError with details."""
        error = ToolInternalError(
            "Operation failed", details={"operation": "save", "retry": True}
        )
        assert error.details["operation"] == "save"
        assert error.details["retry"] is True

    def test_to_dict(self):
        """Test to_dict returns correct structure."""
        error = ToolInternalError("Error", details={"trace": "..."})
        result = error.to_dict()

        assert result["code"] == "internal_error"
        assert result["details"]["trace"] == "..."


class TestToolTimeoutError:
    """Tests for ToolTimeoutError."""

    def test_create_with_tool_and_timeout(self):
        """Test creating ToolTimeoutError with tool name and timeout."""
        error = ToolTimeoutError("slow_tool", 30.0)
        assert error.code == "tool_timeout"
        assert "slow_tool" in error.message
        assert "30" in error.message
        assert error.details["tool"] == "slow_tool"
        assert error.details["timeout_seconds"] == 30.0

    def test_to_dict(self):
        """Test to_dict returns correct structure."""
        error = ToolTimeoutError("my_tool", 60.5)
        result = error.to_dict()

        assert result["code"] == "tool_timeout"
        assert result["details"]["tool"] == "my_tool"
        assert result["details"]["timeout_seconds"] == 60.5

    def test_is_tool_error(self):
        """Test ToolTimeoutError is a ToolError."""
        error = ToolTimeoutError("tool", 30)
        assert isinstance(error, ToolError)
