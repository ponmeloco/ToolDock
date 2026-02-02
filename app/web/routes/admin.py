"""
Admin API Routes.

Provides endpoints for system administration:
- Aggregated health check
- Log viewing
- System information

Logging:
- In-memory circular buffer for live viewing (last 1000 entries)
- Persistent JSON Lines files with daily rotation
- Automatic cleanup of logs older than LOG_RETENTION_DAYS (default: 30)
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from app.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# In-memory log buffer (circular buffer for last N log entries)
LOG_BUFFER_SIZE = 1000
_log_buffer: deque = deque(maxlen=LOG_BUFFER_SIZE)

# Persistent log settings
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "30"))
_log_dir: Optional[Path] = None
_current_log_date: Optional[str] = None
_current_log_file = None


class LogEntry(BaseModel):
    """A single log entry."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    level: str
    logger: str
    message: str
    # Optional HTTP request fields
    http_method: Optional[str] = None
    http_path: Optional[str] = None
    http_status: Optional[int] = None
    http_duration_ms: Optional[float] = None
    tool_name: Optional[str] = None
    service_name: Optional[str] = None
    request_id: Optional[str] = None
    error_detail: Optional[str] = None


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


class ServiceErrorRate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int
    errors: int
    error_rate: float


class ServiceErrorRates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_5m: ServiceErrorRate
    last_1h: ServiceErrorRate
    last_24h: ServiceErrorRate
    last_7d: ServiceErrorRate


class ToolCallCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    success: int
    error: int


class ToolCallStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_5m: ToolCallCounts
    last_1h: ToolCallCounts
    last_24h: ToolCallCounts
    last_7d: ToolCallCounts


class MetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    services: dict
    tool_calls: ToolCallStats


class ServiceErrorRate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: int
    errors: int
    error_rate: float


class ServiceErrorRates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_5m: ServiceErrorRate
    last_1h: ServiceErrorRate
    last_24h: ServiceErrorRate
    last_7d: ServiceErrorRate


class ToolCallCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    success: int
    error: int


class ToolCallStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    last_5m: ToolCallCounts
    last_1h: ToolCallCounts
    last_24h: ToolCallCounts
    last_7d: ToolCallCounts


class MetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: str
    services: dict
    tool_calls: ToolCallStats


def _get_log_dir() -> Path:
    """Get the logs directory, creating it if necessary."""
    global _log_dir
    if _log_dir is None:
        data_dir = os.getenv("DATA_DIR", "tooldock_data")
        _log_dir = Path(data_dir) / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
    return _log_dir


def _get_log_file():
    """Get the current log file handle, rotating daily."""
    global _current_log_date, _current_log_file

    today = datetime.now().strftime("%Y-%m-%d")

    if _current_log_date != today:
        # Close old file if open
        if _current_log_file is not None:
            try:
                _current_log_file.close()
            except Exception:
                pass

        # Open new daily log file
        log_dir = _get_log_dir()
        log_path = log_dir / f"{today}.jsonl"
        _current_log_file = open(log_path, "a", encoding="utf-8")
        _current_log_date = today

        # Run cleanup in background (non-blocking)
        _cleanup_old_logs()

    return _current_log_file


def _cleanup_old_logs():
    """Remove log files older than LOG_RETENTION_DAYS."""
    try:
        log_dir = _get_log_dir()
        cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)

        for log_file in log_dir.glob("*.jsonl"):
            try:
                # Parse date from filename (YYYY-MM-DD.jsonl)
                file_date_str = log_file.stem
                file_date = datetime.strptime(file_date_str, "%Y-%m-%d")

                if file_date < cutoff:
                    log_file.unlink()
                    logger.info(f"Deleted old log file: {log_file.name}")
            except (ValueError, OSError) as e:
                # Skip files that don't match the expected format
                logger.debug(f"Skipping log file {log_file.name}: {e}")
    except Exception as e:
        logger.warning(f"Error during log cleanup: {e}")


def _write_log_to_file(entry: LogEntry):
    """Write a log entry to the daily log file."""
    try:
        log_file = _get_log_file()
        log_file.write(entry.model_dump_json() + "\n")
        log_file.flush()
    except Exception as e:
        # Don't let file logging errors break the app
        logger.debug(f"Failed to write log to file: {e}")


def _read_recent_logs_from_file(
    limit: int,
    level: Optional[str] = None,
    logger_name: Optional[str] = None,
) -> tuple[List[LogEntry], int]:
    """Read recent log entries from today's log file."""
    log_dir = _get_log_dir()
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.jsonl"

    if not log_file.exists():
        return [], 0

    level_upper = level.upper() if level else None
    results: deque = deque(maxlen=limit)
    total = 0

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    entry = LogEntry(**data)
                except (json.JSONDecodeError, ValueError):
                    continue

                if level_upper and entry.level != level_upper:
                    continue
                if logger_name and logger_name.lower() not in entry.logger.lower():
                    continue

                results.append(entry)
                total += 1
    except Exception as e:
        logger.warning(f"Error reading log file {log_file}: {e}")
        return [], 0

    return list(results), total


def _infer_service_name(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("/mcp"):
        return "mcp"
    if path.startswith("/tools") or path.startswith("/openapi") or path.startswith("/docs"):
        return "openapi"
    if path.startswith("/api") or path.startswith("/admin"):
        return "web"
    return None


def _load_logs_since(cutoff: datetime) -> List[LogEntry]:
    """Load log entries from the last 7 days (or since cutoff)."""
    log_dir = _get_log_dir()
    entries: List[LogEntry] = []
    for log_file in sorted(log_dir.glob("*.jsonl")):
        try:
            file_date_str = log_file.stem
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # Skip files older than cutoff date
        if file_date.date() < cutoff.date():
            continue

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        entry = LogEntry(**data)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    try:
                        ts = datetime.fromisoformat(entry.timestamp)
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue

                    if entry.service_name is None:
                        entry.service_name = _infer_service_name(entry.http_path)
                    entries.append(entry)
        except Exception as e:
            logger.warning(f"Error reading log file {log_file}: {e}")

    return entries


class BufferingLogHandler(logging.Handler):
    """Custom log handler that buffers log entries and writes to file."""

    def __init__(self, buffer: deque, persist_to_file: bool = True):
        super().__init__()
        self.buffer = buffer
        self.persist_to_file = persist_to_file

    def emit(self, record: logging.LogRecord):
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created).isoformat(),
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
            )
            self.buffer.append(entry)

            # Also write to file for persistence
            if self.persist_to_file:
                _write_log_to_file(entry)
        except Exception:
            pass  # Don't let logging errors break the app


def setup_log_buffer():
    """Setup the log buffer handler on relevant loggers."""
    handler = BufferingLogHandler(_log_buffer, persist_to_file=True)
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

    log_dir = _get_log_dir()
    logger.info(f"Log buffer initialized (persistent logs: {log_dir}, retention: {LOG_RETENTION_DAYS} days)")


def log_request(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    tool_name: Optional[str] = None,
    service_name: Optional[str] = None,
    request_id: Optional[str] = None,
    error_detail: Optional[str] = None,
):
    """Log an HTTP request to the buffer and file."""
    if tool_name is None:
        try:
            from app.utils import get_tool_name

            tool_name = get_tool_name()
        except Exception:
            pass

    # Determine log level based on status code
    if status_code >= 500:
        level = "ERROR"
    elif status_code >= 400:
        level = "WARNING"
    else:
        level = "INFO"

    # Build message with request ID prefix
    prefix = f"[{request_id}] " if request_id else ""
    message = f"{prefix}{method} {path} {status_code} ({duration_ms:.1f}ms)"
    if tool_name:
        message = f"{message} [tool: {tool_name}]"

    entry = LogEntry(
        timestamp=datetime.now().isoformat(),
        level=level,
        logger="http.access",
        message=message,
        http_method=method,
        http_path=path,
        http_status=status_code,
        http_duration_ms=round(duration_ms, 1),
        tool_name=tool_name,
        service_name=service_name,
        request_id=request_id,
        error_detail=error_detail,
    )
    _log_buffer.append(entry)

    # Also write to persistent log file
    _write_log_to_file(entry)


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(
    _: str = Depends(verify_token),
) -> SystemHealthResponse:
    """
    Get aggregated health status of all services.

    Returns health status of OpenAPI, MCP, and Web GUI servers.
    """
    import httpx
    import anyio

    openapi_port = int(os.getenv("OPENAPI_PORT", "8006"))
    mcp_port = int(os.getenv("MCP_PORT", "8007"))
    web_port = int(os.getenv("WEB_PORT", "8080"))

    openapi_public_port = int(os.getenv("OPENAPI_PUBLIC_PORT", str(openapi_port)))
    mcp_public_port = int(os.getenv("MCP_PUBLIC_PORT", str(mcp_port)))
    web_public_port = int(os.getenv("WEB_PUBLIC_PORT", str(web_port)))

    services = []

    # Check each service
    async with httpx.AsyncClient(timeout=2.0) as client:
        # OpenAPI Server
        try:
            with anyio.fail_after(2.0):
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
                port=openapi_public_port,
                details=openapi_details,
            )
        )

        # MCP Server
        try:
            with anyio.fail_after(2.0):
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
                port=mcp_public_port,
                details=mcp_details,
            )
        )

        # Web GUI (self - always healthy if we're responding)
        services.append(
            ServiceHealth(
                name="web",
                status="healthy",
                port=web_public_port,
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
            "data_dir": os.getenv("DATA_DIR", "tooldock_data"),
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
    # Prefer file-backed logs to include entries from other processes (OpenAPI/MCP)
    logs, total = _read_recent_logs_from_file(limit, level=level, logger_name=logger_name)

    # Fallback to in-memory buffer if file is empty/unavailable
    if not logs:
        logs = list(_log_buffer)
        if level:
            level_upper = level.upper()
            logs = [log for log in logs if log.level == level_upper]
        if logger_name:
            logs = [log for log in logs if logger_name.lower() in log.logger.lower()]
        logs = logs[-limit:]

    if not total:
        total = len(logs)

    return LogsResponse(
        logs=logs,
        total=total,
        has_more=total > limit,
    )


class LogFileInfo(BaseModel):
    """Information about a log file."""

    model_config = ConfigDict(extra="forbid")

    date: str
    filename: str
    size_bytes: int
    entry_count: int


class LogFilesResponse(BaseModel):
    """Response for log files listing."""

    model_config = ConfigDict(extra="forbid")

    files: List[LogFileInfo]
    total_size_bytes: int
    retention_days: int
    log_dir: str


@router.get("/logs/files", response_model=LogFilesResponse)
async def get_log_files(
    _: str = Depends(verify_token),
) -> LogFilesResponse:
    """
    Get list of all log files with their sizes and entry counts.

    Returns information about daily log files stored in DATA_DIR/logs/.
    """
    log_dir = _get_log_dir()
    files = []
    total_size = 0

    for log_file in sorted(log_dir.glob("*.jsonl"), reverse=True):
        try:
            size = log_file.stat().st_size
            total_size += size

            # Count entries (lines) in file
            entry_count = 0
            with open(log_file, "r", encoding="utf-8") as f:
                entry_count = sum(1 for _ in f)

            files.append(LogFileInfo(
                date=log_file.stem,
                filename=log_file.name,
                size_bytes=size,
                entry_count=entry_count,
            ))
        except Exception as e:
            logger.warning(f"Error reading log file {log_file}: {e}")

    return LogFilesResponse(
        files=files,
        total_size_bytes=total_size,
        retention_days=LOG_RETENTION_DAYS,
        log_dir=str(log_dir),
    )


@router.get("/logs/files/{date}")
async def get_log_file_content(
    date: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    _: str = Depends(verify_token),
) -> LogsResponse:
    """
    Get log entries from a specific date's log file.

    Args:
        date: Date in YYYY-MM-DD format
        limit: Maximum number of entries to return
        offset: Number of entries to skip (for pagination)
    """
    log_dir = _get_log_dir()
    log_file = log_dir / f"{date}.jsonl"

    if not log_file.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Log file for {date} not found")

    logs = []
    total = 0

    try:
        with open(log_file, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                total += 1
                if i < offset:
                    continue
                if len(logs) >= limit:
                    continue  # Keep counting total but don't add more

                try:
                    data = json.loads(line.strip())
                    logs.append(LogEntry(**data))
                except (json.JSONDecodeError, ValueError):
                    pass  # Skip malformed entries
    except Exception as e:
        logger.warning(f"Error reading log file {log_file}: {e}")

    return LogsResponse(
        logs=logs,
        total=total,
        has_more=total > offset + limit,
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

    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    data_dir_absolute = str(Path(data_dir).resolve())
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
        data_dir=data_dir_absolute,
        namespaces=namespaces,
        environment={
            "openapi_port": os.getenv("OPENAPI_PUBLIC_PORT", os.getenv("OPENAPI_PORT", "8006")),
            "mcp_port": os.getenv("MCP_PUBLIC_PORT", os.getenv("MCP_PORT", "8007")),
            "web_port": os.getenv("WEB_PUBLIC_PORT", os.getenv("WEB_PORT", "8080")),
            "openapi_internal_port": os.getenv("OPENAPI_PORT", "8006"),
            "mcp_internal_port": os.getenv("MCP_PORT", "8007"),
            "web_internal_port": os.getenv("WEB_PORT", "8080"),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
            "cors_origins": os.getenv("CORS_ORIGINS", "*"),
            "mcp_protocol_version": os.getenv("MCP_PROTOCOL_VERSION", "2025-11-25"),
            "mcp_protocol_versions": os.getenv(
                "MCP_PROTOCOL_VERSIONS",
                f"{os.getenv('MCP_PROTOCOL_VERSION', '2025-11-25')},2025-03-26",
            ),
            "host_data_dir": os.getenv("HOST_DATA_DIR", ""),
        },
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(_: str = Depends(verify_token)) -> MetricsResponse:
    """Get recent error rates and tool call stats for the dashboard."""
    now = datetime.now()
    cutoff = now - timedelta(days=7)
    entries = _load_logs_since(cutoff)

    windows = {
        "last_5m": now - timedelta(minutes=5),
        "last_1h": now - timedelta(hours=1),
        "last_24h": now - timedelta(hours=24),
        "last_7d": now - timedelta(days=7),
    }

    service_names = ["openapi", "mcp", "web"]
    services: dict = {}

    for service in service_names:
        rates = {}
        for key, window_start in windows.items():
            window_entries = [
                e for e in entries
                if e.service_name == service
                and e.http_status is not None
                and datetime.fromisoformat(e.timestamp) >= window_start
            ]
            requests = len(window_entries)
            errors = len([e for e in window_entries if (e.http_status or 0) >= 400])
            error_rate = (errors / requests * 100.0) if requests else 0.0
            rates[key] = ServiceErrorRate(
                requests=requests,
                errors=errors,
                error_rate=round(error_rate, 2),
            )
        services[service] = ServiceErrorRates(**rates)

    def tool_counts(since: datetime) -> ToolCallCounts:
        tool_entries = [
            e for e in entries
            if e.tool_name is not None
            and e.http_status is not None
            and datetime.fromisoformat(e.timestamp) >= since
        ]
        total = len(tool_entries)
        errors = len([e for e in tool_entries if (e.http_status or 0) >= 400])
        success = total - errors
        return ToolCallCounts(total=total, success=success, error=errors)

    tool_calls = ToolCallStats(
        last_5m=tool_counts(windows["last_5m"]),
        last_1h=tool_counts(windows["last_1h"]),
        last_24h=tool_counts(windows["last_24h"]),
        last_7d=tool_counts(windows["last_7d"]),
    )

    return MetricsResponse(
        timestamp=now.isoformat(),
        services=services,
        tool_calls=tool_calls,
    )
