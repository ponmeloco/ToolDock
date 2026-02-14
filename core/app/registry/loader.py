from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from app.registry.models import ToolEntry


IGNORED_FILENAMES = {"requirements.txt", "tooldock.yaml", "README.md", "LICENSE"}


def load_tools_from_file(namespace: str, file_path: Path) -> list[ToolEntry]:
    if file_path.name in IGNORED_FILENAMES:
        return []

    if not file_path.name.endswith(".py"):
        return []

    if file_path.name.startswith(".") or file_path.name.startswith("_"):
        return []

    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tools: list[ToolEntry] = []

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _has_tool_decorator(node):
            continue

        description = ast.get_docstring(node) or ""
        input_schema = _build_input_schema(node)
        output_schema = _annotation_to_schema(node.returns) if node.returns else None
        title = node.name.replace("_", " ").title()

        tools.append(
            ToolEntry(
                namespace=namespace,
                name=node.name,
                title=title,
                description=description,
                filename=file_path.name,
                function_name=node.name,
                module_path=file_path,
                input_schema=input_schema,
                output_schema=output_schema,
                annotations={"source": file_path.name},
            )
        )

    return tools


def _has_tool_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name) and target.id == "tool":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return True
    return False


def _build_input_schema(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    args = node.args.args
    defaults = list(node.args.defaults)
    defaults_by_index: dict[int, ast.expr] = {}
    if defaults:
        start = len(args) - len(defaults)
        defaults_by_index = {start + i: defaults[i] for i in range(len(defaults))}

    for index, arg in enumerate(args):
        if arg.arg in {"self", "cls"}:
            continue

        schema = _annotation_to_schema(arg.annotation)
        schema["title"] = arg.arg.replace("_", " ").title()

        if index in defaults_by_index:
            default = _literal_or_none(defaults_by_index[index])
            schema["default"] = default
        else:
            required.append(arg.arg)

        properties[arg.arg] = schema

    payload: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        payload["required"] = required
    return payload


def _literal_or_none(node: ast.expr) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _annotation_to_schema(annotation: ast.expr | None) -> dict[str, Any]:
    if annotation is None:
        return {}

    if isinstance(annotation, ast.Name):
        return _basic_schema_for_name(annotation.id)

    if isinstance(annotation, ast.Subscript):
        base = _qualified_name(annotation.value)
        if base in {"list", "List"}:
            item_schema = _annotation_to_schema(annotation.slice)
            return {"type": "array", "items": item_schema or {}}
        if base in {"dict", "Dict"}:
            return {"type": "object"}
        if base in {"Optional", "typing.Optional"}:
            inner = _annotation_to_schema(annotation.slice)
            if not inner:
                return {}
            return {"anyOf": [inner, {"type": "null"}]}

    if isinstance(annotation, ast.Attribute):
        return _basic_schema_for_name(annotation.attr)

    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return _basic_schema_for_name(annotation.value)

    return {}


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _qualified_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _basic_schema_for_name(name: str) -> dict[str, Any]:
    normalized = name.lower()
    if normalized in {"str", "string"}:
        return {"type": "string"}
    if normalized in {"int", "integer"}:
        return {"type": "integer"}
    if normalized in {"float", "number"}:
        return {"type": "number"}
    if normalized in {"bool", "boolean"}:
        return {"type": "boolean"}
    if normalized in {"dict", "mapping", "object"}:
        return {"type": "object"}
    if normalized in {"list", "array", "tuple", "set"}:
        return {"type": "array"}
    return {}
