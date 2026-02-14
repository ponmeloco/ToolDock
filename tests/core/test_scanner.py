from __future__ import annotations

from pathlib import Path

from tests.helpers import import_core


def test_scanner_finds_valid_namespaces(tmp_path: Path):
    scanner = import_core("app.registry.scanner")

    tools_dir = tmp_path / "tools"
    (tools_dir / "github").mkdir(parents=True)
    (tools_dir / "_ignored").mkdir(parents=True)
    (tools_dir / "Bad.Name").mkdir(parents=True)

    (tools_dir / "github" / "issues.py").write_text(
        """
from fastmcp.tools import tool

@tool
def list_issues(owner: str, repo: str) -> list:
    \"\"\"List issues.\"\"\"
    return []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    namespaces = scanner.scan_namespaces(tools_dir)
    assert set(namespaces) == {"github"}
    assert namespaces["github"].tool_count == 1
