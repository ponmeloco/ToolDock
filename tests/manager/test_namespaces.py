from __future__ import annotations

from tests.helpers import import_manager


def test_create_and_list_namespace(tmp_path, monkeypatch):
    config = import_manager("app.config")
    monkeypatch.setenv("BEARER_TOKEN", "x")
    monkeypatch.setenv("MANAGER_INTERNAL_TOKEN", "y")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_INSECURE_SECRETS", "1")

    settings = config.ManagerSettings()
    namespaces_mod = import_manager("app.tools.namespaces")
    tool = namespaces_mod.NamespaceTools(settings)

    created = tool.create_namespace("github")
    assert created["created"] is True

    listed = tool.list_namespaces()
    assert any(item["name"] == "github" for item in listed)
