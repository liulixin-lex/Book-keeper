"""Add login usernames and record creator lookup index.

Revision ID: 0011_add_usernames
Revises: 0010_link_providers_categories
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_add_usernames"
down_revision: str | None = "0010_link_providers_categories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_exists(bind: sa.Connection, table_name: str, index_name: str) -> bool:
    if bind.dialect.name == "sqlite":
        return (
            bind.execute(
                sa.text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = :table_name AND name = :index_name"
                ),
                {"table_name": table_name, "index_name": index_name},
            ).first()
            is not None
        )
    return any(
        index["name"] == index_name
        for index in sa.inspect(bind).get_indexes(table_name)
    )


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "username" not in columns:
        op.add_column("users", sa.Column("username", sa.String(length=120), nullable=True))
        bind.execute(sa.text("UPDATE users SET username = trim(display_name)"))
        bind.execute(
            sa.text(
                """
                UPDATE users
                SET username = username || '-' || substr(id, 1, 8)
                WHERE EXISTS (
                  SELECT 1
                  FROM users AS earlier
                  WHERE lower(earlier.username) = lower(users.username)
                    AND earlier.id < users.id
                )
                """
            )
        )
    if not _index_exists(bind, "users", "uq_users_username_lower"):
        op.create_index(
            "uq_users_username_lower",
            "users",
            [sa.text("lower(username)")],
            unique=True,
        )
    if not _index_exists(
        bind, "business_records", "ix_business_records_created_by_user_id"
    ):
        op.create_index(
            "ix_business_records_created_by_user_id",
            "business_records",
            ["created_by_user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind, "business_records", "ix_business_records_created_by_user_id"):
        op.drop_index("ix_business_records_created_by_user_id", table_name="business_records")
    if _index_exists(bind, "users", "uq_users_username_lower"):
        op.drop_index("uq_users_username_lower", table_name="users")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "username" in columns:
        op.drop_column("users", "username")
