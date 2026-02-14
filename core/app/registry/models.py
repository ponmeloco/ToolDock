from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ToolEntry:
    namespace: str
    name: str
    title: str
    description: str
    filename: str
    function_name: str
    module_path: Path
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None

    def to_mcp_tool(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.output_schema:
            payload["outputSchema"] = self.output_schema
        if self.annotations:
            payload["annotations"] = self.annotations
        return payload


@dataclass(slots=True)
class NamespaceInfo:
    name: str
    path: Path
    tools: list[ToolEntry] = field(default_factory=list)
    requirements_path: Path | None = None
    requirements_hash: str | None = None
    config_path: Path | None = None

    @property
    def tool_count(self) -> int:
        return len(self.tools)
