"""Database package for ToolDock."""

from app.db.database import (  # noqa: F401
    get_db,
    get_engine,
    get_session_factory,
    init_db,
    reset_engine,
)

# Backwards compatibility alias
SessionLocal = get_session_factory
