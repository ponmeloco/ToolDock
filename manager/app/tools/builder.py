from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.config import ManagerSettings
from app.core_client import CoreClient
from app.repo.analyze import analyze_repository, read_repo_file
from app.repo.clone import ensure_cloned
from app.tools.common import data_paths
from app.tools.tool_files import ToolFileTools


class BuilderTools:
    def __init__(self, settings: ManagerSettings):
        self._settings = settings
        self._paths = data_paths(settings)
        self._core = CoreClient(settings)
        self._tool_files = ToolFileTools(settings)

    def analyze_repo(self, repo_url: str) -> dict[str, Any]:
        path = ensure_cloned(self._paths["repos"], repo_url)
        return analyze_repository(path, repo_url)

    def read_repo_file(self, repo_url: str, path: str) -> dict[str, Any]:
        repo_path = ensure_cloned(self._paths["repos"], repo_url)
        return read_repo_file(repo_path, path)

    def generate_tool(self, namespace: str, filename: str, code: str) -> dict[str, Any]:
        return self._tool_files.write_tool(namespace, filename, code)

    async def test_tool(self, namespace: str, tool_name: str, input: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._settings.bearer_token}",
            "X-Namespace": namespace,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{self._settings.core_url}/tools/{tool_name}",
                headers=headers,
                json=input,
            )
        if response.is_error:
            return {
                "success": False,
                "error": response.text,
                "status_code": response.status_code,
            }
        return {"success": True, "result": response.json()}

    def install_pip_packages(self, packages: list[str]) -> dict[str, Any]:
        if not packages:
            return {"installed": True, "packages": []}

        try:
            subprocess.run(
                ["python", "-m", "pip", "install", "--disable-pip-version-check", *packages],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            return {
                "installed": False,
                "packages": packages,
                "error": (exc.stderr or exc.stdout or str(exc))[-4000:],
            }

        return {"installed": True, "packages": packages}

    async def reload_core(self) -> dict[str, Any]:
        return await self._core.reload_core()
