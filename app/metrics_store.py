"""
Lightweight metrics store for request logs.

Hybrid design:
- In-memory queue for fast ingestion
- Background flush to SQLite for persistence
"""

from __future__ import annotations

import atexit
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


class MetricsStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: list[tuple[float, str, int, Optional[str]]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._retention_days = int(os.getenv("METRICS_RETENTION_DAYS", "30"))
        self._last_cleanup = 0.0
        self._init_db()
        self._thread.start()
        atexit.register(self.close)

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path, timeout=2.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS request_logs (
                    ts REAL NOT NULL,
                    service TEXT NOT NULL,
                    status INTEGER NOT NULL,
                    tool_name TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_ts ON request_logs (ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_service_ts ON request_logs (service, ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_tool_ts ON request_logs (tool_name, ts)")
            conn.commit()

    def record(self, service: str, status: int, tool_name: Optional[str]) -> None:
        now = time.time()
        with self._lock:
            self._queue.append((now, service, status, tool_name))
            if len(self._queue) >= 200:
                self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._queue:
            return
        batch = self._queue
        self._queue = []
        self._write_batch(batch)

    def _write_batch(self, batch: list[tuple[float, str, int, Optional[str]]]) -> None:
        tries = 0
        while True:
            try:
                with sqlite3.connect(self._db_path, timeout=2.0) as conn:
                    conn.executemany(
                        "INSERT INTO request_logs (ts, service, status, tool_name) VALUES (?, ?, ?, ?)",
                        batch,
                    )
                    conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and tries < 3:
                    tries += 1
                    time.sleep(0.05 * tries)
                    continue
                return

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(1.0)
            with self._lock:
                self._flush_locked()
            self._maybe_cleanup()

    def _maybe_cleanup(self) -> None:
        # Run cleanup at most once per hour
        now = time.time()
        if now - self._last_cleanup < 3600:
            return
        self._last_cleanup = now
        cutoff = now - (self._retention_days * 24 * 60 * 60)
        try:
            with sqlite3.connect(self._db_path, timeout=2.0) as conn:
                conn.execute("DELETE FROM request_logs WHERE ts < ?", (cutoff,))
                conn.commit()
        except sqlite3.OperationalError:
            pass

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._flush_locked()

    def _count_requests(self, service: str, since: float) -> tuple[int, int]:
        with sqlite3.connect(self._db_path, timeout=2.0) as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) as errors
                FROM request_logs
                WHERE service = ? AND ts >= ?
                """,
                (service, since),
            )
            total, errors = cursor.fetchone()
            return int(total or 0), int(errors or 0)

    def _count_tool_calls(self, since: float) -> tuple[int, int]:
        with sqlite3.connect(self._db_path, timeout=2.0) as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status >= 400 THEN 1 ELSE 0 END) as errors
                FROM request_logs
                WHERE tool_name IS NOT NULL AND ts >= ?
                """,
                (since,),
            )
            total, errors = cursor.fetchone()
            return int(total or 0), int(errors or 0)

    def get_metrics(self) -> dict[str, Any]:
        now = time.time()
        windows = {
            "last_5m": now - 5 * 60,
            "last_1h": now - 60 * 60,
            "last_24h": now - 24 * 60 * 60,
            "last_7d": now - 7 * 24 * 60 * 60,
        }
        services = {}
        for service in ["openapi", "mcp", "web"]:
            rates = {}
            for key, since in windows.items():
                total, errors = self._count_requests(service, since)
                error_rate = (errors / total * 100.0) if total else 0.0
                rates[key] = {
                    "requests": total,
                    "errors": errors,
                    "error_rate": round(error_rate, 2),
                }
            services[service] = rates

        tool_calls = {}
        for key, since in windows.items():
            total, errors = self._count_tool_calls(since)
            tool_calls[key] = {
                "total": total,
                "success": total - errors,
                "error": errors,
            }

        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
            "services": services,
            "tool_calls": tool_calls,
        }


_metrics_store: Optional[MetricsStore] = None


def init_metrics_store(data_dir: str) -> MetricsStore:
    global _metrics_store
    if _metrics_store is None:
        db_path = Path(data_dir) / "metrics.sqlite"
        _metrics_store = MetricsStore(db_path)
    return _metrics_store


def get_metrics_store() -> Optional[MetricsStore]:
    return _metrics_store
