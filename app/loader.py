from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from app.registry import ToolRegistry

logger = logging.getLogger("loader")


def _import_module_from_path(py_file: Path):
    module_name = py_file.stem
    unique_name = f"tools_{py_file.parent.name}_{module_name}"
    spec = importlib.util.spec_from_file_location(unique_name, py_file)
    if not spec or not spec.loader:
        raise RuntimeError(f"Cannot import tool module: {py_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_tools_from_directory(registry: ToolRegistry, tools_dir: str, recursive: bool = True) -> None:
    tools_path = Path(tools_dir)
    if not tools_path.exists() or not tools_path.is_dir():
        raise RuntimeError(f"TOOLS_DIR not found or not a directory: {tools_dir}")

    logger.info(f"Scanning for tools in: {tools_path} (recursive={recursive})")

    pattern = "**/*.py" if recursive else "*.py"

    files = sorted(
        [p for p in tools_path.glob(pattern) if p.is_file() and not p.name.startswith("_")]
    )

    for py_file in files:
        module = _import_module_from_path(py_file)

        if not hasattr(module, "register_tools") or not callable(module.register_tools):
            logger.info(f"Skipping {py_file}: no register_tools(registry) found")
            continue

        module.register_tools(registry)
        logger.info(f"Registered tools from module: {py_file}")
