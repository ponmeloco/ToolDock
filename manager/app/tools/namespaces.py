from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.config import ManagerSettings
from app.tools.common import data_paths, validate_namespace_name
from app.tools.secrets_store import ManagerSecretsStore


class NamespaceTools:
    def __init__(self, settings: ManagerSettings):
        self._settings = settings
        self._paths = data_paths(settings)
        self._secrets = ManagerSecretsStore(settings)
        self._paths["tools"].mkdir(parents=True, exist_ok=True)
        self._paths["venvs"].mkdir(parents=True, exist_ok=True)

    def list_namespaces(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in sorted(self._paths["tools"].iterdir(), key=lambda p: p.name):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name.startswith("_"):
                continue

            tool_count = len([p for p in entry.glob("*.py") if not p.name.startswith("_") and not p.name.startswith(".")])
            has_requirements = (entry / "requirements.txt").exists()
            check = self._secrets.check_namespace(entry.name)
            if check["missing"]:
                secrets_status = "missing"
            elif check["placeholders"]:
                secrets_status = "placeholders"
            elif check["satisfied"]:
                secrets_status = "ok"
            else:
                secrets_status = "no_secrets_needed"

            out.append(
                {
                    "name": entry.name,
                    "tool_count": tool_count,
                    "has_requirements": has_requirements,
                    "secrets_status": secrets_status,
                }
            )
        return out

    def create_namespace(self, name: str) -> dict[str, Any]:
        validate_namespace_name(name)
        ns_path = self._paths["tools"] / name
        if ns_path.exists():
            raise ValueError(f"Namespace already exists: {ns_path}")
        ns_path.mkdir(parents=True)
        return {"created": True, "path": str(ns_path)}

    def delete_namespace(self, name: str) -> dict[str, Any]:
        validate_namespace_name(name)
        ns_path = self._paths["tools"] / name
        if not ns_path.exists():
            raise ValueError(f"Namespace does not exist: {name}")

        shutil.rmtree(ns_path)

        venv_dir = self._paths["venvs"] / name
        if venv_dir.exists():
            shutil.rmtree(venv_dir)

        return {"deleted": True, "name": name}
