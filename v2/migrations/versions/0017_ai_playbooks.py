"""Scenario playbooks a book changed or added (the built-in ones ship with the code in ai/playbooks.json).

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_playbooks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("updated_by", sa.Text(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("book_id", "code", name=op.f("uq_ai_playbooks_book_id_code")),
    )


def downgrade() -> None:
    op.drop_table("ai_playbooks")
