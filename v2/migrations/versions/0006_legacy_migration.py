"""legacy_map, legacy_archive.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legacy_map",
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("legacy_table", sa.Text(), nullable=False),
        sa.Column("legacy_id", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name="fk_legacy_map_book_id_books"),
        sa.PrimaryKeyConstraint("book_id", "legacy_table", "legacy_id", name="pk_legacy_map"),
    )
    op.create_index("ix_legacy_map_entity", "legacy_map", ["entity_type", "entity_id"])
    op.create_table(
        "legacy_archive",
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("legacy_table", sa.Text(), nullable=False),
        sa.Column("legacy_id", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name="fk_legacy_archive_book_id_books"),
        sa.PrimaryKeyConstraint("book_id", "legacy_table", "legacy_id", name="pk_legacy_archive"),
    )


def downgrade() -> None:
    op.drop_table("legacy_archive")
    op.drop_index("ix_legacy_map_entity", table_name="legacy_map")
    op.drop_table("legacy_map")
