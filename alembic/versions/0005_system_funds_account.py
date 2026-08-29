"""Use a system-owned funds account for new bookkeeping records.

Revision ID: 0005_system_funds_account
Revises: 0004_enable_record_deletion
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_system_funds_account"
down_revision: str | None = "0004_enable_record_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE accounts SET name = '系统资金账户' "
            "WHERE code = '1000' AND name = '未指定支付账户'"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE accounts SET name = '未指定支付账户' "
            "WHERE code = '1000' AND name = '系统资金账户'"
        )
    )
