"""
Dependency management for ToolDock tool namespaces.

Provides per-namespace virtual environments stored under DATA_DIR/venvs.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PKG_PATTERN = re.compile(r"^[A-Za-z0-9_.@+/:=<>!~\\-]+$")


def _get_data_dir() -> Path:
    data_dir = os.getenv("DATA_DIR", "tooldock_data")
    return Path(data_dir)


def get_venv_dir(namespace: str) -> Path:
    return _get_data_dir() / "venvs" / namespace


def get_requirements_path(namespace: str) -> Path:
    return get_venv_dir(namespace) / "requirements.txt"


def get_site_packages_path(venv_dir: Path) -> Path:
    """
    Compute site-packages path for a given venv directory.
    """
    return Path(
        sysconfig.get_path(
            "purelib",
            vars={"base": str(venv_dir), "platbase": str(venv_dir)},
        )
    )


def ensure_venv(namespace: str) -> Path:
    """
    Ensure a venv exists for a namespace.
    """
    venv_dir = get_venv_dir(namespace)
    if (venv_dir / "bin" / "python").exists():
        return venv_dir

    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Creating venv for namespace '{namespace}' at {venv_dir}")
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create venv: {result.stderr.strip() or result.stdout.strip()}"
        )
    return venv_dir


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / "bin" / "python"


def install_packages(namespace: str, packages: List[str]) -> Dict[str, Any]:
    """
    Install pip packages into the namespace venv.
    """
    if not packages:
        raise ValueError("No packages provided")

    for pkg in packages:
        if not pkg or not _PKG_PATTERN.match(pkg):
            raise ValueError(f"Invalid package spec: {pkg}")

    venv_dir = ensure_venv(namespace)
    cmd = [str(_venv_python(venv_dir)), "-m", "pip", "install"] + packages
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def install_requirements(namespace: str, requirements_text: str) -> Dict[str, Any]:
    """
    Install packages from requirements.txt content into the namespace venv.
    """
    venv_dir = ensure_venv(namespace)
    req_path = get_requirements_path(namespace)
    req_path.write_text(requirements_text, encoding="utf-8")

    cmd = [str(_venv_python(venv_dir)), "-m", "pip", "install", "-r", str(req_path)]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def list_packages(namespace: str) -> List[Dict[str, str]]:
    """
    List installed packages for the namespace venv.
    """
    venv_dir = get_venv_dir(namespace)
    python_path = _venv_python(venv_dir)
    if not python_path.exists():
        return []

    cmd = [str(python_path), "-m", "pip", "list", "--format=json"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return []

    try:
        import json

        data = json.loads(result.stdout)
        return [
            {"name": p.get("name", ""), "version": p.get("version", "")}
            for p in data
        ]
    except Exception:
        return []


def read_requirements(namespace: str) -> Optional[str]:
    req_path = get_requirements_path(namespace)
    if req_path.exists():
        return req_path.read_text(encoding="utf-8")
    return None
