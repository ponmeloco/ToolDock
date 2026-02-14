"""Built-in MCP server that manages FastMCP installs through ToolDock APIs.

Recommended workflow for agents:
1. Call `search_registry_servers` (or gather `repo_url`) to identify candidate server.
2. Call `assess_server_safety` before any install.
3. Install with `install_registry_server` or `install_repo_server`.
4. Optionally call `update_server_runtime` for command/env edits.
5. Call `start_server` and validate behavior in ToolDock playground.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ToolDock Installer")


def _api_base() -> str:
    explicit = os.getenv("TOOLDOCK_INSTALLER_API_BASE", "").strip()
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("TOOLDOCK_INSTALLER_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("WEB_PORT") or os.getenv("WEB_PUBLIC_PORT") or "8080"
    return f"http://{host}:{port}/api"


def _auth_headers() -> Dict[str, str]:
    token = os.getenv("TOOLDOCK_BEARER_TOKEN", "").strip() or os.getenv("BEARER_TOKEN", "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{_api_base()}{path}"
    with httpx.Client(timeout=45.0) as client:
        kwargs: Dict[str, Any] = {"headers": _auth_headers()}
        if payload is not None:
            kwargs["json"] = payload
        response = client.request(method, url, **kwargs)

    if response.status_code >= 400:
        detail = response.text
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("detail") or body)
        except Exception:
            pass
        raise RuntimeError(f"{method} {path} failed ({response.status_code}): {detail}")

    if not response.content:
        return {"success": True}
    return response.json()


@mcp.tool()
def get_instructions() -> str:
    """Get usage instructions for all ToolDock installer tools.

    CALL THIS FIRST before using any other tool in this namespace.
    Returns a guide explaining the available tools, their purpose,
    required parameters, and the recommended workflow.
    """
    return """# ToolDock Installer — Tool Guide

You are connected to the ToolDock Installer, a management interface for
installing and running external MCP servers inside ToolDock.

## Available Tools

### Discovery
- **search_registry_servers(query, limit=20)**
  Search the MCP Registry for installable servers by keyword.
  Returns a list of servers with id, name, description, and package type (npm/pypi/repo).

- **list_installed_servers()**
  List all servers currently installed in ToolDock with their id, namespace, status, and config.
  Use this to find server IDs for start/stop/update operations.

### Safety
- **assess_server_safety(server_id?, server_name?, repo_url?, command?, args?)**
  Run a pre-install safety assessment. Returns risk level and a `blocked` flag.
  ALWAYS call this before installing. If `blocked=true`, do NOT proceed with install.
  Pass either `server_id`/`server_name` (for registry) or `repo_url` (for repo installs).

### Installation
- **install_registry_server(server_id?, server_name?, namespace, version?, env?, config_file?)**
  Install a server from the MCP Registry. Requires `namespace` (unique name for this server).
  At least one of `server_id` or `server_name` is required.
  Use `env` to pass API keys (e.g. `{"GITHUB_TOKEN": "ghp_xxx"}`).

- **install_repo_server(repo_url, namespace, entrypoint?, server_name?, auto_start?, env?)**
  Install a server from a Git repository URL. Requires `repo_url` and `namespace`.
  Use `entrypoint` if the server script is not at the repo root.

### Lifecycle
- **update_server_runtime(server_id, command?, args?, env?, auto_start?)**
  Update startup command, arguments, environment variables, or auto-start setting.
  Use after install to configure API keys or adjust the startup command.

- **start_server(server_id)**
  Start an installed server. The server becomes available at `/{namespace}/mcp`.

- **stop_server(server_id)**
  Stop a running server.

## Recommended Workflow

1. **Search**: `search_registry_servers("github")` to find servers
2. **Safety check**: `assess_server_safety(server_name="...")` — abort if blocked
3. **Install**: `install_registry_server(server_name="...", namespace="my-server")`
4. **Configure** (if needed): `update_server_runtime(server_id=..., env={"API_KEY": "..."})`
5. **Start**: `start_server(server_id=...)`
6. The server's tools are now available at `/{namespace}/mcp`

## Important Notes
- Each server needs a unique `namespace` — this becomes its URL path segment.
- Namespace names must be lowercase alphanumeric with hyphens (e.g. `github-tools`).
- Always run safety checks before installing. Never skip this step.
- Server IDs are integers returned by `list_installed_servers()` or install tools.
- The `tooldock-installer` namespace itself is protected and cannot be deleted.
"""


@mcp.tool()
def search_registry_servers(query: str, limit: int = 20) -> Dict[str, Any]:
    """Find installable MCP servers in the registry.

    Use this when the user asks to discover a server by keyword.
    Follow with `assess_server_safety` on selected results.
    """
    limit = max(1, min(limit, 100))
    return _request("GET", f"/fastmcp/registry/servers?search={query}&limit={limit}")


@mcp.tool()
def assess_server_safety(
    server_id: Optional[str] = None,
    server_name: Optional[str] = None,
    repo_url: Optional[str] = None,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run pre-install safety checks for registry or repo installs.

    Use this before `install_registry_server` or `install_repo_server`.
    If response `blocked=true`, do not install until failing checks are resolved.
    """
    payload: Dict[str, Any] = {}
    if server_id:
        payload["server_id"] = server_id
    if server_name:
        payload["server_name"] = server_name
    if repo_url:
        payload["repo_url"] = repo_url
    if command:
        payload["command"] = command
    if args:
        payload["args"] = args
    return _request("POST", "/fastmcp/safety/check", payload)


@mcp.tool()
def install_registry_server(
    server_id: Optional[str],
    server_name: Optional[str],
    namespace: str,
    version: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    config_file: Optional[str] = None,
    config_filename: str = "config.yaml",
) -> Dict[str, Any]:
    """Install a server from MCP Registry into ToolDock FastMCP.

    Use when you already have `server_id` or a specific `server_name`.
    Prefer calling `assess_server_safety` first.
    """
    payload: Dict[str, Any] = {"namespace": namespace}
    if server_id:
        payload["server_id"] = server_id
    if server_name:
        payload["server_name"] = server_name
    if version:
        payload["version"] = version
    if env is not None:
        payload["env"] = env
    if config_file:
        payload["config_file"] = config_file
        payload["config_filename"] = config_filename
    return _request("POST", "/fastmcp/servers", payload)


@mcp.tool()
def install_repo_server(
    repo_url: str,
    namespace: str,
    entrypoint: Optional[str] = None,
    server_name: Optional[str] = None,
    auto_start: bool = False,
    env: Optional[Dict[str, str]] = None,
    config_file: Optional[str] = None,
    config_filename: str = "config.yaml",
) -> Dict[str, Any]:
    """Install a FastMCP server from a Git repository URL.

    Use for direct repo onboarding when registry metadata is missing.
    Prefer calling `assess_server_safety(repo_url=...)` first.
    """
    payload: Dict[str, Any] = {
        "repo_url": repo_url,
        "namespace": namespace,
        "auto_start": auto_start,
    }
    if entrypoint:
        payload["entrypoint"] = entrypoint
    if server_name:
        payload["server_name"] = server_name
    if env is not None:
        payload["env"] = env
    if config_file:
        payload["config_file"] = config_file
        payload["config_filename"] = config_filename
    return _request("POST", "/fastmcp/servers/repo", payload)


@mcp.tool()
def list_installed_servers() -> List[Dict[str, Any]]:
    """List FastMCP servers currently known by ToolDock.

    Use to discover IDs/status before start/stop/update operations.
    """
    data = _request("GET", "/fastmcp/servers")
    if isinstance(data, list):
        return data
    return []


@mcp.tool()
def update_server_runtime(
    server_id: int,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    auto_start: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update runtime command/args/env/autostart for an installed server.

    Use after install to set API keys, URLs, or startup command adjustments.
    """
    payload: Dict[str, Any] = {}
    if command is not None:
        payload["command"] = command
    if args is not None:
        payload["args"] = args
    if env is not None:
        payload["env"] = env
    if auto_start is not None:
        payload["auto_start"] = auto_start
    return _request("PUT", f"/fastmcp/servers/{server_id}", payload)


@mcp.tool()
def start_server(server_id: int) -> Dict[str, Any]:
    """Start an installed server by ID."""
    return _request("POST", f"/fastmcp/servers/{server_id}/start")


@mcp.tool()
def stop_server(server_id: int) -> Dict[str, Any]:
    """Stop a running server by ID."""
    return _request("POST", f"/fastmcp/servers/{server_id}/stop")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
