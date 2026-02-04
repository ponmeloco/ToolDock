"""Database setup and helpers (SQLite default, Postgres-ready)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import Base


DEFAULT_DB_URL = "sqlite:////data/db/tooldock.db"

# Lazy-initialized globals
_ENGINE: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    data_dir = os.getenv("DATA_DIR")
    if data_dir:
        return f"sqlite:///{os.path.join(data_dir, 'db', 'tooldock.db')}"

    return DEFAULT_DB_URL


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


def init_db() -> None:
    """Initialize database tables if they don't exist.

    Alembic migrations are the long-term path; this ensures
    a usable database for fresh installs.
    """
    Base.metadata.create_all(bind=get_engine())


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
