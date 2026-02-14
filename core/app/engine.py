from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.registry.models import NamespaceInfo, ToolEntry
from app.registry.scanner import scan_namespaces
from app.secrets import SecretsStore
from app.workers.protocol import WorkerError
from app.workers.supervisor import WorkerSupervisor


class NamespaceNotFound(Exception):
    pass


class ToolNotFound(Exception):
    pass


class ToolEngine:
    def __init__(self, data_dir: Path, secrets: SecretsStore, supervisor: WorkerSupervisor):
        self._data_dir = data_dir
        self._tools_dir = data_dir / "tools"
        self._secrets = secrets
        self._supervisor = supervisor

        self._namespaces: dict[str, NamespaceInfo] = {}
        self._tool_index: dict[str, dict[str, ToolEntry]] = {}
        self._lock = asyncio.Lock()

    async def reload(self) -> dict[str, Any]:
        async with self._lock:
            self._secrets.load()

            namespaces = scan_namespaces(self._tools_dir)
            tool_index = {
                ns_name: {entry.name: entry for entry in info.tools}
                for ns_name, info in namespaces.items()
            }

            env_by_ns = {ns_name: self._secrets.get_env(ns_name) for ns_name in namespaces}
            summary = await self._supervisor.apply_snapshot(namespaces, env_by_ns)

            self._namespaces = namespaces
            self._tool_index = tool_index

            return {
                "reloaded": True,
                "namespaces": sorted(self._namespaces),
                "workers_restarted": summary["workers_restarted"],
                "deps_synced": summary["deps_synced"],
            }

    async def list_namespaces(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for ns_name, info in sorted(self._namespaces.items()):
            check = self._secrets.check_namespace_requirements(ns_name)
            if check["missing"]:
                secrets_status = "missing"
            elif check["placeholders"]:
                secrets_status = "placeholders"
            elif check["satisfied"]:
                secrets_status = "ok"
            else:
                secrets_status = "no_secrets_needed"

            result.append(
                {
                    "name": ns_name,
                    "tool_count": info.tool_count,
                    "has_requirements": bool(info.requirements_path),
                    "secrets_status": secrets_status,
                }
            )
        return result

    async def list_tools(self, namespace: str) -> list[dict[str, Any]]:
        self._require_namespace(namespace)
        tools = self._tool_index.get(namespace, {})
        return [
            {
                "name": entry.name,
                "description": entry.description,
                "filename": entry.filename,
            }
            for entry in sorted(tools.values(), key=lambda t: t.name)
        ]

    async def list_mcp_tools(self, namespace: str) -> list[dict[str, Any]]:
        self._require_namespace(namespace)
        return await self._supervisor.list_tools(namespace)

    async def get_schema(self, namespace: str, tool_name: str) -> dict[str, Any]:
        self._require_tool(namespace, tool_name)
        return await self._supervisor.get_schema(namespace, tool_name)

    async def call_tool(self, namespace: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        self._require_tool(namespace, tool_name)
        try:
            return await self._supervisor.call_tool(namespace, tool_name, arguments)
        except WorkerError as exc:
            raise exc

    def _require_namespace(self, namespace: str) -> None:
        if namespace not in self._namespaces:
            raise NamespaceNotFound(f"Unknown namespace: {namespace}")

    def _require_tool(self, namespace: str, tool_name: str) -> None:
        self._require_namespace(namespace)
        tools = self._tool_index.get(namespace, {})
        if tool_name not in tools:
            raise ToolNotFound(f"Unknown tool '{tool_name}' in namespace '{namespace}'")
