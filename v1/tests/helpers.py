from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "core"
MANAGER_ROOT = ROOT / "manager"


def import_core(module_name: str):
    _reset_app_modules()
    _ensure_path(CORE_ROOT)
    _drop_path(MANAGER_ROOT)
    return importlib.import_module(module_name)


def import_manager(module_name: str):
    _reset_app_modules()
    _ensure_path(MANAGER_ROOT)
    _drop_path(CORE_ROOT)
    return importlib.import_module(module_name)


def _reset_app_modules() -> None:
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            sys.modules.pop(key, None)


def _ensure_path(path: Path) -> None:
    raw = str(path)
    if raw not in sys.path:
        sys.path.insert(0, raw)


def _drop_path(path: Path) -> None:
    raw = str(path)
    while raw in sys.path:
        sys.path.remove(raw)
