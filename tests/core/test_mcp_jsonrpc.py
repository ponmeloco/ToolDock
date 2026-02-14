from __future__ import annotations

from tests.helpers import import_core


def test_jsonrpc_rejects_batch_for_2025_11_25():
    jsonrpc = import_core("app.mcp.jsonrpc")
    body = b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]'
    payload = jsonrpc.parse_request(body, "2025-11-25")
    assert payload["error"]["code"] == jsonrpc.INVALID_REQUEST


def test_jsonrpc_allows_batch_for_2025_03_26():
    jsonrpc = import_core("app.mcp.jsonrpc")
    body = b'[{"jsonrpc":"2.0","id":1,"method":"ping"}]'
    payload = jsonrpc.parse_request(body, "2025-03-26")
    assert isinstance(payload, list)
    assert payload[0]["method"] == "ping"
