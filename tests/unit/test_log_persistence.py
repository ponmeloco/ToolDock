"""
Unit tests for log persistence functionality.

Tests:
- Daily log file rotation
- Log cleanup after retention period
- JSON Lines format writing and reading
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


class TestLogFileRotation:
    """Tests for daily log file rotation."""

    def test_get_log_dir_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Log directory is created if it doesn't exist."""
        from app.web.routes import admin

        # Reset the global state
        admin._log_dir = None

        log_dir = tmp_path / "logs"
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        result = admin._get_log_dir()

        assert result == log_dir
        assert log_dir.exists()

        # Cleanup
        admin._log_dir = None

    def test_log_file_uses_daily_rotation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Log files are named by date (YYYY-MM-DD.jsonl)."""
        from app.web.routes import admin

        # Reset the global state
        admin._log_dir = None
        admin._current_log_date = None
        admin._current_log_file = None

        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        log_file = admin._get_log_file()
        today = datetime.now().strftime("%Y-%m-%d")

        assert log_file is not None
        assert admin._current_log_date == today

        # Check file was created
        expected_path = tmp_path / "logs" / f"{today}.jsonl"
        assert expected_path.exists()

        # Cleanup
        log_file.close()
        admin._log_dir = None
        admin._current_log_date = None
        admin._current_log_file = None


class TestLogCleanup:
    """Tests for automatic log cleanup."""

    def test_cleanup_removes_old_logs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Old log files are deleted after retention period."""
        from app.web.routes import admin

        # Reset the global state
        admin._log_dir = None

        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setattr(admin, "LOG_RETENTION_DAYS", 7)

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        # Create some log files
        today = datetime.now()
        old_dates = [
            today - timedelta(days=10),  # Delete (older than 7 days)
            today - timedelta(days=30),  # Delete (older than 7 days)
        ]
        recent_dates = [
            today - timedelta(days=1),   # Keep (within 7 days)
            today - timedelta(days=5),   # Keep (within 7 days)
        ]

        for date in old_dates + recent_dates:
            log_file = log_dir / f"{date.strftime('%Y-%m-%d')}.jsonl"
            log_file.write_text('{"test": "data"}\n')

        # Run cleanup
        admin._cleanup_old_logs()

        # Check that old files were deleted
        for date in old_dates:
            old_file = log_dir / f"{date.strftime('%Y-%m-%d')}.jsonl"
            assert not old_file.exists(), f"Old file {old_file.name} should have been deleted"

        # Check that recent files still exist
        for date in recent_dates:
            recent_file = log_dir / f"{date.strftime('%Y-%m-%d')}.jsonl"
            assert recent_file.exists(), f"Recent file {recent_file.name} should still exist"

        # Cleanup
        admin._log_dir = None

    def test_cleanup_skips_invalid_filenames(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Non-date filenames are skipped during cleanup."""
        from app.web.routes import admin

        # Reset the global state
        admin._log_dir = None

        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setattr(admin, "LOG_RETENTION_DAYS", 7)

        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)

        # Create files with various names
        (log_dir / "invalid-name.jsonl").write_text('{"test": "data"}\n')
        (log_dir / "not-a-date.log").write_text('{"test": "data"}\n')

        # This should not raise an error
        admin._cleanup_old_logs()

        # Invalid files should still exist (not deleted)
        assert (log_dir / "invalid-name.jsonl").exists()
        assert (log_dir / "not-a-date.log").exists()

        # Cleanup
        admin._log_dir = None


class TestLogWriting:
    """Tests for log entry writing."""

    def test_write_log_to_file_json_lines_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Log entries are written in JSON Lines format."""
        from app.web.routes.admin import LogEntry, _write_log_to_file, _get_log_dir
        from app.web.routes import admin

        # Reset the global state
        admin._log_dir = None
        admin._current_log_date = None
        admin._current_log_file = None

        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        entry = LogEntry(
            timestamp="2024-01-15T10:30:00",
            level="INFO",
            logger="test.logger",
            message="Test log message",
            http_method="GET",
            http_path="/api/test",
            http_status=200,
        )

        _write_log_to_file(entry)

        # Close file to flush
        if admin._current_log_file:
            admin._current_log_file.close()

        # Read and verify
        log_dir = _get_log_dir()
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}.jsonl"

        assert log_file.exists()

        with open(log_file, "r") as f:
            line = f.readline()
            data = json.loads(line)

        assert data["timestamp"] == "2024-01-15T10:30:00"
        assert data["level"] == "INFO"
        assert data["message"] == "Test log message"
        assert data["http_method"] == "GET"
        assert data["http_status"] == 200

        # Cleanup
        admin._log_dir = None
        admin._current_log_date = None
        admin._current_log_file = None

    def test_log_request_writes_to_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """log_request() writes entries to both buffer and file."""
        from app.web.routes.admin import log_request, _log_buffer, _get_log_dir
        from app.web.routes import admin

        # Reset the global state
        admin._log_dir = None
        admin._current_log_date = None
        admin._current_log_file = None

        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        # Use a unique tool name to identify our entry
        unique_tool_name = f"test_tool_{datetime.now().timestamp()}"

        log_request(
            method="POST",
            path="/api/playground/execute",
            status_code=200,
            duration_ms=45.5,
            tool_name=unique_tool_name,
            request_id="req-123",
        )

        # Check that entry was added to buffer (last entry should be ours)
        last_entry = _log_buffer[-1]
        assert last_entry.tool_name == unique_tool_name

        # Close file to flush
        if admin._current_log_file:
            admin._current_log_file.close()

        # Check file
        log_dir = _get_log_dir()
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}.jsonl"

        assert log_file.exists()

        with open(log_file, "r") as f:
            lines = f.readlines()

        assert len(lines) >= 1

        # Find our log entry
        found = False
        for line in lines:
            data = json.loads(line)
            if data.get("tool_name") == unique_tool_name:
                assert data["http_method"] == "POST"
                assert data["http_path"] == "/api/playground/execute"
                assert data["http_status"] == 200
                assert data["request_id"] == "req-123"
                found = True
                break

        assert found, "Log entry not found in file"

        # Cleanup
        admin._log_dir = None
        admin._current_log_date = None
        admin._current_log_file = None


class TestLogRetention:
    """Tests for log retention configuration."""

    def test_log_retention_from_env(self, monkeypatch: pytest.MonkeyPatch):
        """LOG_RETENTION_DAYS is read from environment."""
        monkeypatch.setenv("LOG_RETENTION_DAYS", "14")

        # Re-import to pick up new env var
        import importlib
        from app.web.routes import admin
        importlib.reload(admin)

        assert admin.LOG_RETENTION_DAYS == 14

        # Reset to default
        monkeypatch.delenv("LOG_RETENTION_DAYS", raising=False)
        importlib.reload(admin)

    def test_log_retention_default(self, monkeypatch: pytest.MonkeyPatch):
        """LOG_RETENTION_DAYS defaults to 30."""
        monkeypatch.delenv("LOG_RETENTION_DAYS", raising=False)

        import importlib
        from app.web.routes import admin
        importlib.reload(admin)

        assert admin.LOG_RETENTION_DAYS == 30
