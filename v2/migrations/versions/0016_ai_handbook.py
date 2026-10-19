"""识别规则手册: versioned, editable recognition rules per book (no site lists or rates: those stay the book's data).

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_handbooks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Numeric(3, 2), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("created_by", sa.Text(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("book_id", "version", name=op.f("uq_ai_handbooks_book_id_version")),
        sa.CheckConstraint("threshold BETWEEN 0.5 AND 1", name=op.f("ck_ai_handbooks_threshold")),
    )


def downgrade() -> None:
    op.drop_table("ai_handbooks")
