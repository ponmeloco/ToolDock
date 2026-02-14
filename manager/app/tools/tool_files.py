from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from app.config import ManagerSettings
from app.tools.common import data_paths, validate_namespace_name


class ToolFileTools:
    def __init__(self, settings: ManagerSettings):
        self._paths = data_paths(settings)
        self._paths["tools"].mkdir(parents=True, exist_ok=True)

    def list_tools(self, namespace: str) -> list[dict[str, Any]]:
        validate_namespace_name(namespace)
        ns_path = self._namespace_path(namespace)

        tools: list[dict[str, Any]] = []
        for file_path in sorted(ns_path.glob("*.py"), key=lambda p: p.name):
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _has_tool_decorator(node):
                    continue
                tools.append(
                    {
                        "name": node.name,
                        "description": ast.get_docstring(node) or "",
                        "filename": file_path.name,
                    }
                )
        return tools

    def get_tool_source(self, namespace: str, filename: str) -> dict[str, Any]:
        validate_namespace_name(namespace)
        file_path = self._resolve_py_file(namespace, filename)
        return {"filename": file_path.name, "source": file_path.read_text(encoding="utf-8")}

    def write_tool(self, namespace: str, filename: str, code: str) -> dict[str, Any]:
        validate_namespace_name(namespace)
        if not filename.endswith(".py"):
            return {"written": False, "error": "Filename must end with .py"}

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return {"written": False, "error": f"Syntax error: {exc.msg}", "details": str(exc)}

        validation = _validate_tool_file(tree)
        if validation["ok"] is False:
            return {"written": False, "error": validation["error"], "details": validation.get("details", "")}

        ns_path = self._namespace_path(namespace)
        file_path = ns_path / filename
        file_path.write_text(code, encoding="utf-8")

        return {
            "written": True,
            "filename": filename,
            "tools_found": validation["tools"],
        }

    def delete_tool(self, namespace: str, filename: str) -> dict[str, Any]:
        validate_namespace_name(namespace)
        file_path = self._resolve_py_file(namespace, filename)
        file_path.unlink(missing_ok=True)
        return {"deleted": True, "filename": filename}

    def _namespace_path(self, namespace: str) -> Path:
        path = self._paths["tools"] / namespace
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Unknown namespace: {namespace}")
        return path

    def _resolve_py_file(self, namespace: str, filename: str) -> Path:
        if "/" in filename or ".." in filename:
            raise ValueError("Invalid filename")
        path = self._namespace_path(namespace) / filename
        if not path.exists():
            raise ValueError(f"File not found: {filename}")
        if path.suffix != ".py":
            raise ValueError("File must be .py")
        return path


def _validate_tool_file(tree: ast.Module) -> dict[str, Any]:
    tools: list[str] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _has_tool_decorator(node):
            continue

        tools.append(node.name)

        if not ast.get_docstring(node):
            return {"ok": False, "error": f"Tool '{node.name}' must have a docstring"}

        for arg in node.args.args:
            if arg.arg in {"self", "cls"}:
                continue
            if arg.annotation is None:
                return {
                    "ok": False,
                    "error": f"Tool '{node.name}' has missing type hint",
                    "details": f"Parameter '{arg.arg}' has no annotation",
                }

    if not tools:
        return {"ok": False, "error": "No @tool decorator found"}

    return {"ok": True, "tools": tools}


def _has_tool_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "tool":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return True
    return False
