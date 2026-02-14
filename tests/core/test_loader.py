from __future__ import annotations

from pathlib import Path

from tests.helpers import import_core


def test_loader_detects_tool_decorator(tmp_path: Path):
    loader = import_core("app.registry.loader")

    file_path = tmp_path / "demo.py"
    file_path.write_text(
        """
from fastmcp.tools import tool

@tool
async def hello(name: str) -> str:
    \"\"\"Say hello.\"\"\"
    return f\"Hi {name}\"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    tools = loader.load_tools_from_file("demo", file_path)
    assert len(tools) == 1
    assert tools[0].name == "hello"
    assert tools[0].description == "Say hello."
    assert tools[0].input_schema["required"] == ["name"]
