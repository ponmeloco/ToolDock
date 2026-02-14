from __future__ import annotations

import subprocess
import venv
from pathlib import Path
from typing import Any

from app.config import ManagerSettings
from app.tools.common import data_paths, validate_namespace_name


class DependencyTools:
    def __init__(self, settings: ManagerSettings):
        self._paths = data_paths(settings)
        self._paths["tools"].mkdir(parents=True, exist_ok=True)
        self._paths["venvs"].mkdir(parents=True, exist_ok=True)

    def list_requirements(self, namespace: str) -> dict[str, Any]:
        validate_namespace_name(namespace)
        req = self._requirements_path(namespace)
        if not req.exists():
            return {"namespace": namespace, "packages": []}

        packages = [line.strip() for line in req.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {"namespace": namespace, "packages": packages}

    def add_requirement(self, namespace: str, package: str) -> dict[str, Any]:
        validate_namespace_name(namespace)
        req = self._requirements_path(namespace)
        req.parent.mkdir(parents=True, exist_ok=True)

        lines = [line.strip() for line in req.read_text(encoding="utf-8").splitlines()] if req.exists() else []
        if package not in lines:
            lines.append(package)
        req.write_text("\n".join(line for line in lines if line) + "\n", encoding="utf-8")

        self.install_requirements(namespace)
        return {"added": True, "package": package, "namespace": namespace}

    def install_requirements(self, namespace: str) -> dict[str, Any]:
        validate_namespace_name(namespace)
        req = self._requirements_path(namespace)
        if not req.exists():
            return {"installed": True, "namespace": namespace, "packages": []}

        venv_dir = self._paths["venvs"] / namespace
        python_bin = venv_dir / "bin" / "python"
        if not python_bin.exists():
            venv.create(venv_dir, with_pip=True, clear=False)

        packages = [line.strip() for line in req.read_text(encoding="utf-8").splitlines() if line.strip()]
        try:
            result = subprocess.run(
                [str(python_bin), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            return {
                "installed": False,
                "error": "pip install failed",
                "details": (exc.stderr or exc.stdout or str(exc))[-4000:],
            }

        return {
            "installed": True,
            "namespace": namespace,
            "packages": packages,
            "output": result.stdout[-4000:],
        }

    def _requirements_path(self, namespace: str) -> Path:
        ns_path = self._paths["tools"] / namespace
        if not ns_path.exists() or not ns_path.is_dir():
            raise ValueError(f"Unknown namespace: {namespace}")
        return ns_path / "requirements.txt"
