"""Create FastMCP external server tables

Revision ID: 20260203_01
Revises: 
Create Date: 2026-02-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260203_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_registry_cache",
        sa.Column("server_name", sa.String(length=255), primary_key=True),
        sa.Column("latest_version", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )

    op.create_table(
        "external_fastmcp_servers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("server_name", sa.String(length=255), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False, unique=True),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("install_method", sa.String(length=32), nullable=False),
        sa.Column("package_info", sa.JSON(), nullable=True),
        sa.Column("repo_url", sa.Text(), nullable=True),
        sa.Column("entrypoint", sa.Text(), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("venv_path", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="stopped"),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("auto_start", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("external_fastmcp_servers")
    op.drop_table("external_registry_cache")
