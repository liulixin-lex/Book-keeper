"""AI providers the owner configures in 设置 → AI (keys sealed with BK_MASTER_KEY), and per-call usage.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(none_as_null=True)


def upgrade() -> None:
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text()),
        sa.Column("api_key_sealed", sa.Text()),
        sa.Column("key_last4", sa.Text()),
        sa.Column("models", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("default_model", sa.Text()),
        sa.Column("timeout_seconds", sa.Integer(), server_default="120", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("capabilities", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("options", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("prices", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.Text()),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("book_id", "name", name=op.f("uq_ai_providers_book_id_name")),
        sa.CheckConstraint("kind IN ('anthropic','openai_compatible')", name=op.f("ck_ai_providers_kind")),
        sa.CheckConstraint("timeout_seconds BETWEEN 5 AND 600", name=op.f("ck_ai_providers_timeout")),
    )
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("provider_id", sa.Text(), sa.ForeignKey("ai_providers.id", ondelete="SET NULL")),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost", sa.Numeric(14, 6)),
        sa.Column("ok", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("ref", sa.Text()),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ai_usage_book_created", "ai_usage", ["book_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_book_created", table_name="ai_usage")
    op.drop_table("ai_usage")
    op.drop_table("ai_providers")
