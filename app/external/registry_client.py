"""
MCP Registry Client.

Provides access to the official MCP Registry API at
https://registry.modelcontextprotocol.io
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io/v0.1"
DEFAULT_TIMEOUT = 30.0


class MCPRegistryClient:
    """Client for the MCP Registry API."""

    def __init__(self, base_url: str = REGISTRY_BASE_URL, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def list_servers(
        self,
        limit: int = 30,
        cursor: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List servers from the MCP Registry.

        Args:
            limit: Maximum number of servers to return
            cursor: Pagination cursor for next page
            search: Search query to filter servers

        Returns:
            Dict with 'servers' list and 'metadata' for pagination
        """
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if search:
            params["search"] = search

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/servers",
                    params=params,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Registry API error: {e.response.status_code}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Registry request failed: {e}")
                raise

    async def get_server(self, server_ref: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific server by registry reference.

        Args:
            server_ref: Registry server ID (UUID) or name

        Returns:
            Server metadata dict or None if not found
        """
        return await self.get_server_by_id(server_ref)

    async def get_server_by_id(self, server_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific server by registry ID.

        Args:
            server_id: Registry server ID (UUID)

        Returns:
            Server metadata dict or None if not found
        """
        encoded_id = quote(server_id, safe="")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/servers/{encoded_id}")
                if response.status_code == 404:
                    logger.warning(f"Server not found: {server_id}")
                    return None
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Failed to get server {server_id}: {e.response.status_code}")
                raise
            except httpx.RequestError as e:
                logger.error(f"Request failed for server {server_id}: {e}")
                raise

    async def get_server_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a server by name via search.

        Args:
            name: Full server name (e.g., 'io.github.modelcontextprotocol/server-filesystem')

        Returns:
            Server metadata dict or None if not found
        """
        result = await self.list_servers(limit=10, search=name)
        for entry in result.get("servers", []):
            server = entry.get("server", entry)
            if isinstance(server, dict) and server.get("name") == name:
                server_id = server.get("id") or entry.get("id")
                if server_id:
                    return await self.get_server_by_id(str(server_id))
                return entry
        logger.warning(f"Server not found by name: {name}")
        return None

    async def search_servers(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Search for servers by query.

        Args:
            query: Search query string
            limit: Maximum results to return

        Returns:
            List of matching server metadata dicts
        """
        result = await self.list_servers(limit=limit, search=query)
        return result.get("servers", [])

    def get_server_config(self, server_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert registry server metadata to internal config format.

        Args:
            server_data: Raw server data from registry API

        Returns:
            Config dict with command, args, env, etc.
        """
        server = server_data.get("server", server_data)
        config: Dict[str, Any] = {
            "name": server.get("name", "unknown"),
            "description": server.get("description", ""),
            "version": server.get("version", ""),
        }

        # Check for package-based servers (STDIO transport)
        packages = server.get("packages", [])
        if packages:
            pkg = packages[0]  # Use first package
            registry_type = pkg.get("registryType", "").lower()
            identifier = pkg.get("identifier", "")

            if registry_type == "npm":
                config["type"] = "stdio"
                config["command"] = "npx"
                config["args"] = ["-y", identifier]
            elif registry_type == "pypi":
                config["type"] = "stdio"
                config["command"] = "uvx"
                config["args"] = [identifier]
            elif registry_type == "oci":
                config["type"] = "stdio"
                config["command"] = "docker"
                config["args"] = ["run", "-i", "--rm", identifier]

            # Environment variables from package
            env_vars = pkg.get("environmentVariables", [])
            if env_vars:
                config["env_schema"] = [
                    {
                        "name": ev.get("name"),
                        "description": ev.get("description", ""),
                        "required": not ev.get("isSecret", False),
                        "secret": ev.get("isSecret", False),
                    }
                    for ev in env_vars
                ]

        # Check for remote servers (HTTP transport)
        remotes = server.get("remotes", [])
        if remotes and not packages:
            remote = remotes[0]  # Use first remote
            config["type"] = "http"
            config["url"] = remote.get("url", "")

            # Headers
            headers = remote.get("headers", [])
            if headers:
                config["headers_schema"] = [
                    {
                        "name": h.get("name"),
                        "description": h.get("description", ""),
                        "required": h.get("isRequired", False),
                        "secret": h.get("isSecret", False),
                    }
                    for h in headers
                ]

        return config
