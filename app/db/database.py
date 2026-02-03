"""Database setup and helpers (SQLite default, Postgres-ready)."""

from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base


DEFAULT_DB_URL = "sqlite:////data/db/tooldock.db"


def get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    data_dir = os.getenv("DATA_DIR")
    if data_dir:
        return f"sqlite:///{os.path.join(data_dir, 'db', 'tooldock.db')}"

    return DEFAULT_DB_URL


def _create_engine():
    db_url = get_database_url()
    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(db_url, connect_args=connect_args, future=True)


ENGINE = _create_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ENGINE, future=True)


def init_db() -> None:
    """Initialize database tables if they don't exist.

    Alembic migrations are the long-term path; this ensures
    a usable database for fresh installs.
    """
    Base.metadata.create_all(bind=ENGINE)


@contextmanager
def get_db():
    """Provide a transactional scope around a series of operations."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
