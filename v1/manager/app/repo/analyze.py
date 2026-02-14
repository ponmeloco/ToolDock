from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def analyze_repository(path: Path, repo_url: str) -> dict[str, Any]:
    files = [p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts]
    relative_files = [str(p.relative_to(path)) for p in files]

    language = _detect_language(files)
    framework = _detect_framework(path)
    tools_found = _detect_tools(files, path)
    dependencies = _detect_dependencies(path)
    apis_called = _detect_apis(files)
    secrets_needed = _detect_secrets(files)

    return {
        "repo_url": repo_url,
        "language": language,
        "framework": framework,
        "files": sorted(relative_files)[:500],
        "tools_found": tools_found,
        "dependencies": dependencies,
        "apis_called": sorted(apis_called),
        "secrets_needed": sorted(secrets_needed),
    }


def read_repo_file(path: Path, relative_path: str) -> dict[str, Any]:
    file_path = path / relative_path
    if not file_path.exists() or not file_path.is_file():
        raise ValueError(f"File not found in repo: {relative_path}")
    return {"path": relative_path, "content": file_path.read_text(encoding="utf-8", errors="replace")}


def _detect_language(files: list[Path]) -> str:
    counts = Counter(p.suffix.lower() for p in files if p.suffix)
    if not counts:
        return "unknown"
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".js": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".cs": "csharp",
    }
    suffix = counts.most_common(1)[0][0]
    return mapping.get(suffix, suffix.lstrip("."))


def _detect_framework(path: Path) -> str:
    if (path / "package.json").exists():
        pkg = json.loads((path / "package.json").read_text(encoding="utf-8", errors="replace"))
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        if "@modelcontextprotocol/sdk" in deps:
            return "mcp-sdk"
        if "fastify" in deps:
            return "fastify"
        if "express" in deps:
            return "express"
    if (path / "pyproject.toml").exists():
        text = (path / "pyproject.toml").read_text(encoding="utf-8", errors="replace").lower()
        if "fastapi" in text:
            return "fastapi"
    return "unknown"


def _detect_tools(files: list[Path], root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for file_path in files:
        if file_path.suffix.lower() not in {".py", ".ts", ".js", ".go", ".rs"}:
            continue
        text = file_path.read_text(encoding="utf-8", errors="replace")

        for match in re.finditer(r"(def|function|async\s+function)\s+([a-zA-Z0-9_]+)", text):
            name = match.group(2)
            if any(token in name.lower() for token in ("tool", "list_", "get_", "create_", "delete_", "update_")):
                out.append(
                    {
                        "name": name,
                        "file": str(file_path.relative_to(root)),
                        "description": "Candidate tool function",
                        "parameters": [],
                    }
                )
        if len(out) > 100:
            break
    return out[:100]


def _detect_dependencies(path: Path) -> dict[str, str]:
    deps: dict[str, str] = {}

    req = path / "requirements.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            deps[line] = ""

    pkg = path / "package.json"
    if pkg.exists():
        data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
        for key, value in (data.get("dependencies") or {}).items():
            deps[key] = str(value)

    return deps


def _detect_apis(files: list[Path]) -> set[str]:
    hosts: set[str] = set()
    pattern = re.compile(r"https?://([a-zA-Z0-9.-]+)")
    for file_path in files:
        if file_path.suffix.lower() not in {".py", ".ts", ".js", ".json", ".yaml", ".yml"}:
            continue
        text = file_path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.findall(text):
            hosts.add(match.lower())
        if len(hosts) > 100:
            break
    return hosts


def _detect_secrets(files: list[Path]) -> set[str]:
    found: set[str] = set()
    pattern = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
    hints = ("TOKEN", "KEY", "SECRET", "PASSWORD")
    for file_path in files:
        if file_path.suffix.lower() not in {".py", ".ts", ".js", ".env", ".yaml", ".yml"}:
            continue
        text = file_path.read_text(encoding="utf-8", errors="replace")
        for candidate in pattern.findall(text):
            if any(h in candidate for h in hints):
                found.add(candidate)
        if len(found) > 200:
            break
    return found
