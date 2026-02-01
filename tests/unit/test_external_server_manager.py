"""
Unit tests for app/external/server_manager.py - ExternalServerManager.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.external.server_manager import (
    ExternalServerManager,
    _is_sensitive_key,
    _mask_config,
)


class TestIsSensitiveKey:
    """Tests for _is_sensitive_key helper."""

    def test_token_is_sensitive(self):
        """Test 'token' key is sensitive."""
        assert _is_sensitive_key("token") is True
        assert _is_sensitive_key("auth_token") is True
        assert _is_sensitive_key("API_TOKEN") is True

    def test_secret_is_sensitive(self):
        """Test 'secret' key is sensitive."""
        assert _is_sensitive_key("secret") is True
        assert _is_sensitive_key("client_secret") is True
        assert _is_sensitive_key("SECRET_KEY") is True

    def test_password_is_sensitive(self):
        """Test 'password' key is sensitive."""
        assert _is_sensitive_key("password") is True
        assert _is_sensitive_key("user_password") is True
        assert _is_sensitive_key("PASSWORD") is True

    def test_key_is_sensitive(self):
        """Test 'key' key is sensitive."""
        assert _is_sensitive_key("api_key") is True
        assert _is_sensitive_key("private_key") is True
        assert _is_sensitive_key("KEY") is True

    def test_credential_is_sensitive(self):
        """Test 'credential' key is sensitive."""
        assert _is_sensitive_key("credential") is True
        assert _is_sensitive_key("credentials") is True
        assert _is_sensitive_key("user_credentials") is True

    def test_connection_string_is_sensitive(self):
        """Test 'connection string' key is sensitive."""
        assert _is_sensitive_key("connection_string") is True
        assert _is_sensitive_key("db_connection_string") is True

    def test_normal_keys_not_sensitive(self):
        """Test normal keys are not sensitive."""
        assert _is_sensitive_key("name") is False
        assert _is_sensitive_key("command") is False
        assert _is_sensitive_key("url") is False
        assert _is_sensitive_key("type") is False


class TestMaskConfig:
    """Tests for _mask_config helper."""

    def test_masks_sensitive_values(self):
        """Test sensitive values are masked."""
        config = {"api_key": "secret123", "name": "test"}
        result = _mask_config(config)

        assert result["api_key"] == "***MASKED***"
        assert result["name"] == "test"

    def test_masks_env_sensitive_values(self):
        """Test sensitive values in env dict are masked."""
        config = {
            "command": "echo",
            "env": {
                "API_KEY": "secret123",
                "DEBUG": "true",
            },
        }
        result = _mask_config(config)

        assert result["env"]["API_KEY"] == "***MASKED***"
        assert result["env"]["DEBUG"] == "true"

    def test_masks_nested_dicts(self):
        """Test nested dicts are recursively masked."""
        config = {
            "outer": {
                "api_token": "secret",
                "safe": "value",
            }
        }
        result = _mask_config(config)

        assert result["outer"]["api_token"] == "***MASKED***"
        assert result["outer"]["safe"] == "value"

    def test_preserves_none_values(self):
        """Test None values for sensitive keys are preserved as None."""
        config = {"api_key": None, "name": "test"}
        result = _mask_config(config)

        assert result["api_key"] is None


class TestExternalServerManagerInit:
    """Tests for ExternalServerManager initialization."""

    def test_init_stores_registry(self):
        """Test registry is stored."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)
        assert manager.registry is mock_registry

    def test_init_empty_servers(self):
        """Test servers dict starts empty."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)
        assert manager.servers == {}


class TestAddServer:
    """Tests for add_server method."""

    @pytest.mark.asyncio
    async def test_add_server_duplicate_raises(self):
        """Test adding duplicate server raises ValueError."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)
        manager.servers["existing"] = MagicMock()

        with pytest.raises(ValueError, match="already exists"):
            await manager.add_server("existing", {"command": "echo"})

    @pytest.mark.asyncio
    async def test_add_server_success(self):
        """Test successful server addition."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        # Mock the proxy
        mock_proxy = MagicMock()
        mock_proxy.connect = AsyncMock()
        mock_proxy.tools = {
            "tool1": {"name": "tool1", "description": "Test", "inputSchema": {}},
        }
        mock_proxy.server_id = "test-server"
        mock_proxy.config = {"command": "echo"}

        with patch("app.external.server_manager.MCPServerProxy", return_value=mock_proxy):
            result = await manager.add_server("test-server", {"command": "echo"})

        assert result["server_id"] == "test-server"
        assert result["status"] == "connected"
        assert result["tools"] == 1
        assert "test-server" in manager.servers
        mock_registry.register_external_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_server_connection_failure_cleanup(self):
        """Test connection failure triggers cleanup."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        mock_proxy.connect = AsyncMock(side_effect=RuntimeError("Connection failed"))
        mock_proxy.disconnect = AsyncMock()

        with patch("app.external.server_manager.MCPServerProxy", return_value=mock_proxy):
            with pytest.raises(RuntimeError):
                await manager.add_server("failing", {"command": "bad"})

        mock_proxy.disconnect.assert_called_once()
        assert "failing" not in manager.servers


class TestRemoveServer:
    """Tests for remove_server method."""

    @pytest.mark.asyncio
    async def test_remove_nonexistent_server(self):
        """Test removing non-existent server returns False."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        result = await manager.remove_server("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_server_success(self):
        """Test successful server removal."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        mock_proxy.tools = {"tool1": {}}
        mock_proxy.disconnect = AsyncMock()
        manager.servers["test-server"] = mock_proxy

        result = await manager.remove_server("test-server")

        assert result is True
        assert "test-server" not in manager.servers
        mock_proxy.disconnect.assert_called_once()
        mock_registry.unregister_tool.assert_called_once_with("tool1")


class TestRegisterTools:
    """Tests for _register_tools method."""

    def test_register_tools_calls_registry(self):
        """Test _register_tools registers each tool."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        mock_proxy.server_id = "github"
        mock_proxy.tools = {
            "list_repos": {"description": "List repos", "inputSchema": {"type": "object"}},
            "create_issue": {"description": "Create issue", "inputSchema": {}},
        }

        count = manager._register_tools(mock_proxy)

        assert count == 2
        assert mock_registry.register_external_tool.call_count == 2


class TestUnregisterTools:
    """Tests for _unregister_tools method."""

    def test_unregister_tools_calls_registry(self):
        """Test _unregister_tools unregisters each tool."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        mock_proxy.tools = {
            "tool1": {},
            "tool2": {},
        }

        manager._unregister_tools(mock_proxy)

        assert mock_registry.unregister_tool.call_count == 2


class TestListServers:
    """Tests for list_servers method."""

    def test_list_servers_empty(self):
        """Test list_servers with no servers."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        result = manager.list_servers()
        assert result == []

    def test_list_servers_returns_info(self):
        """Test list_servers returns server info."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        mock_proxy.is_connected = True
        mock_proxy.tools = {"tool1": {}, "tool2": {}}
        mock_proxy.config = {"type": "stdio", "command": "npx"}
        manager.servers["github"] = mock_proxy

        result = manager.list_servers()

        assert len(result) == 1
        assert result[0]["server_id"] == "github"
        assert result[0]["namespace"] == "github"
        assert result[0]["status"] == "connected"
        assert result[0]["tools"] == 2

    def test_list_servers_masks_config(self):
        """Test list_servers masks sensitive config."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        mock_proxy.is_connected = True
        mock_proxy.tools = {}
        mock_proxy.config = {
            "type": "stdio",
            "command": "npx",
            "env": {"API_KEY": "secret123"},
        }
        manager.servers["test"] = mock_proxy

        result = manager.list_servers()

        # Config should only contain type and command (masked)
        assert "config" in result[0]


class TestGetServer:
    """Tests for get_server method."""

    def test_get_server_exists(self):
        """Test get_server returns proxy when exists."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy = MagicMock()
        manager.servers["test"] = mock_proxy

        result = manager.get_server("test")
        assert result is mock_proxy

    def test_get_server_not_exists(self):
        """Test get_server returns None when not exists."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        result = manager.get_server("nonexistent")
        assert result is None


class TestHasServer:
    """Tests for has_server method."""

    def test_has_server_true(self):
        """Test has_server returns True when exists."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)
        manager.servers["test"] = MagicMock()

        assert manager.has_server("test") is True

    def test_has_server_false(self):
        """Test has_server returns False when not exists."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        assert manager.has_server("nonexistent") is False


class TestShutdownAll:
    """Tests for shutdown_all method."""

    @pytest.mark.asyncio
    async def test_shutdown_all_removes_all_servers(self):
        """Test shutdown_all removes all servers."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy1 = MagicMock()
        mock_proxy1.tools = {}
        mock_proxy1.disconnect = AsyncMock()

        mock_proxy2 = MagicMock()
        mock_proxy2.tools = {}
        mock_proxy2.disconnect = AsyncMock()

        manager.servers["server1"] = mock_proxy1
        manager.servers["server2"] = mock_proxy2

        await manager.shutdown_all()

        assert len(manager.servers) == 0
        mock_proxy1.disconnect.assert_called_once()
        mock_proxy2.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_all_handles_errors(self):
        """Test shutdown_all continues on error."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy1 = MagicMock()
        mock_proxy1.tools = {}
        mock_proxy1.disconnect = AsyncMock(side_effect=RuntimeError("Cleanup failed"))

        mock_proxy2 = MagicMock()
        mock_proxy2.tools = {}
        mock_proxy2.disconnect = AsyncMock()

        manager.servers["failing"] = mock_proxy1
        manager.servers["working"] = mock_proxy2

        # Should not raise
        await manager.shutdown_all()

        # Both should be attempted
        mock_proxy1.disconnect.assert_called_once()
        mock_proxy2.disconnect.assert_called_once()


class TestGetStats:
    """Tests for get_stats method."""

    def test_get_stats_empty(self):
        """Test get_stats with no servers."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        stats = manager.get_stats()

        assert stats["total_servers"] == 0
        assert stats["connected_servers"] == 0
        assert stats["total_tools"] == 0
        assert stats["namespaces"] == []

    def test_get_stats_with_servers(self):
        """Test get_stats with servers."""
        mock_registry = MagicMock()
        manager = ExternalServerManager(mock_registry)

        mock_proxy1 = MagicMock()
        mock_proxy1.is_connected = True
        mock_proxy1.tools = {"t1": {}, "t2": {}}

        mock_proxy2 = MagicMock()
        mock_proxy2.is_connected = False
        mock_proxy2.tools = {"t3": {}}

        manager.servers["server1"] = mock_proxy1
        manager.servers["server2"] = mock_proxy2

        stats = manager.get_stats()

        assert stats["total_servers"] == 2
        assert stats["connected_servers"] == 1
        assert stats["total_tools"] == 3
        assert set(stats["namespaces"]) == {"server1", "server2"}
