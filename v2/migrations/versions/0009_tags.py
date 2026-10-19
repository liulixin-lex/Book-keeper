"""Tags on transactions.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_tags_book_id_books")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("book_id", "name", name=op.f("uq_tags_book_id")),
    )
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("tag_id", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], name=op.f("fk_transaction_tags_tag_id_tags")),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], name=op.f("fk_transaction_tags_transaction_id_transactions")
        ),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id", name=op.f("pk_transaction_tags")),
    )
    op.create_index("ix_transaction_tags_tag", "transaction_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transaction_tags_tag", table_name="transaction_tags")
    op.drop_table("transaction_tags")
    op.drop_table("tags")
