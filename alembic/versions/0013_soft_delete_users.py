"""Add soft deletion for user accounts.

Revision ID: 0013_soft_delete_users
Revises: 0012_ai_workbench
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_soft_delete_users"
down_revision: str | None = "0012_ai_workbench"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_exists(bind: sa.Connection, index_name: str) -> bool:
    if bind.dialect.name == "sqlite":
        return (
            bind.execute(
                sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :name"),
                {"name": index_name},
            ).first()
            is not None
        )
    return any(index["name"] == index_name for index in sa.inspect(bind).get_indexes("users"))


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "deleted_at" not in columns:
        op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    if not _index_exists(bind, "ix_users_deleted_at"):
        op.create_index("ix_users_deleted_at", "users", ["deleted_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind, "ix_users_deleted_at"):
        op.drop_index("ix_users_deleted_at", table_name="users")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "deleted_at" in columns:
        op.drop_column("users", "deleted_at")
