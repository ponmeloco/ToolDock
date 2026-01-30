"""
Unit tests for app.loader module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.registry import ToolRegistry, reset_registry
from app.loader import (
    load_tools_from_directory,
    load_tools_from_namespaces,
    discover_namespaces,
    _NamespaceRegistryWrapper,
)


# ==================== Directory Loading Tests ====================


class TestLoadToolsFromDirectory:
    """Tests for load_tools_from_directory function."""

    def test_load_valid_tool(self, registry: ToolRegistry, sample_tools_dir: Path):
        """Test loading a valid tool from directory."""
        # Create a directory with just valid tools
        valid_dir = sample_tools_dir.parent / "valid_only"
        valid_dir.mkdir(exist_ok=True)

        # Copy valid_tool.py content
        tool_code = (sample_tools_dir / "valid_tool.py").read_text()
        (valid_dir / "valid_tool.py").write_text(tool_code)

        count = load_tools_from_directory(registry, str(valid_dir), namespace="test")

        assert count >= 1
        assert registry.has_tool("greet")

    def test_load_nonexistent_directory(self, registry: ToolRegistry, tmp_path: Path):
        """Test loading from a directory that doesn't exist."""
        count = load_tools_from_directory(
            registry, str(tmp_path / "nonexistent"), namespace="test"
        )
        assert count == 0

    def test_load_empty_directory(self, registry: ToolRegistry, tmp_path: Path):
        """Test loading from an empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        count = load_tools_from_directory(registry, str(empty_dir), namespace="test")

        assert count == 0

    def test_skip_invalid_syntax(self, registry: ToolRegistry, tmp_path: Path):
        """Test that files with syntax errors are skipped."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # Create a file with invalid syntax
        invalid_file = tools_dir / "bad_syntax.py"
        invalid_file.write_text("def broken(\n")  # Invalid syntax

        # Create a valid file
        valid_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class ValidInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(default="x", description="Value")

async def handler(payload: ValidInput) -> str:
    return payload.value

def register_tools(registry: ToolRegistry) -> None:
    ValidInput.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="valid_tool_syntax",
        description="Valid",
        input_model=ValidInput,
        handler=handler,
    ))
'''
        valid_file = tools_dir / "valid.py"
        valid_file.write_text(valid_code)

        count = load_tools_from_directory(registry, str(tools_dir), namespace="test")

        # Should load the valid file despite the invalid one
        assert count == 1
        assert registry.has_tool("valid_tool_syntax")

    def test_skip_missing_register_function(
        self, registry: ToolRegistry, tmp_path: Path
    ):
        """Test that files without register_tools function are skipped."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # File without register_tools
        no_register = tools_dir / "no_register.py"
        no_register.write_text("""
def some_function():
    pass
""")

        count = load_tools_from_directory(registry, str(tools_dir), namespace="test")

        assert count == 0

    def test_skip_underscore_files(self, registry: ToolRegistry, tmp_path: Path):
        """Test that files starting with underscore are skipped."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # Create _private.py
        private_file = tools_dir / "_private.py"
        private_file.write_text('''
from pydantic import BaseModel, ConfigDict
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

async def handler(payload): return "private"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="private_tool",
        description="Should not be loaded",
        input_model=Input,
        handler=handler,
    ))
''')

        count = load_tools_from_directory(registry, str(tools_dir), namespace="test")

        assert count == 0
        assert not registry.has_tool("private_tool")

    def test_namespace_from_directory_name(self, registry: ToolRegistry, tmp_path: Path):
        """Test that namespace defaults to directory name."""
        custom_ns_dir = tmp_path / "my_namespace"
        custom_ns_dir.mkdir()

        tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "ok"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="ns_test_tool",
        description="Test",
        input_model=Input,
        handler=handler,
    ))
'''
        (custom_ns_dir / "tool.py").write_text(tool_code)

        # Load without specifying namespace
        load_tools_from_directory(registry, str(custom_ns_dir))

        assert registry.get_tool_namespace("ns_test_tool") == "my_namespace"

    def test_explicit_namespace_override(self, registry: ToolRegistry, tmp_path: Path):
        """Test that explicit namespace overrides directory name."""
        dir_name = tmp_path / "original_name"
        dir_name.mkdir()

        tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "ok"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="override_ns_tool",
        description="Test",
        input_model=Input,
        handler=handler,
    ))
'''
        (dir_name / "tool.py").write_text(tool_code)

        load_tools_from_directory(
            registry, str(dir_name), namespace="custom_override"
        )

        assert registry.get_tool_namespace("override_ns_tool") == "custom_override"


# ==================== Namespace Loading Tests ====================


class TestLoadToolsFromNamespaces:
    """Tests for load_tools_from_namespaces function."""

    def test_load_multiple_namespaces(self, registry: ToolRegistry, tmp_path: Path):
        """Test loading from multiple namespace directories."""
        base_dir = tmp_path / "tools"

        # Create two namespace directories
        for ns in ["namespace_a", "namespace_b"]:
            ns_dir = base_dir / ns
            ns_dir.mkdir(parents=True)

            tool_code = f'''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "{ns}"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="{ns}_tool",
        description="Tool in {ns}",
        input_model=Input,
        handler=handler,
    ))
'''
            (ns_dir / "tool.py").write_text(tool_code)

        results = load_tools_from_namespaces(registry, str(base_dir))

        assert "namespace_a" in results
        assert "namespace_b" in results
        assert registry.has_tool("namespace_a_tool")
        assert registry.has_tool("namespace_b_tool")
        assert registry.get_tool_namespace("namespace_a_tool") == "namespace_a"
        assert registry.get_tool_namespace("namespace_b_tool") == "namespace_b"

    def test_load_specific_namespaces(self, registry: ToolRegistry, tmp_path: Path):
        """Test loading only specific namespaces."""
        base_dir = tmp_path / "tools"

        # Create three namespace directories
        for ns in ["ns1", "ns2", "ns3"]:
            ns_dir = base_dir / ns
            ns_dir.mkdir(parents=True)

            tool_code = f'''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "{ns}"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="{ns}_tool",
        description="Tool",
        input_model=Input,
        handler=handler,
    ))
'''
            (ns_dir / "tool.py").write_text(tool_code)

        # Only load ns1 and ns3
        results = load_tools_from_namespaces(
            registry, str(base_dir), namespaces=["ns1", "ns3"]
        )

        assert "ns1" in results
        assert "ns3" in results
        assert "ns2" not in results
        assert registry.has_tool("ns1_tool")
        assert registry.has_tool("ns3_tool")
        assert not registry.has_tool("ns2_tool")

    def test_skip_nonexistent_namespace(self, registry: ToolRegistry, tmp_path: Path):
        """Test that nonexistent namespace directories are skipped."""
        base_dir = tmp_path / "tools"
        base_dir.mkdir()

        results = load_tools_from_namespaces(
            registry, str(base_dir), namespaces=["nonexistent"]
        )

        assert results == {}


# ==================== Namespace Discovery Tests ====================


class TestDiscoverNamespaces:
    """Tests for discover_namespaces function."""

    def test_discover_namespaces(self, tmp_path: Path):
        """Test discovering namespace directories."""
        base_dir = tmp_path / "tools"

        # Create namespace directories
        (base_dir / "alpha").mkdir(parents=True)
        (base_dir / "beta").mkdir(parents=True)
        (base_dir / "gamma").mkdir(parents=True)

        namespaces = discover_namespaces(str(base_dir))

        assert sorted(namespaces) == ["alpha", "beta", "gamma"]

    def test_discover_ignores_underscore_dirs(self, tmp_path: Path):
        """Test that directories starting with underscore are ignored."""
        base_dir = tmp_path / "tools"

        (base_dir / "public").mkdir(parents=True)
        (base_dir / "_private").mkdir(parents=True)
        (base_dir / "__pycache__").mkdir(parents=True)

        namespaces = discover_namespaces(str(base_dir))

        assert namespaces == ["public"]

    def test_discover_ignores_files(self, tmp_path: Path):
        """Test that files are ignored when discovering namespaces."""
        base_dir = tmp_path / "tools"
        base_dir.mkdir()

        # Create a directory and a file
        (base_dir / "namespace_dir").mkdir()
        (base_dir / "not_a_namespace.py").write_text("# file")

        namespaces = discover_namespaces(str(base_dir))

        assert namespaces == ["namespace_dir"]

    def test_discover_nonexistent_directory(self, tmp_path: Path):
        """Test discovering from nonexistent directory."""
        namespaces = discover_namespaces(str(tmp_path / "nonexistent"))

        assert namespaces == []


# ==================== Namespace Wrapper Tests ====================


class TestNamespaceRegistryWrapper:
    """Tests for _NamespaceRegistryWrapper class."""

    def test_wrapper_injects_namespace(self, registry: ToolRegistry):
        """Test that wrapper injects namespace on registration."""
        from pydantic import BaseModel, ConfigDict, Field
        from app.registry import ToolDefinition

        class Input(BaseModel):
            model_config = ConfigDict(extra="forbid")
            x: str = Field(default="", description="X")

        async def handler(payload):
            return "ok"

        wrapper = _NamespaceRegistryWrapper(registry, "injected_ns")

        Input.model_rebuild(force=True)
        wrapper.register(
            ToolDefinition(
                name="wrapped_tool",
                description="Test",
                input_model=Input,
                handler=handler,
            )
        )

        assert registry.get_tool_namespace("wrapped_tool") == "injected_ns"

    def test_wrapper_forwards_other_methods(self, registry: ToolRegistry):
        """Test that wrapper forwards non-register methods to registry."""
        wrapper = _NamespaceRegistryWrapper(registry, "test_ns")

        # list_tools should be forwarded
        tools = wrapper.list_tools()
        assert isinstance(tools, list)

        # has_tool should be forwarded
        assert wrapper.has_tool("nonexistent") is False

    def test_wrapper_get_stats(self, registry: ToolRegistry):
        """Test that wrapper can access get_stats."""
        wrapper = _NamespaceRegistryWrapper(registry, "test_ns")

        stats = wrapper.get_stats()

        assert "native" in stats
        assert "total" in stats
