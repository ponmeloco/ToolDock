from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

from app.errors import ToolNotFoundError, ToolValidationError

ToolHandler = Callable[[BaseModel], Awaitable[Any]]

# Global registry instance (singleton)
_global_registry: Optional["ToolRegistry"] = None


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

    def get_tool_info(self, name: str) -> Dict[str, Any]:
        """
        Get tool information in a format suitable for MCP.

        Args:
            name: The tool name

        Returns:
            Dictionary with name, description, and input_schema

        Raises:
            ToolNotFoundError: If the tool doesn't exist
        """
        tool = self.get(name)
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_model.model_json_schema()
        }

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


def get_registry(namespace: str = "default") -> ToolRegistry:
    """
    Get the global registry singleton.

    This ensures both OpenAPI and MCP transports share the same
    registry instance with all registered tools.

    Args:
        namespace: Registry namespace (only used on first call)

    Returns:
        The global ToolRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry(namespace=namespace)
    return _global_registry


def reset_registry() -> None:
    """
    Reset the global registry.

    Primarily for testing purposes.
    """
    global _global_registry
    _global_registry = None
