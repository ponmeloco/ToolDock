"""
Unit tests for app/external/registry_client.py - MCPRegistryClient.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.external.registry_client import MCPRegistryClient, REGISTRY_BASE_URL


class TestMCPRegistryClientInit:
    """Tests for MCPRegistryClient initialization."""

    def test_default_base_url(self):
        """Test default base URL is set correctly."""
        client = MCPRegistryClient()
        assert client.base_url == REGISTRY_BASE_URL

    def test_custom_base_url(self):
        """Test custom base URL is used."""
        client = MCPRegistryClient(base_url="https://custom.registry.io/v1")
        assert client.base_url == "https://custom.registry.io/v1"

    def test_base_url_strips_trailing_slash(self):
        """Test trailing slash is stripped from base URL."""
        client = MCPRegistryClient(base_url="https://custom.registry.io/v1/")
        assert client.base_url == "https://custom.registry.io/v1"

    def test_custom_timeout(self):
        """Test custom timeout is used."""
        client = MCPRegistryClient(timeout=60.0)
        assert client.timeout == 60.0


class TestListServers:
    """Tests for list_servers method."""

    @pytest.mark.asyncio
    async def test_list_servers_success(self):
        """Test successful server listing."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "servers": [
                {"name": "server1", "description": "Test server 1"},
                {"name": "server2", "description": "Test server 2"},
            ],
            "metadata": {"cursor": "next_page"},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.list_servers(limit=10)

            assert len(result["servers"]) == 2
            assert result["servers"][0]["name"] == "server1"

    @pytest.mark.asyncio
    async def test_list_servers_with_cursor(self):
        """Test server listing with pagination cursor."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"servers": [], "metadata": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await client.list_servers(limit=10, cursor="page2")

            # Verify cursor was passed
            call_args = mock_client.get.call_args
            assert call_args[1]["params"]["cursor"] == "page2"

    @pytest.mark.asyncio
    async def test_list_servers_with_search(self):
        """Test server listing with search query."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"servers": [], "metadata": {}}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await client.list_servers(search="filesystem")

            # Verify search was passed
            call_args = mock_client.get.call_args
            assert call_args[1]["params"]["search"] == "filesystem"

    @pytest.mark.asyncio
    async def test_list_servers_http_error(self):
        """Test HTTP error handling."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server error", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await client.list_servers()

    @pytest.mark.asyncio
    async def test_list_servers_request_error(self):
        """Test request error handling (network failure)."""
        client = MCPRegistryClient()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=httpx.RequestError("Connection failed")
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(httpx.RequestError):
                await client.list_servers()


class TestGetServer:
    """Tests for get_server method."""

    @pytest.mark.asyncio
    async def test_get_server_success(self):
        """Test successful server retrieval."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "server": {
                "name": "test/server",
                "description": "A test server",
                "packages": [],
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_server("test/server")

            assert result["server"]["name"] == "test/server"

    @pytest.mark.asyncio
    async def test_get_server_not_found(self):
        """Test server not found returns None."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.get_server("nonexistent/server")

            assert result is None


class TestSearchServers:
    """Tests for search_servers method."""

    @pytest.mark.asyncio
    async def test_search_servers(self):
        """Test searching servers by query."""
        client = MCPRegistryClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "servers": [
                {"name": "matching-server-1"},
                {"name": "matching-server-2"},
            ],
            "metadata": {},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await client.search_servers("matching")

            assert len(result) == 2
            assert result[0]["name"] == "matching-server-1"


class TestGetServerConfig:
    """Tests for get_server_config method."""

    def test_npm_package_config(self):
        """Test config for NPM package."""
        client = MCPRegistryClient()

        server_data = {
            "server": {
                "name": "test/npm-server",
                "description": "NPM test server",
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "@test/mcp-server",
                    }
                ],
            }
        }

        result = client.get_server_config(server_data)

        assert result["type"] == "stdio"
        assert result["command"] == "npx"
        assert result["args"] == ["-y", "@test/mcp-server"]

    def test_pypi_package_config(self):
        """Test config for PyPI package."""
        client = MCPRegistryClient()

        server_data = {
            "server": {
                "name": "test/pypi-server",
                "packages": [
                    {
                        "registryType": "pypi",
                        "identifier": "mcp-server-test",
                    }
                ],
            }
        }

        result = client.get_server_config(server_data)

        assert result["type"] == "stdio"
        assert result["command"] == "uvx"
        assert result["args"] == ["mcp-server-test"]

    def test_oci_package_config(self):
        """Test config for OCI/Docker package."""
        client = MCPRegistryClient()

        server_data = {
            "server": {
                "name": "test/oci-server",
                "packages": [
                    {
                        "registryType": "oci",
                        "identifier": "docker.io/test/mcp-server:latest",
                    }
                ],
            }
        }

        result = client.get_server_config(server_data)

        assert result["type"] == "stdio"
        assert result["command"] == "docker"
        assert result["args"] == ["run", "-i", "--rm", "docker.io/test/mcp-server:latest"]

    def test_http_remote_config(self):
        """Test config for HTTP remote server."""
        client = MCPRegistryClient()

        server_data = {
            "server": {
                "name": "test/remote-server",
                "remotes": [
                    {
                        "url": "https://api.example.com/mcp",
                        "headers": [
                            {"name": "Authorization", "isRequired": True, "isSecret": True},
                        ],
                    }
                ],
            }
        }

        result = client.get_server_config(server_data)

        assert result["type"] == "http"
        assert result["url"] == "https://api.example.com/mcp"
        assert "headers_schema" in result

    def test_env_vars_schema(self):
        """Test environment variables schema extraction."""
        client = MCPRegistryClient()

        server_data = {
            "server": {
                "name": "test/server",
                "packages": [
                    {
                        "registryType": "npm",
                        "identifier": "@test/server",
                        "environmentVariables": [
                            {
                                "name": "API_KEY",
                                "description": "API key for authentication",
                                "isSecret": True,
                            },
                            {
                                "name": "DEBUG",
                                "description": "Enable debug mode",
                                "isSecret": False,
                            },
                        ],
                    }
                ],
            }
        }

        result = client.get_server_config(server_data)

        assert "env_schema" in result
        assert len(result["env_schema"]) == 2
        assert result["env_schema"][0]["name"] == "API_KEY"
        assert result["env_schema"][0]["secret"] is True
        assert result["env_schema"][1]["secret"] is False

    def test_handles_server_data_with_nested_server_key(self):
        """Test handling when server data has nested 'server' key."""
        client = MCPRegistryClient()

        server_data = {
            "server": {
                "name": "nested/server",
                "packages": [{"registryType": "npm", "identifier": "@test/pkg"}],
            }
        }

        result = client.get_server_config(server_data)
        assert result["name"] == "nested/server"

    def test_handles_server_data_without_nested_key(self):
        """Test handling when server data is flat."""
        client = MCPRegistryClient()

        server_data = {
            "name": "flat/server",
            "packages": [{"registryType": "pypi", "identifier": "pkg"}],
        }

        result = client.get_server_config(server_data)
        assert result["name"] == "flat/server"
