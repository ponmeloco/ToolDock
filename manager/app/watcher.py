from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from app.config import ManagerSettings
from app.core_client import CoreClient
from app.tools.common import data_paths


class FileSystemWatcher:
    def __init__(self, settings: ManagerSettings):
        self._settings = settings
        self._core = CoreClient(settings)
        self._paths = data_paths(settings)
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if not self._settings.enable_fs_watcher:
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task

    async def _run(self) -> None:
        tools_dir = self._paths["tools"]
        tools_dir.mkdir(parents=True, exist_ok=True)

        delay = max(self._settings.fs_watcher_debounce_ms, 200) / 1000.0
        last_hash = self._snapshot_hash(tools_dir)

        while not self._stop.is_set():
            await asyncio.sleep(delay)
            current = self._snapshot_hash(tools_dir)
            if current == last_hash:
                continue
            last_hash = current
            try:
                await self._core.reload_core()
            except Exception:  # noqa: BLE001
                # Watcher is best-effort; failures surface through explicit reload calls.
                pass

    def _snapshot_hash(self, tools_dir: Path) -> str:
        hasher = hashlib.sha256()
        if not tools_dir.exists():
            return ""

        for path in sorted(tools_dir.rglob("*"), key=lambda p: str(p)):
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            hasher.update(str(path.relative_to(tools_dir)).encode("utf-8"))
            if path.is_file():
                stat = path.stat()
                hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
                hasher.update(str(stat.st_size).encode("utf-8"))

        return hasher.hexdigest()
