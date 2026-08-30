"""Remove unused categories created by the old startup seed.

Revision ID: 0015_remove_default_categories
Revises: 0014_backup_storage
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_remove_default_categories"
down_revision: str | None = "0014_backup_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_CATEGORY_SEEDS = (
    ("主营业务收入", "income", "5001"),
    ("其他业务收入", "income", "5051"),
    ("上游采购", "expense", "5401"),
    ("账号采购", "expense", "5401"),
    ("云服务", "expense", "5602"),
    ("软件订阅", "expense", "5602"),
    ("交易手续费", "expense", "5603"),
    ("其他支出", "expense", "5602"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for name, kind, account_code in OLD_CATEGORY_SEEDS:
        bind.execute(
            sa.text(
                """
                DELETE FROM categories
                WHERE name = :name
                  AND kind = :kind
                  AND EXISTS (
                    SELECT 1
                    FROM accounts
                    WHERE accounts.id = categories.account_id
                      AND accounts.code = :account_code
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM audit_events
                    WHERE audit_events.entity_type = 'category'
                      AND audit_events.entity_id = categories.id
                      AND audit_events.action = 'category.create'
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM business_records
                    WHERE business_records.category_id = categories.id
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM counterparties
                    WHERE counterparties.expense_category_id = categories.id
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM categories AS children
                    WHERE children.parent_id = categories.id
                  )
                """
            ),
            {"name": name, "kind": kind, "account_code": account_code},
        )


def downgrade() -> None:
    # Removed seed rows cannot be distinguished well enough to recreate safely.
    pass
