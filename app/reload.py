"""
Hot Reload Module for ToolDock.

Provides functionality to reload tools at runtime without restarting the server.
Supports:
- Reload all tools in a namespace
- Reload all native namespaces
- Optional file watching for auto-reload
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from app.loader import load_tools_from_directory, discover_namespaces

if TYPE_CHECKING:
    from app.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ReloadResult:
    """Result of a reload operation."""

    namespace: str
    tools_unloaded: int
    tools_loaded: int
    success: bool
    error: Optional[str] = None


class ToolReloader:
    """
    Handles hot reloading of tools at runtime.

    Provides methods to reload tools from a namespace directory
    while maintaining registry consistency.
    """

    def __init__(
        self,
        registry: "ToolRegistry",
        tools_dir: str,
        external_namespaces: Optional[Set[str]] = None,
    ):
        """
        Initialize the ToolReloader.

        Args:
            registry: The tool registry to manage
            tools_dir: Base directory containing namespace folders
            external_namespaces: Set of namespace names that are external
                                (managed by external servers, not reloadable)
        """
        self.registry = registry
        self.tools_dir = Path(tools_dir)
        self._external_namespaces = external_namespaces or set()
        self._file_hashes: Dict[str, str] = {}

    def reload_namespace(self, namespace: str) -> ReloadResult:
        """
        Reload all tools in a specific namespace.

        This will:
        1. Unregister all tools currently in the namespace
        2. Clear Python module cache for the namespace
        3. Re-import and register tools from the namespace directory

        Args:
            namespace: The namespace to reload

        Returns:
            ReloadResult with details of the operation
        """
        logger.info(f"Reloading namespace: {namespace}")

        # Check if namespace is external (not reloadable)
        if namespace in self._external_namespaces:
            logger.warning(f"Cannot reload external namespace: {namespace}")
            return ReloadResult(
                namespace=namespace,
                tools_unloaded=0,
                tools_loaded=0,
                success=False,
                error=f"Namespace '{namespace}' is managed by an external server",
            )

        # Check if namespace directory exists
        namespace_dir = self.tools_dir / namespace
        if not namespace_dir.exists():
            logger.warning(f"Namespace directory not found: {namespace_dir}")
            return ReloadResult(
                namespace=namespace,
                tools_unloaded=0,
                tools_loaded=0,
                success=False,
                error=f"Namespace directory not found: {namespace_dir}",
            )

        try:
            # 1. Get current tools in namespace and unregister them
            tools_unloaded = self._unregister_namespace_tools(namespace)

            # 2. Clear Python module cache for this namespace
            self._clear_module_cache(namespace)

            # 3. Reload tools from directory
            tools_loaded = load_tools_from_directory(
                self.registry,
                str(namespace_dir),
                recursive=False,
                namespace=namespace,
            )

            logger.info(
                f"Reloaded namespace '{namespace}': "
                f"{tools_unloaded} unloaded, {tools_loaded} loaded"
            )

            return ReloadResult(
                namespace=namespace,
                tools_unloaded=tools_unloaded,
                tools_loaded=tools_loaded,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to reload namespace '{namespace}': {e}", exc_info=True)
            return ReloadResult(
                namespace=namespace,
                tools_unloaded=0,
                tools_loaded=0,
                success=False,
                error=str(e),
            )

    def reload_all(self) -> List[ReloadResult]:
        """
        Reload all native (non-external) namespaces.

        Returns:
            List of ReloadResult for each namespace
        """
        logger.info("Reloading all native namespaces")
        results: List[ReloadResult] = []

        # Get all namespaces from registry that are native
        all_namespaces = set(self.registry.list_namespaces())

        # Also discover namespaces from filesystem that might not be loaded yet
        discovered = set(discover_namespaces(str(self.tools_dir)))

        # Combine both sets, excluding external namespaces
        namespaces_to_reload = (all_namespaces | discovered) - self._external_namespaces

        for namespace in sorted(namespaces_to_reload):
            result = self.reload_namespace(namespace)
            results.append(result)

        successful = sum(1 for r in results if r.success)
        logger.info(
            f"Reload complete: {successful}/{len(results)} namespaces successful"
        )

        return results

    def _unregister_namespace_tools(self, namespace: str) -> int:
        """
        Unregister all tools in a namespace.

        Args:
            namespace: The namespace to clear

        Returns:
            Number of tools unregistered
        """
        # Get tools in this namespace
        tools = self.registry.list_tools_for_namespace(namespace)
        count = 0

        for tool_info in tools:
            tool_name = tool_info["name"]
            if self.registry.unregister_tool(tool_name):
                count += 1
                logger.debug(f"Unregistered tool: {tool_name}")

        return count

    def _clear_module_cache(self, namespace: str) -> None:
        """
        Remove cached Python modules for a namespace.

        This is necessary to ensure that modified code is actually
        reloaded instead of using cached imports.

        Args:
            namespace: The namespace to clear from cache
        """
        import importlib

        # Module names follow the pattern: tools_{namespace}_{module_name}
        prefix = f"tools_{namespace}_"
        modules_to_remove = [
            name for name in list(sys.modules.keys())
            if name.startswith(prefix)
        ]

        for module_name in modules_to_remove:
            del sys.modules[module_name]
            logger.debug(f"Cleared module from cache: {module_name}")

        if modules_to_remove:
            logger.debug(
                f"Cleared {len(modules_to_remove)} modules from cache for namespace: {namespace}"
            )

        # Also invalidate importlib caches
        importlib.invalidate_caches()

    def is_native_namespace(self, namespace: str) -> bool:
        """
        Check if a namespace is native (reloadable) vs external.

        Args:
            namespace: The namespace to check

        Returns:
            True if the namespace is native, False if external
        """
        return namespace not in self._external_namespaces

    def set_external_namespaces(self, namespaces: Set[str]) -> None:
        """
        Update the set of external namespaces.

        Args:
            namespaces: Set of namespace names that are external
        """
        self._external_namespaces = namespaces


# Global reloader instance
_global_reloader: Optional[ToolReloader] = None


def get_reloader() -> Optional[ToolReloader]:
    """Get the global ToolReloader instance."""
    return _global_reloader


def init_reloader(
    registry: "ToolRegistry",
    tools_dir: str,
    external_namespaces: Optional[Set[str]] = None,
) -> ToolReloader:
    """
    Initialize the global ToolReloader.

    Args:
        registry: The tool registry
        tools_dir: Base directory for tool namespaces
        external_namespaces: Optional set of external namespace names

    Returns:
        The initialized ToolReloader instance
    """
    global _global_reloader
    _global_reloader = ToolReloader(registry, tools_dir, external_namespaces)
    logger.info(f"Initialized ToolReloader with tools_dir: {tools_dir}")
    return _global_reloader


def reset_reloader() -> None:
    """Reset the global reloader (primarily for testing)."""
    global _global_reloader
    _global_reloader = None
