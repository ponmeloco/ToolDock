"""Add FastMCP config and provenance columns

Revision ID: 20260206_02
Revises: 20260203_01
Create Date: 2026-02-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260206_02"
down_revision = "20260203_01"
branch_labels = None
depends_on = None


def _get_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _get_columns("external_fastmcp_servers")

    with op.batch_alter_table("external_fastmcp_servers") as batch:
        if "startup_command" not in existing:
            batch.add_column(sa.Column("startup_command", sa.Text(), nullable=True))
        if "command_args" not in existing:
            batch.add_column(sa.Column("command_args", sa.JSON(), nullable=True))
        if "env_vars" not in existing:
            batch.add_column(sa.Column("env_vars", sa.JSON(), nullable=True))
        if "config_yaml" not in existing:
            batch.add_column(sa.Column("config_yaml", sa.Text(), nullable=True))
        if "transport_type" not in existing:
            batch.add_column(
                sa.Column(
                    "transport_type",
                    sa.String(length=16),
                    nullable=False,
                    server_default=sa.text("'stdio'"),
                )
            )
        if "server_url" not in existing:
            batch.add_column(sa.Column("server_url", sa.Text(), nullable=True))
        if "package_type" not in existing:
            batch.add_column(sa.Column("package_type", sa.String(length=32), nullable=True))
        if "source_url" not in existing:
            batch.add_column(sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    existing = _get_columns("external_fastmcp_servers")

    with op.batch_alter_table("external_fastmcp_servers") as batch:
        if "source_url" in existing:
            batch.drop_column("source_url")
        if "package_type" in existing:
            batch.drop_column("package_type")
        if "server_url" in existing:
            batch.drop_column("server_url")
        if "transport_type" in existing:
            batch.drop_column("transport_type")
        if "config_yaml" in existing:
            batch.drop_column("config_yaml")
        if "env_vars" in existing:
            batch.drop_column("env_vars")
        if "command_args" in existing:
            batch.drop_column("command_args")
        if "startup_command" in existing:
            batch.drop_column("startup_command")
