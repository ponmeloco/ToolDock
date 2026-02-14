"""
Unit tests for app.web.validation module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.web.validation import (
    validate_tool_file,
    validate_tool_module,
    ValidationResult,
)


# ==================== Syntax Validation Tests ====================


class TestSyntaxValidation:
    """Tests for Python syntax validation."""

    def test_valid_syntax(self):
        """Test valid Python syntax passes."""
        code = """
def hello():
    return "world"
"""
        result = validate_tool_file(code)

        # Not valid as tool (no register_tools), but syntax is ok
        assert "Syntax error" not in str(result.errors)

    def test_invalid_syntax(self):
        """Test invalid Python syntax fails."""
        code = """
def broken(
    # Missing closing paren
"""
        result = validate_tool_file(code)

        assert result.is_valid is False
        assert any("Syntax error" in e for e in result.errors)

    def test_syntax_error_includes_line_number(self):
        """Test syntax error includes line number."""
        code = """line1
line2
def broken("""
        result = validate_tool_file(code)

        assert result.is_valid is False
        # Should mention line 3
        assert any("line 3" in e.lower() or "3:" in e for e in result.errors)


# ==================== register_tools Function Tests ====================


class TestRegisterToolsValidation:
    """Tests for register_tools() function validation."""

    def test_has_register_tools(self):
        """Test detection of register_tools function."""
        code = """
def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert result.info["has_register_tools"] is True

    def test_missing_register_tools(self):
        """Test error when register_tools is missing."""
        code = """
def other_function():
    pass
"""
        result = validate_tool_file(code)

        assert result.is_valid is False
        assert result.info["has_register_tools"] is False
        assert any("register_tools" in e for e in result.errors)

    def test_register_tools_without_parameter(self):
        """Test error when register_tools has no parameter."""
        code = """
def register_tools():
    pass
"""
        result = validate_tool_file(code)

        assert any("registry" in e.lower() for e in result.errors)


# ==================== Pydantic Model Validation Tests ====================


class TestPydanticModelValidation:
    """Tests for Pydantic model validation."""

    def test_model_with_extra_forbid_config_dict(self):
        """Test model with ConfigDict(extra='forbid') passes."""
        code = """
from pydantic import BaseModel, ConfigDict

class MyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "MyInput" in result.info["models"]
        assert not any("extra" in e.lower() for e in result.errors)

    def test_model_with_class_config(self):
        """Test model with Config class and extra='forbid' passes."""
        code = """
from pydantic import BaseModel

class MyInput(BaseModel):
    class Config:
        extra = "forbid"
    name: str

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "MyInput" in result.info["models"]
        assert not any("extra" in e.lower() for e in result.errors)

    def test_model_missing_extra_forbid(self):
        """Test model without extra='forbid' fails."""
        code = """
from pydantic import BaseModel

class MyInput(BaseModel):
    name: str

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert result.is_valid is False
        assert any("extra" in e.lower() and "forbid" in e.lower() for e in result.errors)

    def test_multiple_models_all_need_extra_forbid(self):
        """Test that all models need extra='forbid'."""
        code = """
from pydantic import BaseModel, ConfigDict

class ValidModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str

class InvalidModel(BaseModel):
    y: str

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert result.is_valid is False
        assert any("InvalidModel" in e for e in result.errors)


# ==================== Handler Validation Tests ====================


class TestHandlerValidation:
    """Tests for async handler validation."""

    def test_async_handler(self):
        """Test async handler passes."""
        code = """
from pydantic import BaseModel, ConfigDict

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str

async def my_handler(payload):
    return "ok"

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "my_handler" in result.info["handlers"]
        # No warning about async
        assert not any(
            "handler" in w.lower() and "async" in w.lower() for w in result.warnings
        )

    def test_sync_handler_warning(self):
        """Test sync handler generates warning."""
        code = """
from pydantic import BaseModel, ConfigDict

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str

def my_handler(payload):
    return "ok"

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "my_handler" in result.info["handlers"]
        # Should have warning about async
        assert any(
            "handler" in w.lower() and "async" in w.lower() for w in result.warnings
        )

    def test_function_named_handler(self):
        """Test function literally named 'handler' is detected."""
        code = """
from pydantic import BaseModel, ConfigDict

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str

def handler(payload):
    return "ok"

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "handler" in result.info["handlers"]


# ==================== Field Description Tests ====================


class TestFieldDescriptionValidation:
    """Tests for Field description validation."""

    def test_field_with_description(self):
        """Test field with description generates no warning."""
        code = """
from pydantic import BaseModel, ConfigDict, Field

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="The name")

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert not any("description" in w.lower() for w in result.warnings)

    def test_field_without_description(self):
        """Test field without description generates warning."""
        code = """
from pydantic import BaseModel, ConfigDict, Field

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="test")

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert any("description" in w.lower() for w in result.warnings)


# ==================== Import Validation Tests ====================


class TestImportValidation:
    """Tests for import validation."""

    def test_missing_pydantic_import_warning(self):
        """Test warning when pydantic import is missing but models exist."""
        code = """
class NotAModel:
    pass

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        # Should not warn since there are no BaseModel classes
        assert not any("pydantic" in w.lower() for w in result.warnings)

    def test_missing_registry_import_warning(self):
        """Test warning when app.registry import is missing."""
        code = """
from pydantic import BaseModel, ConfigDict

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert any("registry" in w.lower() for w in result.warnings)

    def test_has_registry_import(self):
        """Test no warning when app.registry is imported."""
        code = """
from pydantic import BaseModel, ConfigDict
from app.registry import ToolDefinition

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert not any(
            "No import from app.registry" in w for w in result.warnings
        )


# ==================== Info Collection Tests ====================


class TestInfoCollection:
    """Tests for info collection during validation."""

    def test_collects_functions(self):
        """Test that all functions are collected."""
        code = """
def func_a():
    pass

async def func_b():
    pass

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "func_a" in result.info["functions"]
        assert "func_b" in result.info["functions"]
        assert "register_tools" in result.info["functions"]

    def test_collects_classes(self):
        """Test that all classes are collected."""
        code = """
class ClassA:
    pass

class ClassB:
    pass

def register_tools(registry):
    pass
"""
        result = validate_tool_file(code)

        assert "ClassA" in result.info["classes"]
        assert "ClassB" in result.info["classes"]


# ==================== Full Valid Tool Tests ====================


class TestFullValidTool:
    """Tests for complete valid tool files."""

    def test_complete_valid_tool(self):
        """Test a complete, valid tool file."""
        code = '''
"""A valid tool."""

from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry


class GreetInput(BaseModel):
    """Input for greeting."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="World", description="Name to greet")


async def greet_handler(payload: GreetInput) -> str:
    """Handle the greet tool."""
    return f"Hello, {payload.name}!"


def register_tools(registry: ToolRegistry) -> None:
    """Register tools."""
    registry.register(
        ToolDefinition(
            name="greet",
            description="Greet someone",
            input_model=GreetInput,
            handler=greet_handler,
        )
    )
'''
        result = validate_tool_file(code)

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert result.info["has_register_tools"] is True
        assert "GreetInput" in result.info["models"]
        assert "greet_handler" in result.info["handlers"]


# ==================== File-based Validation Tests ====================


class TestValidateToolModule:
    """Tests for validate_tool_module function."""

    def test_validate_existing_file(self, sample_tools_dir: Path):
        """Test validating an existing file."""
        result = validate_tool_module(str(sample_tools_dir / "valid_tool.py"))

        assert result.is_valid is True

    def test_validate_nonexistent_file(self, tmp_path: Path):
        """Test validating a nonexistent file."""
        result = validate_tool_module(str(tmp_path / "nonexistent.py"))

        assert result.is_valid is False
        assert any("not found" in e.lower() for e in result.errors)

    def test_validate_invalid_file(self, sample_tools_dir: Path):
        """Test validating an invalid syntax file."""
        result = validate_tool_module(str(sample_tools_dir / "invalid_syntax.py"))

        assert result.is_valid is False


# ==================== ValidationResult Tests ====================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_creation(self):
        """Test creating a ValidationResult."""
        result = ValidationResult(
            is_valid=True,
            errors=[],
            warnings=["A warning"],
            info={"key": "value"},
        )

        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == ["A warning"]
        assert result.info == {"key": "value"}

    def test_validation_result_with_errors(self):
        """Test ValidationResult with errors."""
        result = ValidationResult(
            is_valid=False,
            errors=["Error 1", "Error 2"],
            warnings=[],
            info={},
        )

        assert result.is_valid is False
        assert len(result.errors) == 2
