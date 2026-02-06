"""Database setup and helpers (SQLite default, Postgres-ready)."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import sqlalchemy
from sqlalchemy import create_engine, Engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import Base

logger = logging.getLogger(__name__)


DEFAULT_DATA_DIR = os.path.join(os.getcwd(), "tooldock_data")
DEFAULT_DB_URL = f"sqlite:///{os.path.join(DEFAULT_DATA_DIR, 'db', 'tooldock.db')}"

# Lazy-initialized globals
_ENGINE: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL", "").strip()
    if db_url:
        return db_url

    data_dir = os.getenv("DATA_DIR", DEFAULT_DATA_DIR)
    return f"sqlite:///{os.path.join(data_dir, 'db', 'tooldock.db')}"


def _create_engine() -> Engine:
    db_url = get_database_url()
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        # Ensure directory exists for SQLite
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(db_url, connect_args=connect_args, future=True)


def get_engine() -> Engine:
    """Get or create the database engine (lazy initialization)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _create_engine()
    return _ENGINE


def get_session_factory() -> sessionmaker:
    """Get or create the session factory (lazy initialization)."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine(), future=True
        )
    return _SessionLocal


def reset_engine() -> None:
    """Reset engine and session factory (useful for tests)."""
    global _ENGINE, _SessionLocal
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SessionLocal = None


def _migrate_columns(engine: Engine) -> None:
    """Add columns that may be missing from older databases.

    SQLite-safe: ALTER TABLE ADD COLUMN is a no-op if the column
    already exists (we check via inspector first).
    """
    inspector = sqlalchemy.inspect(engine)
    tables = inspector.get_table_names()
    if "external_fastmcp_servers" not in tables:
        return

    existing = {c["name"] for c in inspector.get_columns("external_fastmcp_servers")}
    migrations = {
        "startup_command": "ALTER TABLE external_fastmcp_servers ADD COLUMN startup_command TEXT",
        "command_args": "ALTER TABLE external_fastmcp_servers ADD COLUMN command_args JSON",
        "env_vars": "ALTER TABLE external_fastmcp_servers ADD COLUMN env_vars JSON",
        "config_yaml": "ALTER TABLE external_fastmcp_servers ADD COLUMN config_yaml TEXT",
        "transport_type": "ALTER TABLE external_fastmcp_servers ADD COLUMN transport_type VARCHAR(16) DEFAULT 'stdio' NOT NULL",
        "server_url": "ALTER TABLE external_fastmcp_servers ADD COLUMN server_url TEXT",
        "package_type": "ALTER TABLE external_fastmcp_servers ADD COLUMN package_type VARCHAR(32)",
        "source_url": "ALTER TABLE external_fastmcp_servers ADD COLUMN source_url TEXT",
    }
    with engine.begin() as conn:
        for col_name, ddl in migrations.items():
            if col_name not in existing:
                conn.execute(text(ddl))
                logger.info(f"Migrated column: external_fastmcp_servers.{col_name}")


def init_db() -> None:
    """Initialize database tables if they don't exist.

    Alembic migrations are the long-term path; this ensures
    a usable database for fresh installs.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _migrate_columns(engine)


@contextmanager
def get_db():
    """Provide a transactional scope around a series of operations."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


# Backwards compatibility: Some code may import ENGINE or SessionLocal directly
# These are now functions that must be called
ENGINE = get_engine  # type: ignore[assignment]
SessionLocal = get_session_factory  # type: ignore[assignment]
