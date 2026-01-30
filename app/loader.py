from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import List, Optional

from app.registry import ToolRegistry

logger = logging.getLogger("loader")


def _import_module_from_path(py_file: Path):
    """
    Import a Python module from its file path.

    Uses compile+exec to ensure fresh file content is loaded,
    avoiding importlib's source caching which prevents hot reload.

    Adds the module to sys.modules to support module introspection.
    """
    import sys
    import types

    module_name = py_file.stem
    # Create unique module name to avoid collisions
    unique_name = f"tools_{py_file.parent.name}_{module_name}"

    # Remove from sys.modules if already exists (for hot reload)
    if unique_name in sys.modules:
        del sys.modules[unique_name]

    # Read file content directly to avoid caching
    try:
        source_code = py_file.read_text(encoding="utf-8")
    except OSError as e:
        raise RuntimeError(f"Cannot read tool module: {py_file}") from e

    # Create module and compile/exec the code
    module = types.ModuleType(unique_name)
    module.__file__ = str(py_file)
    module.__loader__ = None
    module.__package__ = ""

    # Add to sys.modules BEFORE exec (required for submodule imports)
    sys.modules[unique_name] = module

    try:
        code = compile(source_code, str(py_file), "exec")
        exec(code, module.__dict__)
    except Exception:
        # Remove from sys.modules if exec fails
        del sys.modules[unique_name]
        raise

    return module


def load_tools_from_directory(
    registry: ToolRegistry,
    tools_dir: str,
    recursive: bool = True,
    namespace: Optional[str] = None,
) -> int:
    """
    Load tools from a directory.

    Args:
        registry: The tool registry to register tools with
        tools_dir: Path to the tools directory
        recursive: Whether to scan subdirectories
        namespace: Namespace to register tools under (defaults to folder name)

    Returns:
        Number of tool files loaded
    """
    tools_path = Path(tools_dir)
    if not tools_path.exists() or not tools_path.is_dir():
        logger.warning(f"Tools directory not found: {tools_dir}")
        return 0

    # Determine namespace from folder name if not provided
    ns = namespace or tools_path.name

    logger.info(f"Scanning for tools in: {tools_path} (namespace={ns}, recursive={recursive})")

    pattern = "**/*.py" if recursive else "*.py"

    files = sorted(
        [p for p in tools_path.glob(pattern) if p.is_file() and not p.name.startswith("_")]
    )

    loaded_count = 0
    for py_file in files:
        try:
            module = _import_module_from_path(py_file)

            if not hasattr(module, "register_tools") or not callable(module.register_tools):
                logger.debug(f"Skipping {py_file}: no register_tools(registry) found")
                continue

            # Create a namespace-aware wrapper for the registry
            wrapper = _NamespaceRegistryWrapper(registry, ns)
            module.register_tools(wrapper)
            loaded_count += 1
            logger.info(f"Registered tools from module: {py_file} (namespace={ns})")

        except Exception as e:
            logger.error(f"Failed to load tool from {py_file}: {e}", exc_info=True)

    return loaded_count


def load_tools_from_namespaces(
    registry: ToolRegistry,
    base_dir: str,
    namespaces: Optional[List[str]] = None,
) -> dict:
    """
    Load tools from multiple namespace directories.

    Each subdirectory of base_dir is treated as a namespace.
    Tools in that directory are registered under that namespace.

    Args:
        registry: The tool registry
        base_dir: Base directory containing namespace folders
        namespaces: Optional list of namespaces to load (loads all if None)

    Returns:
        Dictionary mapping namespace names to number of tools loaded
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        logger.warning(f"Base tools directory not found: {base_dir}")
        return {}

    results = {}

    # Get all subdirectories as potential namespaces
    if namespaces:
        namespace_dirs = [base_path / ns for ns in namespaces]
    else:
        namespace_dirs = [d for d in base_path.iterdir() if d.is_dir() and not d.name.startswith("_")]

    for ns_dir in sorted(namespace_dirs):
        if not ns_dir.exists():
            logger.warning(f"Namespace directory not found: {ns_dir}")
            continue

        namespace = ns_dir.name
        count = load_tools_from_directory(
            registry=registry,
            tools_dir=str(ns_dir),
            recursive=False,  # Don't recurse within namespace folders
            namespace=namespace,
        )
        results[namespace] = count
        logger.info(f"Loaded {count} tool file(s) from namespace '{namespace}'")

    return results


def discover_namespaces(base_dir: str) -> List[str]:
    """
    Discover available namespace directories.

    Args:
        base_dir: Base directory to scan

    Returns:
        List of namespace names (directory names)
    """
    base_path = Path(base_dir)
    if not base_path.exists():
        return []

    return sorted([
        d.name for d in base_path.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    ])


class _NamespaceRegistryWrapper:
    """
    Wrapper that adds namespace to tool registrations.

    This allows existing tool modules to work without modification
    while registering tools into the correct namespace.
    """

    def __init__(self, registry: ToolRegistry, namespace: str):
        self._registry = registry
        self._namespace = namespace

    def register(self, tool) -> None:
        """Register a tool in the wrapped namespace."""
        self._registry.register(tool, namespace=self._namespace)

    def __getattr__(self, name):
        """Forward all other attribute access to the real registry."""
        return getattr(self._registry, name)
