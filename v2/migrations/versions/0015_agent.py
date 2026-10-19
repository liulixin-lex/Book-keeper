"""The in-app AI assistant: runs, their step-by-step transcript, and the book's AI workspace files.

Writes made by the assistant carry the channel ``agent`` (audit, change sets, transactions).

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(none_as_null=True)
TIERS = "tier IN ('user_read','user_write','admin_read','admin_write')"
AUDIT_NEW = "channel IN ('ui','api','mcp','agent','import','worker','cli','migration','system')"
TXN_NEW = "created_channel IN ('ui','api','mcp','agent','import','system','migration','cli')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_audit_events_channel"), "audit_events", type_="check")
    op.create_check_constraint(op.f("ck_audit_events_channel"), "audit_events", AUDIT_NEW)
    op.drop_constraint(op.f("ck_transactions_created_channel"), "transactions", type_="check")
    op.create_check_constraint(op.f("ck_transactions_created_channel"), "transactions", TXN_NEW)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), server_default="general", nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("playbook", sa.Text()),
        sa.Column("file_ids", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("change_set_id", sa.Text(), sa.ForeignKey("change_sets.id")),
        sa.Column("question", sa.Text()),
        sa.Column("result", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cost", sa.Numeric(14, 6)),
        sa.Column("model", sa.Text()),
        sa.Column("finished_at", TZ),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(TIERS, name=op.f("ck_agent_runs_tier")),
        sa.CheckConstraint("stage IN ('general','recognition')", name=op.f("ck_agent_runs_stage")),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting','done','failed','cancelled')", name=op.f("ck_agent_runs_status")
        ),
    )
    op.create_index("ix_agent_runs_book_created", "agent_runs", ["book_id", "created_at"])
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("tool", sa.Text()),
        sa.Column("call_id", sa.Text()),
        sa.Column("arguments", JSONB),
        sa.Column("result", JSONB),
        sa.Column("ok", sa.Boolean()),
        sa.Column("native", JSONB),
        sa.Column("native_kind", sa.Text()),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "seq", name=op.f("uq_agent_steps_run_id_seq")),
        sa.CheckConstraint(
            "kind IN ('instruction','assistant','tool','answer','note')", name=op.f("ck_agent_steps_kind")
        ),
    )
    op.create_table(
        "agent_files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("book_id", sa.Text(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.Text(), sa.ForeignKey("users.id")),
        sa.Column("created_at", TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TZ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.UniqueConstraint("book_id", "path", name=op.f("uq_agent_files_book_id_path")),
    )


def downgrade() -> None:
    op.drop_table("agent_files")
    op.drop_table("agent_steps")
    op.drop_index("ix_agent_runs_book_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    # The channel checks stay wide: audit events and entries are append-only, so rows written with the channel
    # ``agent`` cannot be rewritten, and the wider check is harmless to the code before this revision.
