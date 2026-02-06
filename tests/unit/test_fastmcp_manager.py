"""Unit tests for FastMCP server manager install logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from app.db.database import get_db
from app.db.models import ExternalFastMCPServer
from app.external.fastmcp_manager import FastMCPServerManager, _safe_rmtree_under


def _make_record(db, **overrides) -> ExternalFastMCPServer:
    defaults = dict(
        server_name="test-server",
        namespace=f"test_{uuid4().hex[:8]}",
        install_method="package",
        status="installing",
    )
    defaults.update(overrides)
    record = ExternalFastMCPServer(**defaults)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


class TestInstallServerPyPI:
    """PyPI branch uses uvx instead of venv + pip."""

    def test_pypi_sets_uvx_command(self, data_dir: Path):
        registry = MagicMock()
        manager = FastMCPServerManager(registry, manage_processes=False)

        with get_db() as db:
            record = _make_record(
                db,
                install_method="package",
                package_info={"identifier": "mcp-server-fetch", "registryType": "pypi"},
                version="0.6.2",
            )
            server_id = record.id

        manager._install_server(server_id)

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            assert record.startup_command == "uvx"
            assert record.command_args == ["mcp-server-fetch==0.6.2"]
            assert record.status == "stopped"
            assert record.venv_path is None

            # Cleanup
            db.delete(record)
            db.commit()

    def test_pypi_no_version_omits_pinning(self, data_dir: Path):
        registry = MagicMock()
        manager = FastMCPServerManager(registry, manage_processes=False)

        with get_db() as db:
            record = _make_record(
                db,
                install_method="package",
                package_info={"identifier": "mcp-server-time", "registryType": "pypi"},
                version=None,
            )
            server_id = record.id

        manager._install_server(server_id)

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            assert record.startup_command == "uvx"
            assert record.command_args == ["mcp-server-time"]
            assert record.status == "stopped"

            db.delete(record)
            db.commit()


class TestInstallServerRepo:
    """Repo branch clones and sets stopped status without auto-detecting entrypoint."""

    @patch("app.external.fastmcp_manager._ensure_repo")
    def test_repo_no_entrypoint_sets_stopped(self, mock_ensure, data_dir: Path):
        repo_path = data_dir / "external" / "servers" / "test-repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        mock_ensure.return_value = repo_path

        registry = MagicMock()
        manager = FastMCPServerManager(registry, manage_processes=False)

        with get_db() as db:
            record = _make_record(
                db,
                namespace="test-repo",
                install_method="repo",
                repo_url="https://github.com/example/repo.git",
                entrypoint=None,
            )
            server_id = record.id

        manager._install_server(server_id)

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            assert record.status == "stopped"
            assert record.last_error is not None
            assert "Configure startup command" in record.last_error
            assert record.startup_command is None

            db.delete(record)
            db.commit()

    @patch("app.external.fastmcp_manager._install_repo_deps")
    @patch("app.external.fastmcp_manager._ensure_repo")
    def test_repo_with_entrypoint_installs_deps(self, mock_ensure, mock_deps, data_dir: Path):
        ns = f"test_repo_{uuid4().hex[:8]}"
        repo_path = data_dir / "external" / "servers" / ns
        repo_path.mkdir(parents=True, exist_ok=True)
        entrypoint_file = repo_path / "server.py"
        entrypoint_file.write_text("# server")
        mock_ensure.return_value = repo_path

        registry = MagicMock()
        manager = FastMCPServerManager(registry, manage_processes=False)

        with get_db() as db:
            record = _make_record(
                db,
                namespace=ns,
                install_method="repo",
                repo_url="https://github.com/example/repo.git",
                entrypoint="server.py",
            )
            server_id = record.id

        manager._install_server(server_id)

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            assert record.status == "stopped"
            assert record.startup_command == "python"
            assert str(entrypoint_file) in record.command_args
            assert record.last_error is None

            db.delete(record)
            db.commit()


class TestInstallServerNpm:
    """npm branch still uses npx."""

    @patch("app.external.fastmcp_manager.validate_npm_package")
    def test_npm_sets_npx_command(self, mock_validate, data_dir: Path):
        mock_validate.return_value = {"success": True}

        registry = MagicMock()
        manager = FastMCPServerManager(registry, manage_processes=False)

        with get_db() as db:
            record = _make_record(
                db,
                install_method="package",
                package_info={"identifier": "@modelcontextprotocol/server-fetch", "registryType": "npm"},
                version="1.0.0",
            )
            server_id = record.id

        manager._install_server(server_id)

        with get_db() as db:
            record = db.get(ExternalFastMCPServer, server_id)
            assert record.startup_command == "npx"
            assert record.command_args == ["-y", "@modelcontextprotocol/server-fetch@1.0.0"]
            assert record.status == "stopped"

            db.delete(record)
            db.commit()


class TestSafeDeleteHelpers:
    def test_safe_rmtree_under_deletes_child_dir(self, tmp_path: Path):
        base = tmp_path / "external" / "servers"
        child = base / "ns1"
        child.mkdir(parents=True)
        (child / "config.yaml").write_text("key: value\n")

        _safe_rmtree_under(child, base)
        assert not child.exists()

    def test_safe_rmtree_under_rejects_base_dir(self, tmp_path: Path):
        base = tmp_path / "external" / "servers"
        base.mkdir(parents=True)

        with pytest.raises(RuntimeError, match="outside base directory"):
            _safe_rmtree_under(base, base)
