"""Remove settlement and reconciliation modules.

Revision ID: 0003_remove_settlement_recon
Revises: 0002_remove_imports_rules
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_remove_settlement_recon"
down_revision: str | None = "0002_remove_imports_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("reconciliation_items")
    op.drop_table("reconciliation_sessions")
    op.drop_table("settlement_items")
    op.drop_table("settlements")
    op.execute(
        sa.text(
            "UPDATE accounts SET name = '待核对差额', subtype = 'pending_difference' "
            "WHERE code = '1290' AND subtype = 'settlement_difference'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM idempotency_records "
            "WHERE operation LIKE 'settlements.%' OR operation LIKE 'reconciliations.%'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE accounts SET name = '待核对结算差额', "
            "subtype = 'settlement_difference' "
            "WHERE code = '1290' AND subtype = 'pending_difference'"
        )
    )
    op.create_table(
        "reconciliation_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("payment_account_id", sa.String(length=36), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("opening_balance_e8", sa.Integer(), nullable=False),
        sa.Column("statement_ending_balance_e8", sa.Integer(), nullable=False),
        sa.Column("book_ending_balance_e8", sa.Integer(), nullable=False),
        sa.Column("difference_e8", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("closed_by_id", sa.String(length=36), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["payment_account_id"], ["payment_accounts.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "settlements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=240), nullable=True),
        sa.Column("accounting_date", sa.Date(), nullable=False),
        sa.Column("amount_cny_e8", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("bank_reference", sa.String(length=240), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["record_id"], ["business_records.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("record_id"),
        sa.UniqueConstraint(
            "workspace_id", "channel", "external_id", name="uq_settlement_external"
        ),
    )
    op.create_table(
        "reconciliation_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reconciliation_id", sa.String(length=36), nullable=False),
        sa.Column("journal_line_id", sa.String(length=36), nullable=False),
        sa.Column("matched_amount_e8", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["journal_line_id"], ["journal_lines.id"]),
        sa.ForeignKeyConstraint(["reconciliation_id"], ["reconciliation_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reconciliation_id", "journal_line_id", name="uq_reconciliation_line"),
    )
    op.create_table(
        "settlement_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("settlement_id", sa.String(length=36), nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("amount_cny_e8", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["record_id"], ["business_records.id"]),
        sa.ForeignKeyConstraint(["settlement_id"], ["settlements.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settlement_id", "record_id", name="uq_settlement_record"),
    )
