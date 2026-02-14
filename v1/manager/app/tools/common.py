from __future__ import annotations

from pathlib import Path

from app.config import ManagerSettings


def data_paths(settings: ManagerSettings) -> dict[str, Path]:
    data_dir = Path(settings.data_dir)
    return {
        "data": data_dir,
        "tools": data_dir / "tools",
        "venvs": data_dir / "venvs",
        "repos": data_dir / "repos",
        "logs": data_dir / "logs",
        "meta": data_dir / "secrets.meta.yaml",
        "enc": data_dir / "secrets.enc",
        "lock": data_dir / "secrets.lock",
    }


def validate_namespace_name(name: str) -> None:
    import re

    if name == "_system":
        raise ValueError("_system is reserved")
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", name):
        raise ValueError("Namespace must be lowercase alphanumeric with optional hyphens")
