"""
Shared pytest fixtures for ToolDock tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Ensure the project root is in the Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.registry import ToolRegistry, ToolDefinition, reset_registry
from app.loader import load_tools_from_directory


# ==================== Registry Fixtures ====================


@pytest.fixture
def registry() -> Generator[ToolRegistry, None, None]:
    """
    Fresh ToolRegistry instance for each test.

    Automatically resets the global registry after the test.
    """
    reset_registry()
    reg = ToolRegistry()
    yield reg
    reset_registry()


@pytest.fixture
def registry_with_tools(registry: ToolRegistry) -> ToolRegistry:
    """
    Registry pre-loaded with sample tools.
    """
    from pydantic import BaseModel, ConfigDict, Field

    class TestInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        message: str = Field(default="test", description="Test message")

    async def test_handler(payload: TestInput) -> str:
        return f"Received: {payload.message}"

    TestInput.model_rebuild(force=True)
    registry.register(
        ToolDefinition(
            name="test_tool",
            description="A test tool",
            input_model=TestInput,
            handler=test_handler,
        ),
        namespace="test",
    )
    return registry


# ==================== Auth Fixtures ====================


@pytest.fixture
def auth_token() -> str:
    """Test authentication token."""
    return "test_secret_token_12345"


@pytest.fixture
def auth_headers(auth_token: str) -> dict:
    """Authorization headers with test bearer token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def auth_env(auth_token: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """
    Set up authentication environment.

    Sets BEARER_TOKEN environment variable for tests.
    """
    monkeypatch.setenv("BEARER_TOKEN", auth_token)
    return auth_token


@pytest.fixture
def no_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable authentication by removing BEARER_TOKEN."""
    monkeypatch.delenv("BEARER_TOKEN", raising=False)


# ==================== Path Fixtures ====================


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_tools_dir(fixtures_dir: Path) -> Path:
    """Path to sample tools directory."""
    return fixtures_dir / "sample_tools"


@pytest.fixture
def temp_tools_dir(tmp_path: Path) -> Path:
    """
    Temporary directory for tools that gets cleaned up after tests.
    """
    tools_dir = tmp_path / "tools" / "test_namespace"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


@pytest.fixture
def temp_tool_file(temp_tools_dir: Path) -> Path:
    """
    Create a temporary valid tool file.
    """
    tool_code = '''"""Temporary test tool."""

from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry


class TempInput(BaseModel):
    """Input schema."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(default="default", description="Test value")


async def temp_handler(payload: TempInput) -> str:
    """Handle the tool."""
    return f"Temp: {payload.value}"


def register_tools(registry: ToolRegistry) -> None:
    """Register tools."""
    TempInput.model_rebuild(force=True)
    registry.register(
        ToolDefinition(
            name="temp_tool",
            description="A temporary test tool.",
            input_model=TempInput,
            handler=temp_handler,
        )
    )
'''
    tool_file = temp_tools_dir / "temp_tool.py"
    tool_file.write_text(tool_code)
    return tool_file


# ==================== Client Fixtures ====================


@pytest.fixture
def openapi_client(registry: ToolRegistry, auth_env: str):
    """
    TestClient for OpenAPI endpoints.

    Requires auth_env fixture to set up authentication.
    """
    from fastapi.testclient import TestClient
    from app.transports.openapi_server import create_openapi_app

    app = create_openapi_app(registry)
    return TestClient(app)


@pytest.fixture
def mcp_client(registry: ToolRegistry, auth_env: str):
    """
    TestClient for MCP HTTP endpoints.

    Requires auth_env fixture to set up authentication.
    """
    from fastapi.testclient import TestClient
    from app.transports.mcp_http_server import create_mcp_http_app

    app = create_mcp_http_app(registry)
    return TestClient(app)


@pytest.fixture
def web_client(registry: ToolRegistry, auth_env: str):
    """
    TestClient for Web GUI endpoints.

    Requires auth_env fixture to set up authentication.
    """
    from fastapi.testclient import TestClient
    from app.web.server import create_web_app

    app = create_web_app(registry)
    return TestClient(app)


# ==================== Environment Fixtures ====================


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Clean environment with no ToolDock-related env vars.
    """
    for var in ["BEARER_TOKEN", "DATA_DIR", "CORS_ORIGINS", "ADMIN_USERNAME"]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Temporary data directory for tests.

    Creates the expected subdirectory structure.
    """
    data = tmp_path / "tooldock_data"
    (data / "tools" / "shared").mkdir(parents=True)
    (data / "external").mkdir(parents=True)
    (data / "config").mkdir(parents=True)

    monkeypatch.setenv("DATA_DIR", str(data))
    return data


# ==================== Helper Functions ====================


def create_tool_file(directory: Path, name: str, tool_name: str) -> Path:
    """
    Helper to create a valid tool file in a directory.

    Args:
        directory: Directory to create the file in
        name: Python file name (without .py)
        tool_name: Name of the tool to register

    Returns:
        Path to the created file
    """
    code = f'''"""Auto-generated test tool: {tool_name}."""

from pydantic import BaseModel, ConfigDict, Field
from app.registry import ToolDefinition, ToolRegistry


class {tool_name.title().replace("_", "")}Input(BaseModel):
    """Input schema."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(default="default", description="Test value")


async def {name}_handler(payload):
    """Handle the tool."""
    return f"Result: {{payload.value}}"


def register_tools(registry: ToolRegistry) -> None:
    """Register tools."""
    {tool_name.title().replace("_", "")}Input.model_rebuild(force=True)
    registry.register(
        ToolDefinition(
            name="{tool_name}",
            description="Test tool: {tool_name}",
            input_model={tool_name.title().replace("_", "")}Input,
            handler={name}_handler,
        )
    )
'''
    file_path = directory / f"{name}.py"
    file_path.write_text(code)
    return file_path
