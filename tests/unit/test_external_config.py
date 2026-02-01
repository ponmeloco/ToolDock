"""
Unit tests for app/external/config.py - ExternalServerConfig.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.external.config import ExternalServerConfig


class TestExternalServerConfigInit:
    """Tests for ExternalServerConfig initialization."""

    def test_default_config_path(self):
        """Test default config path is set correctly."""
        config = ExternalServerConfig()
        assert config.config_path == Path("tools/external/config.yaml")

    def test_custom_config_path(self, tmp_path):
        """Test custom config path is used."""
        custom_path = tmp_path / "custom.yaml"
        config = ExternalServerConfig(str(custom_path))
        assert config.config_path == custom_path


class TestExternalServerConfigLoad:
    """Tests for config loading."""

    def test_load_nonexistent_file_returns_empty(self, tmp_path):
        """Test loading non-existent file returns empty config."""
        config = ExternalServerConfig(str(tmp_path / "nonexistent.yaml"))
        result = config.load()
        assert result == {"servers": {}, "settings": {}}

    def test_load_valid_yaml(self, tmp_path):
        """Test loading valid YAML config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  test-server:
    source: custom
    command: echo
    args: ["hello"]
settings:
  auto_start: true
""")
        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert "servers" in result
        assert "test-server" in result["servers"]
        assert result["servers"]["test-server"]["command"] == "echo"
        assert result["settings"]["auto_start"] is True

    def test_load_empty_yaml(self, tmp_path):
        """Test loading empty YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")

        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert result == {"servers": {}, "settings": {}}

    def test_load_yaml_with_null_servers(self, tmp_path):
        """Test loading YAML with null servers section."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
settings:
  key: value
""")
        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert result["servers"] == {}
        assert result["settings"]["key"] == "value"


class TestEnvironmentVariableSubstitution:
    """Tests for environment variable substitution."""

    def test_substitute_simple_env_var(self, tmp_path, monkeypatch):
        """Test substituting a simple environment variable."""
        monkeypatch.setenv("TEST_VALUE", "substituted")

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  test:
    token: ${TEST_VALUE}
""")
        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert result["servers"]["test"]["token"] == "substituted"

    def test_substitute_missing_env_var_returns_empty(self, tmp_path, monkeypatch):
        """Test substituting missing env var returns empty string."""
        monkeypatch.delenv("MISSING_VAR", raising=False)

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  test:
    token: ${MISSING_VAR}
""")
        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert result["servers"]["test"]["token"] == ""

    def test_substitute_nested_dict(self, tmp_path, monkeypatch):
        """Test substitution in nested dictionaries."""
        monkeypatch.setenv("NESTED_VAL", "nested_result")

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  test:
    env:
      MY_VAR: ${NESTED_VAL}
""")
        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert result["servers"]["test"]["env"]["MY_VAR"] == "nested_result"

    def test_substitute_in_list(self, tmp_path, monkeypatch):
        """Test substitution in list items."""
        monkeypatch.setenv("LIST_VAL", "item_value")

        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  test:
    args:
      - ${LIST_VAL}
      - static
""")
        config = ExternalServerConfig(str(config_file))
        result = config.load()

        assert result["servers"]["test"]["args"] == ["item_value", "static"]


class TestExternalServerConfigSave:
    """Tests for config saving."""

    def test_save_creates_file(self, tmp_path):
        """Test saving creates the config file."""
        config_file = tmp_path / "new_config.yaml"
        config = ExternalServerConfig(str(config_file))

        test_config = {"servers": {"test": {"enabled": True}}}
        config.save(test_config)

        assert config_file.exists()

    def test_save_creates_parent_directories(self, tmp_path):
        """Test saving creates parent directories."""
        config_file = tmp_path / "nested" / "dir" / "config.yaml"
        config = ExternalServerConfig(str(config_file))

        test_config = {"servers": {}}
        config.save(test_config)

        assert config_file.exists()

    def test_save_preserves_content(self, tmp_path):
        """Test saved content can be loaded back."""
        config_file = tmp_path / "config.yaml"
        config = ExternalServerConfig(str(config_file))

        test_config = {
            "servers": {
                "server1": {"source": "custom", "command": "test"},
                "server2": {"source": "registry", "name": "some/server"},
            },
            "settings": {"auto_start": True},
        }
        config.save(test_config)

        # Reload and verify
        result = config.load()
        assert result["servers"]["server1"]["command"] == "test"
        assert result["servers"]["server2"]["name"] == "some/server"


class TestGetServerConfig:
    """Tests for get_server_config method."""

    @pytest.mark.asyncio
    async def test_custom_stdio_config(self, tmp_path):
        """Test building custom stdio config."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        server_def = {
            "source": "custom",
            "type": "stdio",
            "command": "python",
            "args": ["-m", "myserver"],
            "env": {"KEY": "value"},
        }

        result = await config.get_server_config("test-server", server_def)

        assert result["type"] == "stdio"
        assert result["command"] == "python"
        assert result["args"] == ["-m", "myserver"]
        assert result["env"] == {"KEY": "value"}

    @pytest.mark.asyncio
    async def test_custom_http_config(self, tmp_path):
        """Test building custom http config."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        server_def = {
            "source": "custom",
            "type": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer token"},
        }

        result = await config.get_server_config("test-server", server_def)

        assert result["type"] == "http"
        assert result["url"] == "https://example.com/mcp"
        assert result["headers"] == {"Authorization": "Bearer token"}

    @pytest.mark.asyncio
    async def test_custom_stdio_missing_command_raises(self, tmp_path):
        """Test stdio config without command raises error."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        server_def = {
            "source": "custom",
            "type": "stdio",
            # command missing
        }

        with pytest.raises(ValueError, match="'command' required"):
            await config.get_server_config("test-server", server_def)

    @pytest.mark.asyncio
    async def test_custom_http_missing_url_raises(self, tmp_path):
        """Test http config without url raises error."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        server_def = {
            "source": "custom",
            "type": "http",
            # url missing
        }

        with pytest.raises(ValueError, match="'url' required"):
            await config.get_server_config("test-server", server_def)

    @pytest.mark.asyncio
    async def test_registry_source_missing_name_raises(self, tmp_path):
        """Test registry source without name raises error."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        server_def = {
            "source": "registry",
            # name missing
        }

        with pytest.raises(ValueError, match="'name' required for registry source"):
            await config.get_server_config("test-server", server_def)

    @pytest.mark.asyncio
    async def test_registry_source_fetches_from_registry(self, tmp_path):
        """Test registry source fetches config from MCP Registry."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        # Mock the registry client
        mock_server_data = {
            "server": {
                "name": "test/server",
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "@test/mcp-server",
                    }
                ],
            }
        }

        with patch.object(
            config._registry_client, "get_server", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_server_data

            server_def = {
                "source": "registry",
                "name": "test/server",
            }

            result = await config.get_server_config("test-server", server_def)

            mock_get.assert_called_once_with("test/server")
            assert result["type"] == "stdio"
            assert result["command"] == "npx"

    @pytest.mark.asyncio
    async def test_registry_source_not_found_raises(self, tmp_path):
        """Test registry source with non-existent server raises error."""
        config = ExternalServerConfig(str(tmp_path / "config.yaml"))

        with patch.object(
            config._registry_client, "get_server", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = None

            server_def = {
                "source": "registry",
                "name": "nonexistent/server",
            }

            with pytest.raises(ValueError, match="Server not found in registry"):
                await config.get_server_config("test-server", server_def)


class TestAddAndRemoveServerFromConfig:
    """Tests for add/remove server methods."""

    def test_add_server_to_config(self, tmp_path):
        """Test adding a server to config."""
        config_file = tmp_path / "config.yaml"
        config = ExternalServerConfig(str(config_file))

        config.add_server_to_config(
            server_id="new-server",
            source="registry",
            name="some/server",
            enabled=True,
        )

        result = config.load()
        assert "new-server" in result["servers"]
        assert result["servers"]["new-server"]["source"] == "registry"
        assert result["servers"]["new-server"]["name"] == "some/server"
        assert result["servers"]["new-server"]["enabled"] is True

    def test_add_custom_server_with_kwargs(self, tmp_path):
        """Test adding a custom server with extra kwargs."""
        config_file = tmp_path / "config.yaml"
        config = ExternalServerConfig(str(config_file))

        config.add_server_to_config(
            server_id="custom-server",
            source="custom",
            enabled=True,
            command="python",
            args=["-m", "server"],
        )

        result = config.load()
        assert result["servers"]["custom-server"]["command"] == "python"
        assert result["servers"]["custom-server"]["args"] == ["-m", "server"]

    def test_remove_server_from_config(self, tmp_path):
        """Test removing a server from config."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  server1:
    enabled: true
  server2:
    enabled: true
""")
        config = ExternalServerConfig(str(config_file))

        result = config.remove_server_from_config("server1")

        assert result is True
        reloaded = config.load()
        assert "server1" not in reloaded["servers"]
        assert "server2" in reloaded["servers"]

    def test_remove_nonexistent_server(self, tmp_path):
        """Test removing non-existent server returns False."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("servers: {}")

        config = ExternalServerConfig(str(config_file))
        result = config.remove_server_from_config("nonexistent")

        assert result is False


class TestApply:
    """Tests for applying config to manager."""

    @pytest.mark.asyncio
    async def test_apply_empty_config(self, tmp_path):
        """Test applying empty config does nothing."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("servers: {}")

        config = ExternalServerConfig(str(config_file))
        mock_manager = MagicMock()

        result = await config.apply(mock_manager)

        assert result["loaded"] == []
        assert result["failed"] == []
        assert result["skipped"] == []

    @pytest.mark.asyncio
    async def test_apply_skips_disabled_servers(self, tmp_path):
        """Test apply skips disabled servers."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  disabled-server:
    enabled: false
    source: custom
    command: echo
""")
        config = ExternalServerConfig(str(config_file))
        mock_manager = MagicMock()

        result = await config.apply(mock_manager)

        assert "disabled-server" in result["skipped"]
        mock_manager.add_server.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_loads_enabled_servers(self, tmp_path):
        """Test apply loads enabled servers."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  test-server:
    enabled: true
    source: custom
    type: stdio
    command: echo
    args: ["hello"]
""")
        config = ExternalServerConfig(str(config_file))
        mock_manager = MagicMock()
        mock_manager.add_server = AsyncMock()

        result = await config.apply(mock_manager)

        assert "test-server" in result["loaded"]
        mock_manager.add_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_records_failed_servers(self, tmp_path):
        """Test apply records servers that fail to load."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
servers:
  failing-server:
    enabled: true
    source: custom
    type: stdio
    command: nonexistent-command
""")
        config = ExternalServerConfig(str(config_file))
        mock_manager = MagicMock()
        mock_manager.add_server = AsyncMock(side_effect=RuntimeError("Connection failed"))

        result = await config.apply(mock_manager)

        assert len(result["failed"]) == 1
        assert result["failed"][0]["server_id"] == "failing-server"
        assert "Connection failed" in result["failed"][0]["error"]
