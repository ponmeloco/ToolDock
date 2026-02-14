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

    def get_tool_template(self, template_name: str = "fastmcp-basic") -> dict[str, Any]:
        normalized = template_name.strip().lower() or "fastmcp-basic"
        templates = _tool_templates()
        template = templates.get(normalized)
        if template is None:
            return {
                "ok": False,
                "error": f"Unknown template: {template_name}",
                "available_templates": sorted(templates.keys()),
            }

        return {
            "ok": True,
            "template_name": normalized,
            "available_templates": sorted(templates.keys()),
            **template,
        }

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
    uses_bare_tool_decorator = False

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _has_tool_decorator(node):
            continue

        tools.append(node.name)
        if _has_bare_tool_decorator(node):
            uses_bare_tool_decorator = True

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

    if uses_bare_tool_decorator and not _has_tool_symbol_binding(tree):
        return {
            "ok": False,
            "error": "Bare @tool decorator is not defined in this file",
            "details": "Add 'from fastmcp.tools import tool' or use FastMCP + @mcp.tool().",
        }

    return {"ok": True, "tools": tools}


def _has_tool_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "tool":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return True
    return False


def _has_bare_tool_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "tool":
            return True
    return False


def _has_tool_symbol_binding(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".", 1)[0]
                if bound_name == "tool":
                    return True
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_name = alias.asname or alias.name
                if bound_name == "tool":
                    return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == "tool":
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "tool":
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "tool":
                return True
    return False


def _tool_templates() -> dict[str, dict[str, Any]]:
    code = (
        "from mcp.server.fastmcp import FastMCP\n"
        "\n"
        "mcp = FastMCP(\"my_tools\")\n"
        "\n"
        "\n"
        "@mcp.tool()\n"
        "def ping(name: str = \"world\") -> str:\n"
        "    \"\"\"Return a simple greeting.\"\"\"\n"
        "    return f\"hello {name}\"\n"
    )
    return {
        "fastmcp-basic": {
            "description": "Recommended template using FastMCP instance decorators.",
            "filename_hint": "my_tool.py",
            "code": code,
            "notes": [
                "Keep one FastMCP instance per file.",
                "Decorate tools with @mcp.tool().",
                "Add type hints and docstrings for every tool function.",
            ],
        }
    }
