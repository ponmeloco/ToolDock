from __future__ import annotations

import asyncio
import importlib

from tests.helpers import import_manager


def _manager_modules():
    import_manager("app.config")
    config = importlib.import_module("app.config")
    methods = importlib.import_module("app.mcp.methods")
    session = importlib.import_module("app.mcp.session")
    stream = importlib.import_module("app.mcp.stream")
    service = importlib.import_module("app.tools.service")
    return config, methods, session, stream, service


def _service(tmp_path, monkeypatch):
    config, _, _, _, service_mod = _manager_modules()
    monkeypatch.setenv("BEARER_TOKEN", "x")
    monkeypatch.setenv("MANAGER_INTERNAL_TOKEN", "y")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_INSECURE_SECRETS", "1")
    settings = config.ManagerSettings()
    return service_mod.ManagerToolService(settings, started_at=0.0)


def _methods(service):
    _, methods_mod, session_mod, stream_mod, _ = _manager_modules()
    sessions = session_mod.SessionManager(ttl_seconds=60, supported_versions=["2025-11-25"])
    streams = stream_mod.StreamManager()
    methods = methods_mod.ManagerMcpMethods(service, sessions, streams)
    session = sessions.create("2025-11-25")
    sessions.mark_initialized(session.session_id)
    return methods, session


def test_first_call_tool_is_first_and_returns_usage(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    descriptors = service.list_tool_descriptors()

    assert descriptors[0]["name"] == "a_first_call_instructions"
    assert descriptors[0]["input_schema"]["type"] == "object"
    assert descriptors[0]["input_schema"]["properties"] == {}

    guide = asyncio.run(service.call_tool("a_first_call_instructions", {}))
    tools = {item["name"]: item for item in guide["tools"]}

    assert "create_namespace" in tools
    assert "get_tool_template" in tools
    assert tools["create_namespace"]["required_parameters"] == ["name"]
    assert tools["get_tool_template"]["required_parameters"] == []
    assert tools["write_tool"]["required_parameters"] == ["namespace", "filename", "code"]
    assert "get_tool_template and mirror its structure." in guide["workflow"][2]


def test_tools_list_uses_descriptor_input_schema(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    methods, session = _methods(service)

    payload = asyncio.run(methods.dispatch("tools/list", {}, session))
    assert payload is not None

    tools = {item["name"]: item for item in payload["tools"]}
    assert payload["tools"][0]["name"] == "a_first_call_instructions"
    assert tools["create_namespace"]["inputSchema"]["required"] == ["name"]
    assert "required" not in tools["get_tool_template"]["inputSchema"]
    assert tools["write_tool"]["inputSchema"]["required"] == ["namespace", "filename", "code"]
    assert "required" not in tools["list_namespaces"]["inputSchema"]


def test_get_tool_template_returns_fastmcp_example(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)

    template = asyncio.run(service.call_tool("get_tool_template", {}))
    assert template["ok"] is True
    assert template["template_name"] == "fastmcp-basic"
    assert "FastMCP" in template["code"]
    assert "@mcp.tool()" in template["code"]


def test_write_tool_rejects_unbound_bare_tool_decorator(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    asyncio.run(service.call_tool("create_namespace", {"name": "demo"}))
    code = """@tool
def ping(name: str) -> str:
    \"\"\"Test.\"\"\"
    return name
"""
    result = asyncio.run(
        service.call_tool(
            "write_tool",
            {
                "namespace": "demo",
                "filename": "bad_tool.py",
                "code": code,
            },
        )
    )
    assert result["written"] is False
    assert result["error"] == "Bare @tool decorator is not defined in this file"


def test_tools_call_list_result_has_no_structured_content(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    methods, session = _methods(service)

    payload = asyncio.run(
        methods.dispatch("tools/call", {"name": "list_namespaces", "arguments": {}}, session)
    )
    assert payload is not None
    assert payload.get("isError") is not True
    assert "structuredContent" not in payload
    assert payload["content"][0]["text"] == "[]"


def test_tools_call_missing_required_argument_returns_explicit_error(tmp_path, monkeypatch):
    service = _service(tmp_path, monkeypatch)
    methods, session = _methods(service)

    payload = asyncio.run(
        methods.dispatch("tools/call", {"name": "list_tools", "arguments": {}}, session)
    )
    assert payload is not None
    assert payload.get("isError") is True
    assert "Missing required arguments for list_tools: namespace" in payload["content"][0]["text"]
