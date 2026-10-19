"""previews, mcp_calls, rate_counters.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = postgresql.TIMESTAMP(timezone=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "previews",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id", name="fk_previews_book_id_books"), nullable=False),
        sa.Column("actor_key", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("preview_key", sa.Text(), nullable=False),
        sa.Column("args", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=False),
        sa.Column("depends", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", TZ, nullable=False),
        sa.Column("committed_at", TZ, nullable=True),
        sa.Column("change_set_id", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('pending','committed','stale','expired')", name="ck_previews_status"),
        sa.PrimaryKeyConstraint("id", name="pk_previews"),
    )
    op.create_index("ix_previews_book_created", "previews", ["book_id", "created_at"])
    op.create_table(
        "mcp_calls",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id", name="fk_mcp_calls_book_id_books"), nullable=True),
        sa.Column("token_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("client", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=True),
        sa.Column("args", JSONB(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("result_code", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("change_set_id", sa.Text(), nullable=True),
        sa.Column("preview_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_mcp_calls"),
    )
    op.create_index("ix_mcp_calls_book_created", "mcp_calls", ["book_id", "created_at"])
    op.create_index("ix_mcp_calls_token_created", "mcp_calls", ["token_id", "created_at"])
    op.create_table(
        "rate_counters",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("window_start", TZ, nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name="pk_rate_counters"),
    )


def downgrade() -> None:
    op.drop_table("rate_counters")
    op.drop_index("ix_mcp_calls_token_created", table_name="mcp_calls")
    op.drop_index("ix_mcp_calls_book_created", table_name="mcp_calls")
    op.drop_table("mcp_calls")
    op.drop_index("ix_previews_book_created", table_name="previews")
    op.drop_table("previews")
