from __future__ import annotations

from typing import Any

from app.config import ManagerSettings
from app.tools.builder import BuilderTools


_REGISTRY = [
    {
        "name": "server-github",
        "description": "GitHub API tools",
        "package": "@modelcontextprotocol/server-github",
        "package_type": "npm",
        "source_url": "https://github.com/modelcontextprotocol/server-github",
    },
    {
        "name": "server-slack",
        "description": "Slack API tools",
        "package": "@modelcontextprotocol/server-slack",
        "package_type": "npm",
        "source_url": "https://github.com/modelcontextprotocol/server-slack",
    },
]


class InstallerTools:
    def __init__(self, settings: ManagerSettings):
        self._builder = BuilderTools(settings)

    def search_registry(self, query: str) -> list[dict[str, Any]]:
        q = query.lower().strip()
        return [item for item in _REGISTRY if q in item["name"].lower() or q in item["description"].lower()]

    def install_from_registry(self, package: str, namespace: str) -> dict[str, Any]:
        matches = [item for item in _REGISTRY if item["package"] == package]
        if not matches:
            raise ValueError(f"Package not found in registry: {package}")
        source_url = matches[0]["source_url"]
        analysis = self._builder.analyze_repo(source_url)
        analysis["target_namespace"] = namespace
        analysis["source"] = "registry"
        return analysis

    def install_from_repo(self, repo_url: str, namespace: str) -> dict[str, Any]:
        analysis = self._builder.analyze_repo(repo_url)
        analysis["target_namespace"] = namespace
        analysis["source"] = "repo"
        return analysis
