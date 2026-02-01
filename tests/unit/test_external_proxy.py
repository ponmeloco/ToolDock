"""
Unit tests for app/external/proxy.py - MCPServerProxy.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.external.proxy import MCPServerProxy


class TestMCPServerProxyInit:
    """Tests for MCPServerProxy initialization."""

    def test_init_sets_server_id(self):
        """Test server_id is set correctly."""
        proxy = MCPServerProxy("test-server", {"command": "echo"})
        assert proxy.server_id == "test-server"

    def test_init_sets_config(self):
        """Test config is stored correctly."""
        config = {"command": "python", "args": ["-m", "server"]}
        proxy = MCPServerProxy("test", config)
        assert proxy.config == config

    def test_init_not_connected(self):
        """Test proxy starts disconnected."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        assert proxy.is_connected is False
        assert proxy.session is None
        assert proxy.tools == {}


class TestIsConnected:
    """Tests for is_connected property."""

    def test_is_connected_false_when_not_connected(self):
        """Test is_connected returns False when not connected."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        assert proxy.is_connected is False

    def test_is_connected_false_when_no_session(self):
        """Test is_connected returns False when session is None."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True
        proxy.session = None
        assert proxy.is_connected is False


class TestConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_already_connected_warns(self):
        """Test connecting when already connected logs warning."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True

        with patch("app.external.proxy.logger") as mock_logger:
            await proxy.connect()
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_connect_http_not_implemented(self):
        """Test HTTP transport raises NotImplementedError."""
        proxy = MCPServerProxy("test", {"type": "http", "url": "https://example.com"})

        with pytest.raises(NotImplementedError, match="HTTP transport not yet implemented"):
            await proxy.connect()

    @pytest.mark.asyncio
    async def test_connect_missing_command_raises(self):
        """Test connecting without command raises ValueError."""
        proxy = MCPServerProxy("test", {"type": "stdio"})

        with pytest.raises(ValueError, match="No command specified"):
            await proxy.connect()

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection."""
        proxy = MCPServerProxy("test", {"command": "echo", "args": []})

        # Mock tool with explicit name attribute
        mock_tool = MagicMock()
        mock_tool.name = "tool1"  # Explicitly set as string
        mock_tool.description = "Test tool"
        mock_tool.inputSchema = {"type": "object"}

        # Mock the MCP SDK components
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MagicMock(tools=[mock_tool])
        )

        with patch("app.external.proxy.stdio_client") as mock_stdio:
            mock_stdio.return_value.__aenter__ = AsyncMock(
                return_value=(MagicMock(), MagicMock())
            )
            mock_stdio.return_value.__aexit__ = AsyncMock()

            with patch("app.external.proxy.ClientSession") as mock_session_class:
                mock_session_class.return_value.__aenter__ = AsyncMock(
                    return_value=mock_session
                )
                mock_session_class.return_value.__aexit__ = AsyncMock()

                await proxy.connect()

                assert proxy._connected is True
                assert "tool1" in proxy.tools

    @pytest.mark.asyncio
    async def test_connect_failure_disconnects(self):
        """Test connection failure triggers disconnect."""
        proxy = MCPServerProxy("test", {"command": "failing-command"})

        with patch("app.external.proxy.stdio_client") as mock_stdio:
            mock_stdio.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("Connection failed")
            )

            with pytest.raises(RuntimeError, match="Connection failed"):
                await proxy.connect()

            # Should be disconnected after failure
            assert proxy._connected is False


class TestDiscoverTools:
    """Tests for _discover_tools method."""

    @pytest.mark.asyncio
    async def test_discover_tools_no_session(self):
        """Test discover tools does nothing without session."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy.session = None

        await proxy._discover_tools()
        assert proxy.tools == {}

    @pytest.mark.asyncio
    async def test_discover_tools_populates_dict(self):
        """Test discover tools populates tools dict."""
        proxy = MCPServerProxy("test", {"command": "echo"})

        # Create mock tools with explicit string names
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool1"
        mock_tool1.description = "First tool"
        mock_tool1.inputSchema = {"type": "object", "properties": {}}

        mock_tool2 = MagicMock()
        mock_tool2.name = "tool2"
        mock_tool2.description = "Second tool"
        mock_tool2.inputSchema = {}

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(
            return_value=MagicMock(tools=[mock_tool1, mock_tool2])
        )
        proxy.session = mock_session

        await proxy._discover_tools()

        assert len(proxy.tools) == 2
        assert proxy.tools["tool1"]["name"] == "tool1"
        assert proxy.tools["tool1"]["description"] == "First tool"
        assert proxy.tools["tool2"]["name"] == "tool2"


class TestCallTool:
    """Tests for call_tool method."""

    @pytest.mark.asyncio
    async def test_call_tool_not_connected_raises(self):
        """Test calling tool when not connected raises error."""
        proxy = MCPServerProxy("test", {"command": "echo"})

        with pytest.raises(RuntimeError, match="not connected"):
            await proxy.call_tool("tool1", {})

    @pytest.mark.asyncio
    async def test_call_tool_not_found_raises(self):
        """Test calling non-existent tool raises error."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True
        proxy.session = MagicMock()
        proxy.tools = {"existing_tool": {}}

        with pytest.raises(ValueError, match="Tool nonexistent not found"):
            await proxy.call_tool("nonexistent", {})

    @pytest.mark.asyncio
    async def test_call_tool_success_text_content(self):
        """Test successful tool call with text content."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True
        proxy.tools = {"mytool": {"name": "mytool"}}

        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="Hello, World!")]
        mock_result.isError = False

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        proxy.session = mock_session

        result = await proxy.call_tool("mytool", {"arg": "value"})

        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "Hello, World!"
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_call_tool_success_data_content(self):
        """Test successful tool call with data content."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True
        proxy.tools = {"mytool": {"name": "mytool"}}

        mock_content = MagicMock()
        mock_content.text = None  # No text attribute
        mock_content.data = {"key": "value"}
        del mock_content.text  # Remove text attribute

        mock_result = MagicMock()
        mock_result.content = [mock_content]
        mock_result.isError = False

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        proxy.session = mock_session

        result = await proxy.call_tool("mytool", {})

        assert result["content"][0]["type"] == "data"

    @pytest.mark.asyncio
    async def test_call_tool_error_returns_error_result(self):
        """Test tool call error returns error result instead of raising."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True
        proxy.tools = {"mytool": {"name": "mytool"}}

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=RuntimeError("Tool failed"))
        proxy.session = mock_session

        result = await proxy.call_tool("mytool", {})

        assert result["isError"] is True
        assert "Error: Tool failed" in result["content"][0]["text"]


class TestDisconnect:
    """Tests for disconnect method."""

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        """Test disconnect clears all state."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True
        proxy.session = MagicMock()
        proxy.tools = {"tool1": {}}

        # Mock exit stack
        mock_exit_stack = AsyncMock()
        proxy._exit_stack = mock_exit_stack

        await proxy.disconnect()

        assert proxy._connected is False
        assert proxy.session is None
        assert proxy.tools == {}
        mock_exit_stack.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_handles_exit_stack_error(self):
        """Test disconnect handles exit stack close error gracefully."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        proxy._connected = True

        mock_exit_stack = AsyncMock()
        mock_exit_stack.aclose = AsyncMock(side_effect=RuntimeError("Cleanup error"))
        proxy._exit_stack = mock_exit_stack

        # Should not raise
        await proxy.disconnect()

        assert proxy._connected is False
        assert proxy._exit_stack is None


class TestBuildEnv:
    """Tests for _build_env method."""

    def test_build_env_includes_current_env(self, monkeypatch):
        """Test build_env includes current environment."""
        monkeypatch.setenv("EXISTING_VAR", "existing_value")

        proxy = MCPServerProxy("test", {"command": "echo"})
        env = proxy._build_env()

        assert "EXISTING_VAR" in env
        assert env["EXISTING_VAR"] == "existing_value"

    def test_build_env_adds_config_env(self):
        """Test build_env adds configured env vars."""
        proxy = MCPServerProxy(
            "test",
            {
                "command": "echo",
                "env": {
                    "CUSTOM_VAR": "custom_value",
                },
            },
        )
        env = proxy._build_env()

        assert env["CUSTOM_VAR"] == "custom_value"

    def test_build_env_substitutes_env_reference(self, monkeypatch):
        """Test build_env substitutes ${VAR} references."""
        monkeypatch.setenv("SOURCE_VAR", "source_value")

        proxy = MCPServerProxy(
            "test",
            {
                "command": "echo",
                "env": {
                    "DERIVED_VAR": "${SOURCE_VAR}",
                },
            },
        )
        env = proxy._build_env()

        assert env["DERIVED_VAR"] == "source_value"

    def test_build_env_missing_reference_returns_empty(self, monkeypatch):
        """Test build_env returns empty for missing ${VAR} reference."""
        monkeypatch.delenv("MISSING_VAR", raising=False)

        proxy = MCPServerProxy(
            "test",
            {
                "command": "echo",
                "env": {
                    "MISSING_REF": "${MISSING_VAR}",
                },
            },
        )
        env = proxy._build_env()

        assert env["MISSING_REF"] == ""


class TestGetToolSchemas:
    """Tests for get_tool_schemas method."""

    def test_get_tool_schemas_empty(self):
        """Test get_tool_schemas with no tools."""
        proxy = MCPServerProxy("test", {"command": "echo"})
        schemas = proxy.get_tool_schemas()
        assert schemas == []

    def test_get_tool_schemas_prefixes_with_server_id(self):
        """Test get_tool_schemas prefixes tool names with server_id."""
        proxy = MCPServerProxy("github", {"command": "echo"})
        proxy.tools = {
            "list_repos": {
                "name": "list_repos",
                "description": "List repositories",
                "inputSchema": {"type": "object"},
            }
        }

        schemas = proxy.get_tool_schemas()

        assert len(schemas) == 1
        assert schemas[0]["name"] == "github:list_repos"
        assert schemas[0]["original_name"] == "list_repos"
        assert schemas[0]["server_id"] == "github"

    def test_get_tool_schemas_multiple_tools(self):
        """Test get_tool_schemas with multiple tools."""
        proxy = MCPServerProxy("myserver", {"command": "echo"})
        proxy.tools = {
            "tool1": {"name": "tool1", "description": "Tool 1", "inputSchema": {}},
            "tool2": {"name": "tool2", "description": "Tool 2", "inputSchema": {}},
        }

        schemas = proxy.get_tool_schemas()

        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"myserver:tool1", "myserver:tool2"}
