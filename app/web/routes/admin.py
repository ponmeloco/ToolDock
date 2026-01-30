"""
Admin API Routes.

Provides endpoints for system administration:
- Aggregated health check
- Log viewing
- System information
"""

from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# In-memory log buffer (circular buffer for last N log entries)
LOG_BUFFER_SIZE = 1000
_log_buffer: deque = deque(maxlen=LOG_BUFFER_SIZE)


class LogEntry(BaseModel):
    """A single log entry."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    level: str
    logger: str
    message: str


class LogsResponse(BaseModel):
    """Response for logs endpoint."""

    model_config = ConfigDict(extra="forbid")

    logs: List[LogEntry]
    total: int
    has_more: bool


class ServiceHealth(BaseModel):
    """Health status of a single service."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    port: int
    details: Optional[dict] = None


class SystemHealthResponse(BaseModel):
    """Aggregated health response."""

    model_config = ConfigDict(extra="forbid")

    status: str
    timestamp: str
    services: List[ServiceHealth]
    environment: dict


class SystemInfoResponse(BaseModel):
    """System information response."""

    model_config = ConfigDict(extra="forbid")

    version: str
    python_version: str
    data_dir: str
    namespaces: List[str]
    environment: dict


class BufferingLogHandler(logging.Handler):
    """Custom log handler that buffers log entries."""

    def __init__(self, buffer: deque):
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord):
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created).isoformat(),
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
            )
            self.buffer.append(entry)
        except Exception:
            pass  # Don't let logging errors break the app


def setup_log_buffer():
    """Setup the log buffer handler on relevant loggers."""
    handler = BufferingLogHandler(_log_buffer)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Add to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    # Add to all app-specific loggers
    for logger_name in [
        "backend-api", "mcp", "openapi", "httpx",
        "uvicorn", "uvicorn.access", "uvicorn.error",
        "app", "app.web", "app.auth", "app.reload",
    ]:
        app_logger = logging.getLogger(logger_name)
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.DEBUG)

    logger.info("Log buffer initialized")


def log_request(method: str, path: str, status_code: int, duration_ms: float):
    """Log an HTTP request to the buffer."""
    entry = LogEntry(
        timestamp=datetime.now().isoformat(),
        level="INFO",
        logger="http.access",
        message=f"{method} {path} {status_code} ({duration_ms:.1f}ms)",
    )
    _log_buffer.append(entry)


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(
    _: str = Depends(verify_token),
) -> SystemHealthResponse:
    """
    Get aggregated health status of all services.

    Returns health status of OpenAPI, MCP, and Web GUI servers.
    """
    import httpx

    openapi_port = int(os.getenv("OPENAPI_PORT", "8006"))
    mcp_port = int(os.getenv("MCP_PORT", "8007"))
    web_port = int(os.getenv("WEB_PORT", "8080"))

    services = []

    # Check each service
    async with httpx.AsyncClient(timeout=2.0) as client:
        # OpenAPI Server
        try:
            resp = await client.get(f"http://localhost:{openapi_port}/health")
            openapi_status = "healthy" if resp.status_code == 200 else "unhealthy"
            openapi_details = resp.json() if resp.status_code == 200 else None
        except Exception:
            openapi_status = "unreachable"
            openapi_details = None

        services.append(
            ServiceHealth(
                name="openapi",
                status=openapi_status,
                port=openapi_port,
                details=openapi_details,
            )
        )

        # MCP Server
        try:
            resp = await client.get(f"http://localhost:{mcp_port}/health")
            mcp_status = "healthy" if resp.status_code == 200 else "unhealthy"
            mcp_details = resp.json() if resp.status_code == 200 else None
        except Exception:
            mcp_status = "unreachable"
            mcp_details = None

        services.append(
            ServiceHealth(
                name="mcp",
                status=mcp_status,
                port=mcp_port,
                details=mcp_details,
            )
        )

        # Web GUI (self - always healthy if we're responding)
        services.append(
            ServiceHealth(
                name="web",
                status="healthy",
                port=web_port,
                details={"service": "web-gui"},
            )
        )

    # Overall status
    all_healthy = all(s.status == "healthy" for s in services)
    overall_status = "healthy" if all_healthy else "degraded"

    return SystemHealthResponse(
        status=overall_status,
        timestamp=datetime.now().isoformat(),
        services=services,
        environment={
            "data_dir": os.getenv("DATA_DIR", "omnimcp_data"),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
        },
    )


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    limit: int = Query(default=100, ge=1, le=1000),
    level: Optional[str] = Query(default=None, description="Filter by log level"),
    logger_name: Optional[str] = Query(default=None, description="Filter by logger name"),
    _: str = Depends(verify_token),
) -> LogsResponse:
    """
    Get recent log entries.

    Args:
        limit: Maximum number of log entries to return
        level: Filter by log level (DEBUG, INFO, WARNING, ERROR)
        logger_name: Filter by logger name (e.g., 'mcp', 'openapi')
    """
    # Filter logs
    logs = list(_log_buffer)

    if level:
        level_upper = level.upper()
        logs = [log for log in logs if log.level == level_upper]

    if logger_name:
        logs = [log for log in logs if logger_name.lower() in log.logger.lower()]

    # Get most recent entries
    total = len(logs)
    logs = logs[-limit:]

    return LogsResponse(
        logs=logs,
        total=total,
        has_more=total > limit,
    )


@router.get("/info", response_model=SystemInfoResponse)
async def get_system_info(
    _: str = Depends(verify_token),
) -> SystemInfoResponse:
    """
    Get system information.

    Returns version, Python version, data directory, and namespaces.
    """
    import sys
    from pathlib import Path

    data_dir = os.getenv("DATA_DIR", "omnimcp_data")
    tools_dir = Path(data_dir) / "tools"

    # Get namespaces
    namespaces = []
    if tools_dir.exists():
        namespaces = [
            d.name for d in sorted(tools_dir.iterdir())
            if d.is_dir() and not d.name.startswith("_")
        ]

    return SystemInfoResponse(
        version="1.0.0",
        python_version=sys.version,
        data_dir=data_dir,
        namespaces=namespaces,
        environment={
            "openapi_port": os.getenv("OPENAPI_PORT", "8006"),
            "mcp_port": os.getenv("MCP_PORT", "8007"),
            "web_port": os.getenv("WEB_PORT", "8080"),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "cors_origins": os.getenv("CORS_ORIGINS", "*"),
        },
    )
