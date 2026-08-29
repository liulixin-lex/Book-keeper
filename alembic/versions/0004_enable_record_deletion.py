"""Enable application-managed deletion of posted records.

Revision ID: 0004_enable_record_deletion
Revises: 0003_remove_settlement_recon
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_enable_record_deletion"
down_revision: str | None = "0003_remove_settlement_recon"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS posted_journal_no_delete"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS posted_line_no_delete"))
    op.execute(
        sa.text(
            "UPDATE accounts SET name = '资金清算账户' "
            "WHERE code = '1100' AND name = '渠道清算账户'"
        )
    )
    op.execute(
        sa.text("UPDATE accounts SET name = '手续费' WHERE code = '5400' AND name = '渠道手续费'")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE accounts SET name = '渠道清算账户' "
            "WHERE code = '1100' AND name = '资金清算账户'"
        )
    )
    op.execute(
        sa.text("UPDATE accounts SET name = '渠道手续费' WHERE code = '5400' AND name = '手续费'")
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER posted_journal_no_delete
            BEFORE DELETE ON journal_entries
            WHEN OLD.status = 'posted'
            BEGIN
              SELECT RAISE(ABORT, 'posted journal cannot be deleted');
            END
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER posted_line_no_delete
            BEFORE DELETE ON journal_lines
            WHEN (SELECT status FROM journal_entries WHERE id = OLD.entry_id) = 'posted'
            BEGIN
              SELECT RAISE(ABORT, 'posted journal lines are immutable');
            END
            """
        )
    )
