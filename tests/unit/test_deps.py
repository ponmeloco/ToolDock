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


def test_delete_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    venv_dir = tmp_path / "venvs" / "shared"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").write_text("")

    deleted = deps.delete_venv("shared")
    assert deleted is True
    assert not venv_dir.exists()


def test_uninstall_packages_blocks_pip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def fake_ensure(namespace: str):
        venv_dir = tmp_path / "venvs" / namespace
        (venv_dir / "bin").mkdir(parents=True)
        (venv_dir / "bin" / "python").write_text("")
        return venv_dir

    monkeypatch.setattr(deps, "ensure_venv", fake_ensure)

    with pytest.raises(ValueError):
        deps.uninstall_packages("shared", ["pip"])


# ── npm validation ──


class TestNpmPkgPattern:
    """Tests for the _NPM_PKG_PATTERN regex."""

    @pytest.mark.parametrize(
        "spec",
        [
            "some-package",
            "@modelcontextprotocol/server-fetch",
            "@scope/pkg@1.2.3",
            "my_package@latest",
            "simple",
        ],
    )
    def test_valid_npm_specs(self, spec: str):
        assert deps._NPM_PKG_PATTERN.match(spec) is not None

    @pytest.mark.parametrize(
        "spec",
        [
            "",
            "bad package",
            "has space@1.0",
            "/leading-slash",
        ],
    )
    def test_invalid_npm_specs(self, spec: str):
        assert deps._NPM_PKG_PATTERN.match(spec) is None


class TestValidateNpmPackage:
    """Tests for validate_npm_package()."""

    def test_success(self, monkeypatch: pytest.MonkeyPatch):
        def fake_run(cmd, check, capture_output, text):
            class Result:
                returncode = 0
                stdout = "@modelcontextprotocol/server-fetch\n1.2.0"
                stderr = ""
            return Result()

        monkeypatch.setattr(deps.subprocess, "run", fake_run)
        result = deps.validate_npm_package("@modelcontextprotocol/server-fetch")
        assert result["success"] is True
        assert "@modelcontextprotocol/server-fetch" in result["stdout"]

    def test_not_found(self, monkeypatch: pytest.MonkeyPatch):
        def fake_run(cmd, check, capture_output, text):
            class Result:
                returncode = 1
                stdout = ""
                stderr = "npm ERR! 404 Not Found"
            return Result()

        monkeypatch.setattr(deps.subprocess, "run", fake_run)
        result = deps.validate_npm_package("nonexistent-pkg-xyz")
        assert result["success"] is False

    def test_invalid_spec_skips_subprocess(self):
        result = deps.validate_npm_package("bad package")
        assert result["success"] is False
        assert "Invalid" in result["stderr"]
