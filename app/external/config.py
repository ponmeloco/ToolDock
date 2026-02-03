"""
External Server Configuration Management.

Loads server configurations from YAML and applies them to the manager.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.external.registry_client import MCPRegistryClient

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "tools/external/config.yaml"


class ExternalServerConfig:
    """
    Manages external server configuration from YAML files.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize config manager.

        Args:
            config_path: Path to config.yaml (default: tools/external/config.yaml)
        """
        self.config_path = Path(config_path or DEFAULT_CONFIG_PATH)
        self._config: Dict[str, Any] = {}
        self._registry_client = MCPRegistryClient()

    def load(self) -> Dict[str, Any]:
        """
        Load configuration from YAML file.

        Returns:
            Loaded configuration dict

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}")
            return {"servers": {}, "settings": {}}

        logger.info(f"Loading config from {self.config_path}")

        with open(self.config_path, "r") as f:
            self._config = yaml.safe_load(f) or {}

        # Ensure servers and settings are dicts (not None)
        if self._config.get("servers") is None:
            self._config["servers"] = {}
        if self._config.get("settings") is None:
            self._config["settings"] = {}

        # Substitute environment variables
        self._config = self._substitute_env_vars(self._config)

        return self._config

    def save(self, config: Dict[str, Any]) -> None:
        """
        Save configuration to YAML file.

        Args:
            config: Configuration dict to save
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.config_path, "w") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Config saved to {self.config_path}")

    def _substitute_env_vars(self, obj: Any) -> Any:
        """Recursively substitute ${VAR} patterns with environment values."""
        if isinstance(obj, str):
            # Match ${VAR_NAME} pattern
            pattern = r"\$\{([^}]+)\}"

            def replace(match: re.Match) -> str:
                var_name = match.group(1)
                value = os.environ.get(var_name, "")
                if not value:
                    logger.warning(f"Environment variable not set: {var_name}")
                return value

            return re.sub(pattern, replace, obj)

        elif isinstance(obj, dict):
            return {k: self._substitute_env_vars(v) for k, v in obj.items()}

        elif isinstance(obj, list):
            return [self._substitute_env_vars(item) for item in obj]

        return obj

    async def get_server_config(self, server_id: str, server_def: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build complete server config from definition.

        Args:
            server_id: Server identifier
            server_def: Server definition from config file

        Returns:
            Complete config ready for MCPServerProxy
        """
        source = server_def.get("source", "custom")

        if source == "registry":
            # Fetch from MCP Registry
            registry_name = server_def.get("name")
            if not registry_name:
                raise ValueError(f"Server {server_id}: 'name' required for registry source")

            logger.info(f"Fetching {server_id} from registry: {registry_name}")

            server_data = await self._registry_client.get_server(registry_name)
            if not server_data:
                raise ValueError(f"Server not found in registry: {registry_name}")

            config = self._registry_client.get_server_config(server_data)

            # Override with local env vars
            if "env" in server_def:
                config["env"] = server_def["env"]

            # Override args if provided
            if "args" in server_def:
                config["args"] = config.get("args", []) + server_def["args"]

            return config

        else:
            # Custom configuration
            config: Dict[str, Any] = {
                "type": server_def.get("type", "stdio"),
            }

            if config["type"] == "stdio":
                config["command"] = server_def.get("command")
                config["args"] = server_def.get("args", [])
                config["env"] = server_def.get("env", {})

                if not config["command"]:
                    raise ValueError(f"Server {server_id}: 'command' required for stdio type")

            elif config["type"] == "http":
                config["url"] = server_def.get("url")
                config["headers"] = server_def.get("headers", {})

                if not config["url"]:
                    raise ValueError(f"Server {server_id}: 'url' required for http type")

            return config

    async def apply(self, manager: "ExternalServerManager") -> Dict[str, Any]:
        """
        Apply configuration by loading all enabled servers.

        Args:
            manager: ExternalServerManager to add servers to

        Returns:
            Summary of applied servers
        """
        from app.external.server_manager import ExternalServerManager

        config = self.load()
        servers_config = config.get("servers") or {}

        results = {
            "loaded": [],
            "failed": [],
            "skipped": [],
        }

        if not servers_config:
            logger.info("No external servers configured")
            return results

        for server_id, server_def in servers_config.items():
            if not server_def:
                continue

            # Check if enabled
            if not server_def.get("enabled", True):
                logger.debug(f"Server {server_id} is disabled, skipping")
                results["skipped"].append(server_id)
                continue

            try:
                server_config = await self.get_server_config(server_id, server_def)
                await manager.add_server(server_id, server_config)
                results["loaded"].append(server_id)

            except Exception as e:
                logger.error(f"Failed to load server {server_id}: {e}")
                results["failed"].append({"server_id": server_id, "error": str(e)})

        logger.info(
            f"Config applied: {len(results['loaded'])} loaded, "
            f"{len(results['failed'])} failed, {len(results['skipped'])} skipped"
        )

        return results

    async def build_enabled_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        Build configs for all enabled servers.

        Returns:
            Dict mapping server_id -> config dict
        """
        config = self.load()
        servers_config = config.get("servers") or {}

        enabled: Dict[str, Dict[str, Any]] = {}

        if not servers_config:
            logger.info("No external servers configured")
            return enabled

        for server_id, server_def in servers_config.items():
            if not server_def:
                continue

            if not server_def.get("enabled", True):
                logger.debug(f"Server {server_id} is disabled, skipping")
                continue

            server_config = await self.get_server_config(server_id, server_def)
            enabled[server_id] = server_config

        return enabled

    def add_server_to_config(
        self,
        server_id: str,
        source: str,
        name: Optional[str] = None,
        enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Add a server definition to the config file.

        Args:
            server_id: Unique server identifier
            source: 'registry' or 'custom'
            name: Registry name (for registry source)
            enabled: Whether server is enabled
            **kwargs: Additional config options
        """
        config = self.load()

        if "servers" not in config:
            config["servers"] = {}

        server_def: Dict[str, Any] = {
            "source": source,
            "enabled": enabled,
        }

        if source == "registry" and name:
            server_def["name"] = name

        server_def.update(kwargs)

        config["servers"][server_id] = server_def

        self.save(config)
        logger.info(f"Added server {server_id} to config")

    def remove_server_from_config(self, server_id: str) -> bool:
        """
        Remove a server definition from the config file.

        Args:
            server_id: Server identifier to remove

        Returns:
            True if removed, False if not found
        """
        config = self.load()
        servers = config.get("servers", {})

        if server_id not in servers:
            return False

        del servers[server_id]
        self.save(config)
        logger.info(f"Removed server {server_id} from config")
        return True
