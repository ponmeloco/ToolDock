"""End-to-end FastMCP tests with a real external toolserver process."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.db.database import init_db, reset_engine
from app.registry import ToolRegistry, reset_registry
from app.web.server import create_web_app
from tests.utils.sync_client import SyncASGIClient


@pytest.fixture
def e2e_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_registry()
    registry = ToolRegistry()

    data_dir = tmp_path / "tooldock_data"
    (data_dir / "tools" / "shared").mkdir(parents=True, exist_ok=True)
    (data_dir / "external").mkdir(parents=True, exist_ok=True)
    (data_dir / "config").mkdir(parents=True, exist_ok=True)
    (data_dir / "db").mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("BEARER_TOKEN", "test_token")
    monkeypatch.setenv("FASTMCP_DEMO_ENABLED", "false")
    monkeypatch.setenv("FASTMCP_INSTALLER_ENABLED", "false")

    reset_engine()
    init_db()

    app = create_web_app(registry)
    client = SyncASGIClient(app)
    try:
        yield client, data_dir
    finally:
        client.close()
        reset_engine()
        reset_registry()


def test_fastmcp_real_hello_server_roundtrip(e2e_client):
    client, data_dir = e2e_client
    headers = {"Authorization": "Bearer test_token"}

    script_path = data_dir / "hello_mcp_server.py"
    script_path.write_text(
        """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("HelloE2E")

@mcp.tool()
def hello_tool(name: str = "World") -> str:
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()
""".strip()
        + "\n",
        encoding="utf-8",
    )

    add_response = client.post(
        "/api/fastmcp/servers/manual",
        headers=headers,
        json={
            "namespace": "helloe2e",
            "server_name": "Hello E2E",
            "command": "python",
            "args": [str(script_path)],
            "auto_start": False,
        },
    )
    assert add_response.status_code == 200, add_response.text
    server_id = add_response.json()["id"]

    start_response = client.post(
        f"/api/fastmcp/servers/{server_id}/start",
        headers=headers,
    )
    assert start_response.status_code == 200, start_response.text
    assert start_response.json()["status"] == "running"

    tool_name = "helloe2e:hello_tool"
    found = False
    for _ in range(12):
        sync_response = client.post("/api/fastmcp/sync", headers=headers)
        assert sync_response.status_code == 200
        tools_response = client.get("/api/playground/tools", headers=headers)
        assert tools_response.status_code == 200
        tools = tools_response.json()["tools"]
        if any(t["name"] == tool_name for t in tools):
            found = True
            break
        time.sleep(0.5)

    assert found, "External hello tool was not exposed in playground listing"

    exec_response = client.post(
        "/api/playground/execute",
        headers=headers,
        json={
            "tool_name": tool_name,
            "transport": "direct",
            "arguments": {"name": "Tester"},
        },
    )
    assert exec_response.status_code == 200, exec_response.text
    payload = exec_response.json()
    assert payload["success"] is True
    assert payload["tool"] == tool_name
    text = payload["result"]["content"][0]["text"]
    assert "Hello, Tester!" in text

    stop_response = client.post(
        f"/api/fastmcp/servers/{server_id}/stop",
        headers=headers,
    )
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopped"

    delete_response = client.delete(
        f"/api/fastmcp/servers/{server_id}",
        headers=headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True
