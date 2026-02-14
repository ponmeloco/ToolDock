"""
Unit tests for app.registry module.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.registry import (
    ToolDefinition,
    ToolRegistry,
    get_registry,
    reset_registry,
)
from app.errors import ToolNotFoundError, ToolTimeoutError, ToolValidationError


# ==================== Test Fixtures ====================


class SampleInput(BaseModel):
    """Sample input model for testing."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="test", description="Test name")
    count: int = Field(default=1, description="Test count")


async def sample_handler(payload: SampleInput) -> dict:
    """Sample handler for testing."""
    return {"name": payload.name, "count": payload.count}


@pytest.fixture
def sample_tool() -> ToolDefinition:
    """Create a sample ToolDefinition."""
    SampleInput.model_rebuild(force=True)
    return ToolDefinition(
        name="sample_tool",
        description="A sample tool for testing",
        input_model=SampleInput,
        handler=sample_handler,
    )


# ==================== Registration Tests ====================


class TestToolRegistration:
    """Tests for tool registration."""

    def test_register_tool(self, registry: ToolRegistry, sample_tool: ToolDefinition):
        """Test registering a single tool."""
        registry.register(sample_tool)

        assert registry.has_tool("sample_tool")
        tools = registry.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "sample_tool"

    def test_register_tool_with_namespace(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test registering a tool with a specific namespace."""
        registry.register(sample_tool, namespace="custom")

        assert registry.has_namespace("custom")
        assert registry.tool_in_namespace("sample_tool", "custom")
        assert registry.get_tool_namespace("sample_tool") == "custom"

    def test_register_tool_default_namespace(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test that tools default to 'shared' namespace."""
        registry.register(sample_tool)

        assert registry.get_tool_namespace("sample_tool") == "shared"
        assert registry.tool_in_namespace("sample_tool", "shared")

    def test_register_multiple_tools_same_namespace(self, registry: ToolRegistry):
        """Test registering multiple tools in the same namespace."""
        SampleInput.model_rebuild(force=True)

        tool1 = ToolDefinition(
            name="tool_one",
            description="Tool one",
            input_model=SampleInput,
            handler=sample_handler,
        )
        tool2 = ToolDefinition(
            name="tool_two",
            description="Tool two",
            input_model=SampleInput,
            handler=sample_handler,
        )

        registry.register(tool1, namespace="test_ns")
        registry.register(tool2, namespace="test_ns")

        assert len(registry.list_tools_for_namespace("test_ns")) == 2

    def test_register_tools_different_namespaces(self, registry: ToolRegistry):
        """Test registering tools in different namespaces."""
        SampleInput.model_rebuild(force=True)

        tool1 = ToolDefinition(
            name="tool_alpha",
            description="Alpha",
            input_model=SampleInput,
            handler=sample_handler,
        )
        tool2 = ToolDefinition(
            name="tool_beta",
            description="Beta",
            input_model=SampleInput,
            handler=sample_handler,
        )

        registry.register(tool1, namespace="namespace_a")
        registry.register(tool2, namespace="namespace_b")

        assert registry.has_namespace("namespace_a")
        assert registry.has_namespace("namespace_b")
        assert len(registry.list_namespaces()) == 2


# ==================== Unregistration Tests ====================


class TestToolUnregistration:
    """Tests for tool unregistration."""

    def test_unregister_tool(self, registry: ToolRegistry, sample_tool: ToolDefinition):
        """Test unregistering a tool."""
        registry.register(sample_tool)
        assert registry.has_tool("sample_tool")

        result = registry.unregister_tool("sample_tool")

        assert result is True
        assert not registry.has_tool("sample_tool")

    def test_unregister_nonexistent_tool(self, registry: ToolRegistry):
        """Test unregistering a tool that doesn't exist."""
        result = registry.unregister_tool("nonexistent")

        assert result is False

    def test_unregister_removes_from_namespace(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test that unregistering removes tool from namespace."""
        registry.register(sample_tool, namespace="test_ns")
        assert registry.tool_in_namespace("sample_tool", "test_ns")

        registry.unregister_tool("sample_tool")

        assert not registry.tool_in_namespace("sample_tool", "test_ns")

    def test_unregister_cleans_empty_namespace(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test that empty namespaces are cleaned up."""
        registry.register(sample_tool, namespace="single_tool_ns")
        assert registry.has_namespace("single_tool_ns")

        registry.unregister_tool("sample_tool")

        assert not registry.has_namespace("single_tool_ns")


# ==================== Namespace Tests ====================


class TestNamespaceOperations:
    """Tests for namespace-related operations."""

    def test_list_namespaces_empty(self, registry: ToolRegistry):
        """Test listing namespaces when empty."""
        namespaces = registry.list_namespaces()
        assert namespaces == []

    def test_list_namespaces(self, registry: ToolRegistry, sample_tool: ToolDefinition):
        """Test listing namespaces."""
        registry.register(sample_tool, namespace="ns_a")

        SampleInput.model_rebuild(force=True)
        another_tool = ToolDefinition(
            name="another",
            description="Another",
            input_model=SampleInput,
            handler=sample_handler,
        )
        registry.register(another_tool, namespace="ns_b")

        namespaces = registry.list_namespaces()
        assert sorted(namespaces) == ["ns_a", "ns_b"]

    def test_list_tools_for_namespace(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test listing tools in a namespace."""
        registry.register(sample_tool, namespace="my_ns")

        tools = registry.list_tools_for_namespace("my_ns")

        assert len(tools) == 1
        assert tools[0]["name"] == "sample_tool"
        assert "inputSchema" in tools[0]

    def test_list_tools_for_empty_namespace(self, registry: ToolRegistry):
        """Test listing tools for a namespace that doesn't exist."""
        tools = registry.list_tools_for_namespace("nonexistent")
        assert tools == []

    def test_namespace_isolation(self, registry: ToolRegistry):
        """Test that namespaces are properly isolated."""
        SampleInput.model_rebuild(force=True)

        tool_a = ToolDefinition(
            name="isolated_tool",
            description="In namespace A",
            input_model=SampleInput,
            handler=sample_handler,
        )
        tool_b = ToolDefinition(
            name="other_tool",
            description="In namespace B",
            input_model=SampleInput,
            handler=sample_handler,
        )

        registry.register(tool_a, namespace="ns_a")
        registry.register(tool_b, namespace="ns_b")

        # Each namespace should only see its own tools
        ns_a_tools = registry.list_tools_for_namespace("ns_a")
        ns_b_tools = registry.list_tools_for_namespace("ns_b")

        assert len(ns_a_tools) == 1
        assert ns_a_tools[0]["name"] == "isolated_tool"

        assert len(ns_b_tools) == 1
        assert ns_b_tools[0]["name"] == "other_tool"


# ==================== Tool Execution Tests ====================


class TestToolExecution:
    """Tests for tool execution."""

    @pytest.mark.asyncio
    async def test_call_tool(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test calling a registered tool."""
        registry.register(sample_tool)

        result = await registry.call("sample_tool", {"name": "Alice", "count": 5})

        assert result == {"name": "Alice", "count": 5}

    @pytest.mark.asyncio
    async def test_call_tool_with_defaults(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test calling a tool with default values."""
        registry.register(sample_tool)

        result = await registry.call("sample_tool", {})

        assert result == {"name": "test", "count": 1}

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self, registry: ToolRegistry):
        """Test calling a tool that doesn't exist raises error."""
        with pytest.raises(ToolNotFoundError):
            await registry.call("nonexistent", {})

    @pytest.mark.asyncio
    async def test_call_tool_invalid_args(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test calling a tool with invalid arguments raises validation error."""
        registry.register(sample_tool)

        with pytest.raises(ToolValidationError):
            await registry.call("sample_tool", {"count": "not_an_int"})

    @pytest.mark.asyncio
    async def test_call_tool_extra_args_rejected(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test that extra arguments are rejected (extra=forbid)."""
        registry.register(sample_tool)

        with pytest.raises(ToolValidationError):
            await registry.call("sample_tool", {"name": "test", "extra_field": "bad"})


# ==================== Timeout Tests ====================


class TestToolExecutionTimeout:
    """Tests for tool execution timeout."""

    @pytest.mark.asyncio
    async def test_tool_timeout(self, registry: ToolRegistry, monkeypatch):
        """Test that slow tools are timed out."""
        import asyncio

        # Set very short timeout
        monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "0.1")

        async def slow_handler(payload: SampleInput) -> dict:
            await asyncio.sleep(1.0)  # Sleep longer than timeout
            return {"name": payload.name}

        SampleInput.model_rebuild(force=True)
        slow_tool = ToolDefinition(
            name="slow_tool",
            description="A slow tool",
            input_model=SampleInput,
            handler=slow_handler,
        )
        registry.register(slow_tool)

        with pytest.raises(ToolTimeoutError) as exc_info:
            await registry.call("slow_tool", {"name": "test"})

        assert exc_info.value.code == "tool_timeout"
        assert "slow_tool" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_fast_tool_no_timeout(self, registry: ToolRegistry, monkeypatch):
        """Test that fast tools complete normally."""
        monkeypatch.setenv("TOOL_TIMEOUT_SECONDS", "5")

        async def fast_handler(payload: SampleInput) -> dict:
            return {"name": payload.name, "fast": True}

        SampleInput.model_rebuild(force=True)
        fast_tool = ToolDefinition(
            name="fast_tool",
            description="A fast tool",
            input_model=SampleInput,
            handler=fast_handler,
        )
        registry.register(fast_tool)

        result = await registry.call("fast_tool", {"name": "speedy"})

        assert result == {"name": "speedy", "fast": True}


# ==================== Tool Info Tests ====================


class TestToolInfo:
    """Tests for getting tool information."""

    def test_get_tool_info(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test getting tool info."""
        registry.register(sample_tool)

        info = registry.get_tool_info("sample_tool")

        assert info["name"] == "sample_tool"
        assert info["description"] == "A sample tool for testing"
        assert info["type"] == "native"
        assert "input_schema" in info

    def test_get_tool_info_nonexistent(self, registry: ToolRegistry):
        """Test getting info for nonexistent tool raises error."""
        with pytest.raises(ToolNotFoundError):
            registry.get_tool_info("nonexistent")

    def test_list_all_tools(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test listing all tools with type information."""
        registry.register(sample_tool, namespace="test_ns")

        all_tools = registry.list_all()

        assert len(all_tools) == 1
        assert all_tools[0]["name"] == "sample_tool"
        assert all_tools[0]["type"] == "native"
        assert all_tools[0]["namespace"] == "test_ns"


# ==================== Statistics Tests ====================


class TestRegistryStats:
    """Tests for registry statistics."""

    def test_get_stats_empty(self, registry: ToolRegistry):
        """Test stats for empty registry."""
        stats = registry.get_stats()

        assert stats["native"] == 0
        assert stats["external"] == 0
        assert stats["total"] == 0
        assert stats["namespaces"] == 0

    def test_get_stats_with_tools(
        self, registry: ToolRegistry, sample_tool: ToolDefinition
    ):
        """Test stats with registered tools."""
        registry.register(sample_tool, namespace="ns1")

        SampleInput.model_rebuild(force=True)
        tool2 = ToolDefinition(
            name="tool2",
            description="Second tool",
            input_model=SampleInput,
            handler=sample_handler,
        )
        registry.register(tool2, namespace="ns2")

        stats = registry.get_stats()

        assert stats["native"] == 2
        assert stats["total"] == 2
        assert stats["namespaces"] == 2
        assert stats["namespace_breakdown"] == {"ns1": 1, "ns2": 1}


# ==================== Global Registry Tests ====================


class TestGlobalRegistry:
    """Tests for global registry singleton."""

    def test_get_registry_singleton(self):
        """Test that get_registry returns the same instance."""
        reset_registry()
        reg1 = get_registry()
        reg2 = get_registry()

        assert reg1 is reg2

    def test_reset_registry(self, sample_tool: ToolDefinition):
        """Test resetting the global registry."""
        reset_registry()
        reg = get_registry()
        reg.register(sample_tool)

        reset_registry()
        new_reg = get_registry()

        assert not new_reg.has_tool("sample_tool")
        assert len(new_reg.list_tools()) == 0
