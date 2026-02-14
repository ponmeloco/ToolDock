from __future__ import annotations

from tests.helpers import import_core


def test_session_resolves_protocol_fallback():
    session_mod = import_core("app.mcp.session")
    manager = session_mod.SessionManager(3600, ["2025-11-25", "2025-03-26"])

    session = manager.create("2025-11-25")
    assert manager.resolve_protocol(None, session.session_id) == "2025-11-25"
    assert manager.resolve_protocol(None, None) == "2025-03-26"
