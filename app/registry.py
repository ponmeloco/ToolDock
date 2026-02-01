from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Set, Type

from pydantic import BaseModel

from app.errors import ToolNotFoundError, ToolTimeoutError, ToolValidationError
from app.utils import get_request_id, set_request_context

if TYPE_CHECKING:
    from app.external.proxy import MCPServerProxy

logger = logging.getLogger(__name__)

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
    """
    Central registry for all tools (native and external).

    Supports namespace-based organization:
    - Native tools are organized by folder (shared/, team1/, etc.)
    - External MCP servers each get their own namespace (github, mssql, etc.)
    """

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        self._tools: Dict[str, ToolDefinition] = {}
        self._external_tools: Dict[str, Dict[str, Any]] = {}
        # Namespace support: maps namespace -> set of tool names
        self._namespaces: Dict[str, Set[str]] = {}
        # Track which namespace each tool belongs to
        self._tool_namespaces: Dict[str, str] = {}

    def register(self, tool: ToolDefinition, namespace: Optional[str] = None) -> None:
        """
        Register a native tool.

        Args:
            tool: The tool definition to register
            namespace: Optional namespace (defaults to 'shared')
        """
        ns = namespace or "shared"
        self._tools[tool.name] = tool
        self._add_to_namespace(tool.name, ns)
        logger.debug(f"Registered native tool: {tool.name} in namespace: {ns}")

    def _add_to_namespace(self, tool_name: str, namespace: str) -> None:
        """Add a tool to a namespace."""
        if namespace not in self._namespaces:
            self._namespaces[namespace] = set()
        self._namespaces[namespace].add(tool_name)
        self._tool_namespaces[tool_name] = namespace

    def _remove_from_namespace(self, tool_name: str) -> None:
        """Remove a tool from its namespace."""
        if tool_name in self._tool_namespaces:
            ns = self._tool_namespaces[tool_name]
            if ns in self._namespaces:
                self._namespaces[ns].discard(tool_name)
                # Clean up empty namespaces
                if not self._namespaces[ns]:
                    del self._namespaces[ns]
            del self._tool_namespaces[tool_name]

    # ==================== Namespace Methods ====================

    def has_namespace(self, namespace: str) -> bool:
        """Check if a namespace exists (native or external)."""
        return namespace in self._namespaces

    def list_namespaces(self) -> List[str]:
        """List all available namespaces."""
        return sorted(self._namespaces.keys())

    def list_tools_for_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """
        Get all tools for a specific namespace in MCP format.

        Args:
            namespace: The namespace to filter by

        Returns:
            List of tool info dicts formatted for MCP
        """
        if namespace not in self._namespaces:
            return []

        tool_names = self._namespaces[namespace]
        tools: List[Dict[str, Any]] = []

        for name in tool_names:
            if name in self._tools:
                definition = self._tools[name]
                tools.append({
                    "name": name,
                    "description": definition.description,
                    "inputSchema": definition.input_model.model_json_schema(),
                })
            elif name in self._external_tools:
                ext_tool = self._external_tools[name]
                tools.append({
                    "name": name,
                    "description": ext_tool["description"],
                    "inputSchema": ext_tool["inputSchema"],
                })

        return sorted(tools, key=lambda t: t["name"])

    def tool_in_namespace(self, tool_name: str, namespace: str) -> bool:
        """Check if a tool belongs to a specific namespace."""
        return (
            namespace in self._namespaces
            and tool_name in self._namespaces[namespace]
        )

    def get_tool_namespace(self, tool_name: str) -> Optional[str]:
        """Get the namespace a tool belongs to."""
        return self._tool_namespaces.get(tool_name)

    # ==================== Original Methods ====================

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
        # Check external tools first
        if name in self._external_tools:
            ext_tool = self._external_tools[name]
            return {
                "name": ext_tool["name"],
                "description": ext_tool["description"],
                "input_schema": ext_tool["inputSchema"],
                "type": "external",
            }

        # Native tool
        tool = self.get(name)
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_model.model_json_schema(),
            "type": "native",
        }

    def has_tool(self, name: str) -> bool:
        """Check if a tool exists (native or external)."""
        return name in self._tools or name in self._external_tools

    async def call(self, name: str, raw_args: Optional[Dict[str, Any]] = None) -> Any:
        """
        Execute a tool by name.

        Args:
            name: Tool name
            raw_args: Tool arguments

        Returns:
            Tool execution result

        Raises:
            ToolNotFoundError: If tool doesn't exist
            ToolValidationError: If arguments are invalid
            ToolTimeoutError: If execution exceeds timeout
        """
        raw_args = raw_args or {}

        # Get timeout from environment (default 30 seconds)
        timeout = float(os.getenv("TOOL_TIMEOUT_SECONDS", "30"))

        # Set tool name in request context for logging
        set_request_context(tool_name=name)
        request_id = get_request_id()
        logger.info(f"[{request_id}/{name}] Executing tool with args: {list(raw_args.keys())}")

        # Check external tools first (prefixed names like "github:create_repo")
        if name in self._external_tools:
            return await self._call_with_timeout(
                self._call_external_tool(name, raw_args),
                name,
                timeout,
            )

        # Native tool
        tool = self.get(name)

        try:
            model = tool.input_model.model_validate(raw_args)
        except Exception as e:
            raise ToolValidationError(
                message=f"Ungültige Parameter für Tool {name}",
                details={"error": str(e), "tool": name, "args": raw_args},
            ) from e

        return await self._call_with_timeout(tool.handler(model), name, timeout)

    async def _call_with_timeout(self, coro: Any, tool_name: str, timeout: float) -> Any:
        """Execute a coroutine with timeout."""
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            request_id = get_request_id()
            logger.error(f"[{request_id}/{tool_name}] Tool execution timed out after {timeout}s")
            raise ToolTimeoutError(tool_name, timeout)

    async def _call_external_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute an external tool via its proxy."""
        tool_info = self._external_tools[name]
        proxy: "MCPServerProxy" = tool_info["proxy"]
        original_name = tool_info["original_name"]

        logger.debug(f"Calling external tool {name} -> {proxy.server_id}:{original_name}")

        result = await proxy.call_tool(original_name, arguments)
        return result

    def register_external_tool(
        self,
        name: str,
        description: str,
        schema: Dict[str, Any],
        server_id: str,
        original_name: str,
        proxy: "MCPServerProxy",
        namespace: Optional[str] = None,
    ) -> None:
        """
        Register a tool from an external MCP server.

        Args:
            name: Tool name (can be original name if using namespace routing)
            description: Tool description
            schema: JSON Schema for input
            server_id: External server identifier
            original_name: Original tool name on the server
            proxy: MCPServerProxy instance for execution
            namespace: Namespace for this tool (defaults to server_id)
        """
        ns = namespace or server_id
        self._external_tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": schema,
            "server_id": server_id,
            "original_name": original_name,
            "proxy": proxy,
            "type": "external",
        }
        self._add_to_namespace(name, ns)
        logger.info(f"Registered external tool: {name} in namespace: {ns}")

    def unregister_tool(self, name: str) -> bool:
        """
        Remove a tool from the registry.

        Args:
            name: Tool name to remove

        Returns:
            True if removed, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            self._remove_from_namespace(name)
            logger.info(f"Unregistered native tool: {name}")
            return True
        elif name in self._external_tools:
            del self._external_tools[name]
            self._remove_from_namespace(name)
            logger.info(f"Unregistered external tool: {name}")
            return True
        return False

    def list_all(self) -> List[Dict[str, Any]]:
        """
        List all tools (native and external) in a unified format.

        Returns:
            List of tool info dicts with type field
        """
        all_tools: List[Dict[str, Any]] = []

        # Native tools
        for name, definition in self._tools.items():
            all_tools.append({
                "name": name,
                "description": definition.description,
                "inputSchema": definition.input_model.model_json_schema(),
                "type": "native",
                "namespace": self._tool_namespaces.get(name, "shared"),
            })

        # External tools
        for tool_info in self._external_tools.values():
            name = tool_info["name"]
            all_tools.append({
                "name": name,
                "description": tool_info["description"],
                "inputSchema": tool_info["inputSchema"],
                "type": "external",
                "server": tool_info["server_id"],
                "namespace": self._tool_namespaces.get(name, tool_info["server_id"]),
            })

        return sorted(all_tools, key=lambda t: t["name"])

    def get_external_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Get external tool info by name."""
        return self._external_tools.get(name)

    def get_stats(self) -> Dict[str, Any]:
        """Get tool statistics including namespace information."""
        namespace_stats = {
            ns: len(tools) for ns, tools in self._namespaces.items()
        }
        return {
            "native": len(self._tools),
            "external": len(self._external_tools),
            "total": len(self._tools) + len(self._external_tools),
            "namespaces": len(self._namespaces),
            "namespace_breakdown": namespace_stats,
        }


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
