from __future__ import annotations

from tests.helpers import import_manager


def test_prepare_set_and_check_secret(tmp_path, monkeypatch):
    config = import_manager("app.config")
    monkeypatch.setenv("BEARER_TOKEN", "x")
    monkeypatch.setenv("MANAGER_INTERNAL_TOKEN", "y")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALLOW_INSECURE_SECRETS", "1")

    settings = config.ManagerSettings()

    # namespace + tooldock.yaml declaring secret
    ns_dir = tmp_path / "tools" / "github"
    ns_dir.mkdir(parents=True)
    (ns_dir / "tooldock.yaml").write_text("secrets:\n  - GITHUB_TOKEN\n", encoding="utf-8")

    store_mod = import_manager("app.tools.secrets_store")
    store = store_mod.ManagerSecretsStore(settings)

    prep = store.prepare_secret("GITHUB_TOKEN")
    assert prep["scope"] == "global"

    check = store.check_namespace("github")
    assert check["placeholders"] == ["GITHUB_TOKEN"]

    updated = store.set_secret("GITHUB_TOKEN", "abc123")
    assert updated["updated"] is True

    check2 = store.check_namespace("github")
    assert check2["satisfied"] == ["GITHUB_TOKEN"]
