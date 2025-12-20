from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from app.errors import ToolNotFoundError, ToolValidationError

ToolHandler = Callable[[BaseModel], Awaitable[Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: Type[BaseModel]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> List[ToolDefinition]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def get(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if not tool:
            raise ToolNotFoundError(name)
        return tool

    async def call(self, name: str, raw_args: Optional[Dict[str, Any]] = None) -> Any:
        tool = self.get(name)
        raw_args = raw_args or {}

        try:
            model = tool.input_model.model_validate(raw_args)
        except Exception as e:
            raise ToolValidationError(
                message=f"Ungültige Parameter für Tool {name}",
                details={"error": str(e), "tool": name, "args": raw_args},
            ) from e

        return await tool.handler(model)
