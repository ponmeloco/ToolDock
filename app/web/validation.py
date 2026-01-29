"""
Tool File Validation Module.

Validates Python tool files before upload to ensure they follow
the required conventions:
1. Valid Python syntax
2. register_tools() function present
3. Pydantic BaseModel with extra="forbid"
4. Async handlers
5. Descriptions in Field()
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of tool file validation."""

    is_valid: bool
    errors: List[str]
    warnings: List[str]
    info: dict


def validate_tool_file(content: str, filename: str = "tool.py") -> ValidationResult:
    """
    Validate a tool Python file.

    Checks:
    1. Valid Python syntax
    2. register_tools() function present
    3. Pydantic BaseModel with extra="forbid" config
    4. Async handlers
    5. Descriptions present in Field definitions

    Args:
        content: The Python file content as a string
        filename: Optional filename for error messages

    Returns:
        ValidationResult with is_valid, errors, warnings, and info
    """
    errors: List[str] = []
    warnings: List[str] = []
    info: dict = {
        "functions": [],
        "classes": [],
        "has_register_tools": False,
        "models": [],
        "handlers": [],
    }

    # 1. Syntax Check
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return ValidationResult(
            is_valid=False,
            errors=[f"Syntax error at line {e.lineno}: {e.msg}"],
            warnings=[],
            info=info,
        )

    # Collect information
    functions: List[str] = []
    classes: List[str] = []
    models: List[str] = []
    handlers: List[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)

    info["functions"] = functions
    info["classes"] = classes

    # 2. Check for register_tools() function
    register_tools_found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "register_tools":
            register_tools_found = True
            # Check if it takes a registry parameter
            if not node.args.args:
                errors.append("register_tools() must accept a 'registry' parameter")
            break

    if not register_tools_found:
        errors.append("Missing required function: register_tools(registry)")

    info["has_register_tools"] = register_tools_found

    # 3. Check Pydantic models have extra="forbid"
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            is_base_model = _is_pydantic_model(node)
            if is_base_model:
                models.append(node.name)
                has_extra_forbid = _check_extra_forbid(node)
                if not has_extra_forbid:
                    errors.append(
                        f"Class '{node.name}': Missing extra='forbid' in model_config or Config class. "
                        "This is required for strict input validation."
                    )

    info["models"] = models

    # 4. Check for async handlers
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check if function name suggests it's a handler
            if node.name.endswith("_handler") or node.name == "handler":
                handlers.append(node.name)
                warnings.append(
                    f"Function '{node.name}' appears to be a handler but is not async. "
                    "Handlers must be async for proper execution."
                )
        elif isinstance(node, ast.AsyncFunctionDef):
            if node.name.endswith("_handler") or node.name == "handler":
                handlers.append(node.name)

    info["handlers"] = handlers

    # 5. Check for descriptions in Field() calls (warning only)
    field_without_desc = _find_fields_without_description(tree)
    for class_name, field_name in field_without_desc:
        warnings.append(
            f"Field '{field_name}' in '{class_name}' has no description. "
            "Descriptions help LLMs understand the parameter."
        )

    # 6. Check imports
    has_pydantic = False
    has_registry = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "pydantic" in node.module:
                has_pydantic = True
            if node.module == "app.registry":
                has_registry = True

    if not has_pydantic and models:
        warnings.append("No pydantic import found but model classes exist")

    if not has_registry:
        warnings.append("No import from app.registry found")

    is_valid = len(errors) == 0

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        info=info,
    )


def _is_pydantic_model(node: ast.ClassDef) -> bool:
    """Check if a class inherits from BaseModel."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
    return False


def _check_extra_forbid(node: ast.ClassDef) -> bool:
    """
    Check if a Pydantic model has extra="forbid" configured.

    Checks for:
    - model_config = ConfigDict(extra="forbid")
    - class Config with extra = "forbid"
    """
    for item in node.body:
        # Check for model_config = ConfigDict(extra="forbid")
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name) and target.id == "model_config":
                    return _check_config_dict_extra_forbid(item.value)

        # Check for class Config with extra = "forbid"
        if isinstance(item, ast.ClassDef) and item.name == "Config":
            for config_item in item.body:
                if isinstance(config_item, ast.Assign):
                    for target in config_item.targets:
                        if isinstance(target, ast.Name) and target.id == "extra":
                            if isinstance(config_item.value, ast.Constant):
                                return config_item.value.value == "forbid"

    return False


def _check_config_dict_extra_forbid(node: ast.expr) -> bool:
    """Check if a ConfigDict call has extra='forbid'."""
    if isinstance(node, ast.Call):
        # Check keyword arguments
        for keyword in node.keywords:
            if keyword.arg == "extra":
                if isinstance(keyword.value, ast.Constant):
                    return keyword.value.value == "forbid"
    return False


def _find_fields_without_description(tree: ast.Module) -> List[Tuple[str, str]]:
    """
    Find Field() definitions without description parameter.

    Returns list of (class_name, field_name) tuples.
    """
    results: List[Tuple[str, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _is_pydantic_model(node):
            class_name = node.name

            for item in node.body:
                if isinstance(item, ast.AnnAssign) and item.value:
                    # Check if value is a Field() call
                    if isinstance(item.value, ast.Call):
                        func = item.value.func
                        if isinstance(func, ast.Name) and func.id == "Field":
                            # Check for description kwarg
                            has_desc = any(
                                kw.arg == "description" for kw in item.value.keywords
                            )
                            if not has_desc:
                                field_name = (
                                    item.target.id
                                    if isinstance(item.target, ast.Name)
                                    else "unknown"
                                )
                                results.append((class_name, field_name))

    return results


def validate_tool_module(filepath: str) -> ValidationResult:
    """
    Validate a tool file from disk.

    Args:
        filepath: Path to the Python file

    Returns:
        ValidationResult
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return validate_tool_file(content, filename=filepath)
    except FileNotFoundError:
        return ValidationResult(
            is_valid=False,
            errors=[f"File not found: {filepath}"],
            warnings=[],
            info={},
        )
    except Exception as e:
        return ValidationResult(
            is_valid=False,
            errors=[f"Error reading file: {e}"],
            warnings=[],
            info={},
        )
