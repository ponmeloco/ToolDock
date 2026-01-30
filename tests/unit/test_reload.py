"""
Unit tests for app.reload module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.registry import ToolRegistry, reset_registry
from app.reload import (
    ToolReloader,
    ReloadResult,
    get_reloader,
    init_reloader,
    reset_reloader,
)
from app.loader import load_tools_from_directory


# ==================== ReloadResult Tests ====================


class TestReloadResult:
    """Tests for ReloadResult dataclass."""

    def test_successful_result(self):
        """Test creating a successful result."""
        result = ReloadResult(
            namespace="test",
            tools_unloaded=3,
            tools_loaded=4,
            success=True,
        )

        assert result.namespace == "test"
        assert result.tools_unloaded == 3
        assert result.tools_loaded == 4
        assert result.success is True
        assert result.error is None

    def test_failed_result(self):
        """Test creating a failed result."""
        result = ReloadResult(
            namespace="test",
            tools_unloaded=0,
            tools_loaded=0,
            success=False,
            error="Something went wrong",
        )

        assert result.success is False
        assert result.error == "Something went wrong"


# ==================== ToolReloader Tests ====================


class TestToolReloader:
    """Tests for ToolReloader class."""

    @pytest.fixture
    def tools_dir(self, tmp_path: Path) -> Path:
        """Create a temporary tools directory."""
        tools = tmp_path / "tools"
        tools.mkdir()
        return tools

    @pytest.fixture
    def namespace_with_tool(self, tools_dir: Path) -> tuple[Path, str]:
        """Create a namespace directory with a tool."""
        ns_dir = tools_dir / "test_ns"
        ns_dir.mkdir()

        tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return f"result: {payload.x}"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="reload_test_tool",
        description="Test tool for reload",
        input_model=Input,
        handler=handler,
    ))
'''
        (ns_dir / "tool.py").write_text(tool_code)
        return ns_dir, "test_ns"

    def test_reload_namespace(
        self,
        registry: ToolRegistry,
        tools_dir: Path,
        namespace_with_tool: tuple[Path, str],
    ):
        """Test reloading a namespace."""
        ns_dir, namespace = namespace_with_tool

        # First, load the tools
        load_tools_from_directory(registry, str(ns_dir), namespace=namespace)
        assert registry.has_tool("reload_test_tool")

        # Create reloader and reload
        reloader = ToolReloader(registry, str(tools_dir))
        result = reloader.reload_namespace(namespace)

        assert result.success is True
        assert result.namespace == namespace
        assert result.tools_unloaded >= 1
        assert result.tools_loaded >= 1
        assert registry.has_tool("reload_test_tool")

    def test_reload_detects_new_tool(
        self,
        registry: ToolRegistry,
        tools_dir: Path,
        namespace_with_tool: tuple[Path, str],
    ):
        """Test that reload detects newly added tools."""
        ns_dir, namespace = namespace_with_tool

        # Load initial tools
        load_tools_from_directory(registry, str(ns_dir), namespace=namespace)
        assert registry.has_tool("reload_test_tool")

        # Add a new tool
        new_tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class NewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    y: int = Field(default=0, description="Y")

async def handler(payload): return payload.y * 2

def register_tools(registry):
    NewInput.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="new_reload_tool",
        description="Newly added tool",
        input_model=NewInput,
        handler=handler,
    ))
'''
        (ns_dir / "new_tool.py").write_text(new_tool_code)

        # Reload
        reloader = ToolReloader(registry, str(tools_dir))
        result = reloader.reload_namespace(namespace)

        assert result.success is True
        assert registry.has_tool("reload_test_tool")
        assert registry.has_tool("new_reload_tool")

    def test_reload_detects_removed_tool(
        self,
        registry: ToolRegistry,
        tools_dir: Path,
        namespace_with_tool: tuple[Path, str],
    ):
        """Test that reload removes tools that were deleted from disk."""
        ns_dir, namespace = namespace_with_tool

        # Add a second tool
        second_tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class SecondInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    z: str = Field(default="", description="Z")

async def handler(payload): return "second"

def register_tools(registry):
    SecondInput.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="second_tool",
        description="Second tool",
        input_model=SecondInput,
        handler=handler,
    ))
'''
        (ns_dir / "second.py").write_text(second_tool_code)

        # Load initial tools
        load_tools_from_directory(registry, str(ns_dir), namespace=namespace)
        assert registry.has_tool("reload_test_tool")
        assert registry.has_tool("second_tool")

        # Remove the second tool file
        (ns_dir / "second.py").unlink()

        # Reload
        reloader = ToolReloader(registry, str(tools_dir))
        result = reloader.reload_namespace(namespace)

        assert result.success is True
        assert registry.has_tool("reload_test_tool")
        assert not registry.has_tool("second_tool")

    def test_reload_nonexistent_namespace(
        self, registry: ToolRegistry, tools_dir: Path
    ):
        """Test reloading a namespace that doesn't exist."""
        reloader = ToolReloader(registry, str(tools_dir))
        result = reloader.reload_namespace("nonexistent")

        assert result.success is False
        assert "not found" in result.error.lower()

    def test_reload_external_namespace_fails(
        self, registry: ToolRegistry, tools_dir: Path
    ):
        """Test that external namespaces cannot be reloaded."""
        reloader = ToolReloader(
            registry, str(tools_dir), external_namespaces={"external_ns"}
        )
        result = reloader.reload_namespace("external_ns")

        assert result.success is False
        assert "external" in result.error.lower()

    def test_reload_all(
        self, registry: ToolRegistry, tools_dir: Path
    ):
        """Test reloading all namespaces."""
        # Create two namespace directories with tools
        for ns in ["ns_alpha", "ns_beta"]:
            ns_dir = tools_dir / ns
            ns_dir.mkdir()

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

        # Load tools initially
        for ns in ["ns_alpha", "ns_beta"]:
            load_tools_from_directory(
                registry, str(tools_dir / ns), namespace=ns
            )

        reloader = ToolReloader(registry, str(tools_dir))
        results = reloader.reload_all()

        assert len(results) == 2
        assert all(r.success for r in results)

    def test_reload_all_skips_external(
        self, registry: ToolRegistry, tools_dir: Path
    ):
        """Test that reload_all skips external namespaces."""
        # Create native namespace
        native_dir = tools_dir / "native"
        native_dir.mkdir()

        tool_code = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "native"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="native_tool",
        description="Native tool",
        input_model=Input,
        handler=handler,
    ))
'''
        (native_dir / "tool.py").write_text(tool_code)

        # Load tools
        load_tools_from_directory(registry, str(native_dir), namespace="native")

        # Mark "external" as an external namespace
        reloader = ToolReloader(
            registry, str(tools_dir), external_namespaces={"external"}
        )
        results = reloader.reload_all()

        # Should only reload "native"
        namespaces_reloaded = [r.namespace for r in results]
        assert "native" in namespaces_reloaded
        assert "external" not in namespaces_reloaded

    def test_is_native_namespace(
        self, registry: ToolRegistry, tools_dir: Path
    ):
        """Test checking if a namespace is native."""
        reloader = ToolReloader(
            registry, str(tools_dir), external_namespaces={"ext1", "ext2"}
        )

        assert reloader.is_native_namespace("native") is True
        assert reloader.is_native_namespace("ext1") is False
        assert reloader.is_native_namespace("ext2") is False


# ==================== Module Cache Tests ====================


class TestModuleCacheClearing:
    """Tests for module cache clearing functionality."""

    @pytest.fixture
    def tools_dir(self, tmp_path: Path) -> Path:
        """Create a temporary tools directory."""
        tools = tmp_path / "tools"
        tools.mkdir()
        return tools

    @pytest.mark.asyncio
    async def test_reload_picks_up_changes(
        self, registry: ToolRegistry, tools_dir: Path
    ):
        """Test that reload actually picks up file changes."""
        ns_dir = tools_dir / "change_test"
        ns_dir.mkdir()

        # Initial version returns "v1"
        tool_code_v1 = '''
from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: str = Field(default="", description="X")

async def handler(payload): return "v1"

def register_tools(registry):
    Input.model_rebuild(force=True)
    registry.register(ToolDefinition(
        name="version_tool",
        description="Version test",
        input_model=Input,
        handler=handler,
    ))
'''
        (ns_dir / "tool.py").write_text(tool_code_v1)

        # Load initial version
        load_tools_from_directory(registry, str(ns_dir), namespace="change_test")
        assert registry.has_tool("version_tool")

        # Call tool to verify v1
        result1 = await registry.call("version_tool", {})
        assert result1 == "v1"

        # Update file to v2
        tool_code_v2 = tool_code_v1.replace('return "v1"', 'return "v2"')
        (ns_dir / "tool.py").write_text(tool_code_v2)

        # Reload
        reloader = ToolReloader(registry, str(tools_dir))
        result = reloader.reload_namespace("change_test")

        assert result.success is True
        assert registry.has_tool("version_tool")

        # Call tool to verify v2
        result2 = await registry.call("version_tool", {})
        assert result2 == "v2"


# ==================== Global Reloader Tests ====================


class TestGlobalReloader:
    """Tests for global reloader functions."""

    def test_init_reloader(self, registry: ToolRegistry, tmp_path: Path):
        """Test initializing the global reloader."""
        reset_reloader()
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        reloader = init_reloader(registry, str(tools_dir))

        assert reloader is not None
        assert get_reloader() is reloader

    def test_get_reloader_before_init(self):
        """Test getting reloader before initialization returns None."""
        reset_reloader()

        assert get_reloader() is None

    def test_reset_reloader(self, registry: ToolRegistry, tmp_path: Path):
        """Test resetting the global reloader."""
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        init_reloader(registry, str(tools_dir))
        assert get_reloader() is not None

        reset_reloader()

        assert get_reloader() is None
