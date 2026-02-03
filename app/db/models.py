"""SQLAlchemy models for ToolDock."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ExternalRegistryCache(Base):
    __tablename__ = "external_registry_cache"

    server_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    latest_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExternalFastMCPServer(Base):
    __tablename__ = "external_fastmcp_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_name: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    install_method: Mapped[str] = mapped_column(String(32), nullable=False)
    package_info: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    repo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entrypoint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    venv_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="stopped")
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    auto_start: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
