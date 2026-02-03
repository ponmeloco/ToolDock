from __future__ import annotations

from pathlib import Path

import pytest

from app import deps


def test_get_venv_dir_uses_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert deps.get_venv_dir("team1") == tmp_path / "venvs" / "team1"


def test_get_site_packages_path(tmp_path: Path):
    venv_dir = tmp_path / "venv"
    site_path = deps.get_site_packages_path(venv_dir)
    assert "site-packages" in str(site_path)


def test_install_packages_validates_specs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", "/tmp")
    with pytest.raises(ValueError):
        deps.install_packages("shared", ["bad package"])


def test_install_packages_calls_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def fake_run(cmd, check, capture_output, text):
        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return Result()

    def fake_ensure(namespace: str):
        venv_dir = tmp_path / "venvs" / namespace
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").write_text("")
        return venv_dir

    monkeypatch.setattr(deps, "ensure_venv", fake_ensure)
    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    result = deps.install_packages("shared", ["requests==2.32.0"])
    assert result["success"] is True


def test_uninstall_packages_calls_subprocess(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def fake_run(cmd, check, capture_output, text):
        class Result:
            returncode = 0
            stdout = "ok"
            stderr = ""
        return Result()

    def fake_ensure(namespace: str):
        venv_dir = tmp_path / "venvs" / namespace
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").write_text("")
        return venv_dir

    monkeypatch.setattr(deps, "ensure_venv", fake_ensure)
    monkeypatch.setattr(deps.subprocess, "run", fake_run)

    result = deps.uninstall_packages("shared", ["requests"])
    assert result["success"] is True


def test_delete_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    venv_dir = tmp_path / "venvs" / "shared"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("")

    deleted = deps.delete_venv("shared")
    assert deleted is True
    assert not venv_dir.exists()
