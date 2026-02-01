"""
Shared utilities for ToolDock.

This module provides common functionality used across multiple components:
- CORS configuration
- Request context (correlation IDs, tool tracking)
"""

from __future__ import annotations

import logging
import os
import uuid
from contextvars import ContextVar
from typing import List, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# CORS Configuration
# =============================================================================


def get_cors_origins() -> List[str]:
    """
    Get CORS origins from environment variable.

    Returns:
        List of allowed origins, or ["*"] if not configured.
    """
    origins_str = os.getenv("CORS_ORIGINS", "").strip()
    if not origins_str or origins_str == "*":
        logger.warning(
            "CORS_ORIGINS not configured or set to '*'. "
            "This is insecure for production. Set specific origins."
        )
        return ["*"]
    return [origin.strip() for origin in origins_str.split(",") if origin.strip()]


# =============================================================================
# Request Context (Correlation IDs)
# =============================================================================

# Context variables for request tracking
_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_tool_name: ContextVar[Optional[str]] = ContextVar("tool_name", default=None)


def generate_request_id() -> str:
    """Generate a short unique request ID."""
    return uuid.uuid4().hex[:8]


def set_request_context(request_id: Optional[str] = None, tool_name: Optional[str] = None) -> None:
    """
    Set the current request context.

    Args:
        request_id: Unique request identifier (generated if not provided)
        tool_name: Name of the tool being executed (if any)
    """
    if request_id:
        _request_id.set(request_id)
    if tool_name:
        _tool_name.set(tool_name)


def get_request_id() -> Optional[str]:
    """Get the current request ID."""
    return _request_id.get()


def get_tool_name() -> Optional[str]:
    """Get the current tool name being executed."""
    return _tool_name.get()


def clear_request_context() -> None:
    """Clear the request context."""
    _request_id.set(None)
    _tool_name.set(None)


class ContextFilter(logging.Filter):
    """
    Logging filter that adds request context to log records.

    Adds:
        - request_id: Unique identifier for the request
        - tool_name: Name of the tool being executed (if any)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        request_id = get_request_id()
        tool_name = get_tool_name()

        # Build context prefix
        parts = []
        if request_id:
            parts.append(request_id)
        if tool_name:
            parts.append(tool_name)

        record.context = f"[{'/'.join(parts)}] " if parts else ""
        return True


def setup_context_logging() -> None:
    """
    Setup logging with context filter.

    Call this once at application startup to enable correlation IDs in logs.
    """
    # Add filter to root logger
    context_filter = ContextFilter()
    for handler in logging.root.handlers:
        handler.addFilter(context_filter)

    # Update format to include context
    formatter = logging.Formatter(
        "%(levelname)s %(context)s%(name)s: %(message)s"
    )
    for handler in logging.root.handlers:
        handler.setFormatter(formatter)
