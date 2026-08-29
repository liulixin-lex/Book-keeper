"""Standardize the chart of accounts and master-data defaults.

Revision ID: 0006_simplify_master_data
Revises: 0005_system_funds_account
Create Date: 2026-08-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_simplify_master_data"
down_revision: str | None = "0005_system_funds_account"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


ACCOUNT_GROUPS = (
    ("1002", "银行存款", "system_funds", ("1000",)),
    ("1012", "其他货币资金", "clearing", ("1100",)),
    ("1221", "其他应收款", "pending_difference", ("1290",)),
    ("2202", "应付账款", "payable", ("2000",)),
    ("3104", "利润分配", "opening_balance", ("3000",)),
    ("5001", "主营业务收入", "operating_revenue", ("4000",)),
    ("5051", "其他业务收入", "other_revenue", ("4100",)),
    ("5401", "主营业务成本", "operating_cost", ("5000", "5100")),
    ("5602", "管理费用", "administrative_expense", ("5200", "5300", "5500")),
    ("5603", "财务费用", "processing_fee", ("5400",)),
)

CATEGORY_RENAMES = (
    ("收入", "主营业务收入"),
    ("链动收入", "其他业务收入"),
    ("上游充值", "上游采购"),
    ("账号购买", "账号采购"),
    ("账号订阅", "软件订阅"),
    ("其他费用", "其他支出"),
)


def _rewire_account(bind: sa.Connection, source_id: str, target_id: str) -> None:
    for table_name, column_name in (
        ("categories", "account_id"),
        ("payment_accounts", "ledger_account_id"),
        ("journal_lines", "account_id"),
    ):
        bind.execute(
            sa.text(
                f"UPDATE {table_name} SET {column_name} = :target "
                f"WHERE {column_name} = :source"
            ),
            {"target": target_id, "source": source_id},
        )


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(sa.text("DROP TRIGGER IF EXISTS posted_line_no_update"))
    workspace_ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM workspaces"))]
    for workspace_id in workspace_ids:
        for target_code, name, subtype, old_codes in ACCOUNT_GROUPS:
            target = bind.execute(
                sa.text(
                    "SELECT id FROM accounts WHERE workspace_id = :workspace_id "
                    "AND code = :code LIMIT 1"
                ),
                {"workspace_id": workspace_id, "code": target_code},
            ).first()
            old_rows = list(
                bind.execute(
                    sa.text(
                        "SELECT id, code FROM accounts WHERE workspace_id = :workspace_id "
                        "AND code IN :codes ORDER BY code"
                    ).bindparams(sa.bindparam("codes", expanding=True)),
                    {"workspace_id": workspace_id, "codes": old_codes},
                )
            )
            if target is None and old_rows:
                target_id = old_rows.pop(0)[0]
                bind.execute(
                    sa.text(
                        "UPDATE accounts SET code = :code, name = :name, subtype = :subtype "
                        "WHERE id = :account_id"
                    ),
                    {
                        "code": target_code,
                        "name": name,
                        "subtype": subtype,
                        "account_id": target_id,
                    },
                )
            elif target is not None:
                target_id = target[0]
                bind.execute(
                    sa.text("UPDATE accounts SET name = :name, subtype = :subtype WHERE id = :id"),
                    {"name": name, "subtype": subtype, "id": target_id},
                )
            else:
                continue

            for source_id, _source_code in old_rows:
                if source_id == target_id:
                    continue
                _rewire_account(bind, source_id, target_id)
                bind.execute(sa.text("DELETE FROM accounts WHERE id = :id"), {"id": source_id})

        for old_name, new_name in CATEGORY_RENAMES:
            new_exists = bind.execute(
                sa.text(
                    "SELECT id FROM categories WHERE workspace_id = :workspace_id "
                    "AND name = :name LIMIT 1"
                ),
                {"workspace_id": workspace_id, "name": new_name},
            ).first()
            if new_exists is None:
                bind.execute(
                    sa.text(
                        "UPDATE categories SET name = :new_name WHERE workspace_id = :workspace_id "
                        "AND name = :old_name"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "old_name": old_name,
                        "new_name": new_name,
                    },
                )
            else:
                bind.execute(
                    sa.text(
                        "UPDATE categories SET is_active = 0 WHERE workspace_id = :workspace_id "
                        "AND name = :old_name"
                    ),
                    {"workspace_id": workspace_id, "old_name": old_name},
                )

        bind.execute(
            sa.text(
                "UPDATE categories SET is_active = 0 WHERE workspace_id = :workspace_id "
                "AND name IN ('Stripe收入', 'xorpay收入')"
            ),
            {"workspace_id": workspace_id},
        )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER posted_line_no_update
            BEFORE UPDATE ON journal_lines
            WHEN (SELECT status FROM journal_entries WHERE id = OLD.entry_id) = 'posted'
              OR (SELECT status FROM journal_entries WHERE id = NEW.entry_id) = 'posted'
            BEGIN
              SELECT RAISE(ABORT, 'posted journal lines are immutable');
            END
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    reverse_codes = {
        "1002": ("1000", "系统资金账户", "cash"),
        "1012": ("1100", "资金清算账户", "clearing"),
        "1221": ("1290", "待核对差额", "pending_difference"),
        "2202": ("2000", "应付账款", "payable"),
        "3104": ("3000", "期初及迁移平衡", "opening_balance"),
        "5001": ("4000", "运营收入", "operating_revenue"),
        "5051": ("4100", "链动收入", "liandong_revenue"),
        "5401": ("5000", "上游充值成本", "upstream_cost"),
        "5602": ("5200", "云服务费用", "cloud_service"),
        "5603": ("5400", "手续费", "processing_fee"),
    }
    for new_code, (old_code, name, subtype) in reverse_codes.items():
        bind.execute(
            sa.text(
                "UPDATE accounts SET code = :old_code, name = :name, subtype = :subtype "
                "WHERE code = :new_code"
            ),
            {"old_code": old_code, "name": name, "subtype": subtype, "new_code": new_code},
        )
    for old_name, new_name in CATEGORY_RENAMES:
        bind.execute(
            sa.text("UPDATE categories SET name = :old_name WHERE name = :new_name"),
            {"old_name": old_name, "new_name": new_name},
        )
