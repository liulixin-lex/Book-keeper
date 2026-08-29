"""Normalize historical cash records to the simplified bookkeeping model.

Revision ID: 0008_normalize_cash_records
Revises: 0007_normalize_counterparty_roles
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_normalize_cash_records"
down_revision: str | None = "0007_normalize_counterparty_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID_SQL = """
lower(
  hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
  substr(hex(randomblob(2)), 2) || '-' ||
  substr('89ab', abs(random()) % 4 + 1, 1) ||
  substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))
)
"""

REFUND_FILTER = """
br.record_type = 'adjustment'
AND (
  json_extract(br.metadata_json, '$.legacy_status') = '退款'
  OR EXISTS (
    SELECT 1 FROM money_components refund_cash
    WHERE refund_cash.record_id = br.id
      AND refund_cash.role = 'cash'
      AND refund_cash.amount_cny_e8 < 0
  )
)
"""


def _install_posted_line_guard() -> None:
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


def _audit(action: str, filter_sql: str, before_type: str, after_type: str) -> None:
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO audit_events (
              id, workspace_id, actor_type, action, entity_type, entity_id,
              before_json, after_json
            )
            SELECT
              {UUID_SQL}, br.workspace_id, 'system', :action,
              'business_record', br.id,
              json_object('record_type', :before_type),
              json_object(
                'record_type', :after_type,
                'migration', '0008_normalize_cash_records'
              )
            FROM business_records br
            WHERE {filter_sql}
              AND NOT EXISTS (
                SELECT 1 FROM audit_events ae
                WHERE ae.entity_id = br.id AND ae.action = :action
              )
            """
        ),
        {
            "action": action,
            "before_type": before_type,
            "after_type": after_type,
        },
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("SAVEPOINT normalize_cash_records")
    try:
        op.execute(sa.text("DROP TRIGGER IF EXISTS posted_line_no_update"))
        # Ensure the standard category needed by historical expense refunds exists.
        op.execute(
            sa.text(
                f"""
                INSERT INTO categories (id, workspace_id, account_id, name, kind, is_active)
                SELECT
                  {UUID_SQL}, w.id, a.id, '其他业务收入', 'income', 1
                FROM workspaces w
                JOIN accounts a ON a.workspace_id = w.id AND a.code = '5051'
                WHERE NOT EXISTS (
                  SELECT 1 FROM categories c
                  WHERE c.workspace_id = w.id AND c.name = '其他业务收入'
                )
                """
            )
        )

        # Historical Stripe/Xorpay income was posted to clearing and had no cash component.
        _audit(
            "migration.cash_income.normalize",
            """
            br.record_type = 'income'
            AND NOT EXISTS (
              SELECT 1 FROM money_components cash
              WHERE cash.record_id = br.id AND cash.role = 'cash'
            )
            """,
            "income_without_cash",
            "income",
        )
        op.execute(
            sa.text(
                f"""
                INSERT INTO money_components (
                  id, record_id, role, sequence, currency, amount_e8,
                  amount_cny_e8, fx_rate_id, is_derived, raw_amount_text
                )
                SELECT
                  {UUID_SQL}, net.record_id, 'cash', 0, net.currency,
                  net.amount_e8, net.amount_cny_e8, net.fx_rate_id, 1,
                  net.raw_amount_text
                FROM money_components net
                JOIN business_records br ON br.id = net.record_id
                WHERE br.record_type = 'income'
                  AND net.role = 'net'
                  AND NOT EXISTS (
                    SELECT 1 FROM money_components cash
                    WHERE cash.record_id = net.record_id AND cash.role = 'cash'
                  )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE business_records
                SET metadata_json = json_set(
                  metadata_json,
                  '$.normalization_migration', '0008_normalize_cash_records',
                  '$.cash_state', 'received'
                )
                WHERE record_type = 'income'
                  AND EXISTS (
                    SELECT 1 FROM journal_entries je
                    JOIN journal_lines jl ON jl.entry_id = je.id
                    JOIN accounts a ON a.id = jl.account_id
                    WHERE je.record_id = business_records.id
                      AND a.subtype = 'clearing'
                  )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE journal_lines
                SET account_id = (
                      SELECT target.id
                      FROM journal_entries entry
                      JOIN accounts target ON target.workspace_id = entry.workspace_id
                      WHERE entry.id = journal_lines.entry_id AND target.code = '1002'
                    ),
                    description = '收入净额'
                WHERE account_id IN (SELECT id FROM accounts WHERE subtype = 'clearing')
                  AND entry_id IN (
                    SELECT je.id
                    FROM journal_entries je
                    JOIN business_records br ON br.id = je.record_id
                    WHERE br.record_type = 'income'
                  )
                """
            )
        )

        # A legacy cloud bill recorded CNY 452.80 of cost but only CNY 392.80 was paid.
        difference_filter = """
        br.record_type = 'expense'
        AND br.description = 'TDSQL-C MySQL版'
        AND EXISTS (
          SELECT 1 FROM money_components adjustment
          WHERE adjustment.record_id = br.id
            AND adjustment.role = 'adjustment'
            AND adjustment.amount_cny_e8 = 6000000000
        )
        AND EXISTS (
          SELECT 1 FROM money_components cash
          WHERE cash.record_id = br.id
            AND cash.role = 'cash'
            AND cash.amount_cny_e8 = 39280000000
        )
        """
        _audit(
            "migration.cash_expense.normalize",
            difference_filter,
            "expense_with_pending_difference",
            "expense",
        )
        op.execute(
            sa.text(
                f"""
                UPDATE money_components
                SET amount_e8 = 39280000000,
                    amount_cny_e8 = 39280000000,
                    raw_amount_text = '392.8'
                WHERE role = 'cost'
                  AND record_id IN (
                    SELECT br.id FROM business_records br WHERE {difference_filter}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE journal_lines
                SET debit_cny_e8 = 39280000000,
                    original_amount_e8 = 39280000000
                WHERE debit_cny_e8 = 45280000000
                  AND entry_id IN (
                    SELECT br.posted_entry_id
                    FROM business_records br
                    WHERE {difference_filter}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                DELETE FROM journal_lines
                WHERE account_id IN (
                    SELECT id FROM accounts WHERE subtype = 'pending_difference'
                  )
                  AND entry_id IN (
                    SELECT br.posted_entry_id
                    FROM business_records br
                    WHERE {difference_filter}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                DELETE FROM money_components
                WHERE role = 'adjustment'
                  AND record_id IN (
                    SELECT br.id FROM business_records br WHERE {difference_filter}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE business_records
                SET metadata_json = json_set(
                  metadata_json,
                  '$.legacy_operating_amount_cny', '452.8',
                  '$.unreconciled_difference_cny', '0',
                  '$.normalization_migration', '0008_normalize_cash_records',
                  '$.cash_state', 'paid'
                )
                WHERE EXISTS (
                  SELECT 1 FROM audit_events ae
                  WHERE ae.entity_id = business_records.id
                    AND ae.action = 'migration.cash_expense.normalize'
                )
                """
            )
        )

        # The only legacy adjustment is an actual vendor refund. It becomes income.
        _audit(
            "migration.expense_refund.normalize",
            REFUND_FILTER,
            "adjustment",
            "income",
        )
        op.execute(
            sa.text(
                f"""
                UPDATE journal_lines
                SET account_id = (
                      SELECT revenue.id
                      FROM journal_entries entry
                      JOIN accounts revenue
                        ON revenue.workspace_id = entry.workspace_id
                       AND revenue.code = '5051'
                      WHERE entry.id = journal_lines.entry_id
                    ),
                    original_amount_e8 = abs(original_amount_e8),
                    description = '支出退款收入'
                WHERE credit_cny_e8 > 0
                  AND account_id IN (SELECT id FROM accounts WHERE account_type = 'expense')
                  AND entry_id IN (
                    SELECT br.posted_entry_id
                    FROM business_records br
                    WHERE {REFUND_FILTER}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE journal_lines
                SET original_amount_e8 = abs(original_amount_e8),
                    description = '收入净额'
                WHERE debit_cny_e8 > 0
                  AND account_id IN (SELECT id FROM accounts WHERE account_type = 'asset')
                  AND entry_id IN (
                    SELECT br.posted_entry_id
                    FROM business_records br
                    WHERE {REFUND_FILTER}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE money_components
                SET role = 'gross',
                    amount_e8 = abs(amount_e8),
                    amount_cny_e8 = abs(amount_cny_e8),
                    raw_amount_text = ltrim(raw_amount_text, '-')
                WHERE role = 'cost'
                  AND record_id IN (
                    SELECT br.id FROM business_records br WHERE {REFUND_FILTER}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE money_components
                SET amount_e8 = abs(amount_e8),
                    amount_cny_e8 = abs(amount_cny_e8),
                    raw_amount_text = ltrim(raw_amount_text, '-')
                WHERE role = 'cash'
                  AND record_id IN (
                    SELECT br.id FROM business_records br WHERE {REFUND_FILTER}
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                INSERT INTO money_components (
                  id, record_id, role, sequence, currency, amount_e8,
                  amount_cny_e8, fx_rate_id, is_derived, raw_amount_text
                )
                SELECT {UUID_SQL}, gross.record_id, 'fee', 0, gross.currency,
                       0, 0, NULL, 1, '0'
                FROM money_components gross
                JOIN business_records br ON br.id = gross.record_id
                WHERE gross.role = 'gross' AND {REFUND_FILTER}
                  AND NOT EXISTS (
                    SELECT 1 FROM money_components fee
                    WHERE fee.record_id = gross.record_id AND fee.role = 'fee'
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                INSERT INTO money_components (
                  id, record_id, role, sequence, currency, amount_e8,
                  amount_cny_e8, fx_rate_id, is_derived, raw_amount_text
                )
                SELECT {UUID_SQL}, cash.record_id, 'net', 0, cash.currency,
                       cash.amount_e8, cash.amount_cny_e8, cash.fx_rate_id, 1,
                       cash.raw_amount_text
                FROM money_components cash
                JOIN business_records br ON br.id = cash.record_id
                WHERE cash.role = 'cash' AND {REFUND_FILTER}
                  AND NOT EXISTS (
                    SELECT 1 FROM money_components net
                    WHERE net.record_id = cash.record_id AND net.role = 'net'
                  )
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                UPDATE business_records AS br
                SET record_type = 'income',
                    category_id = (
                      SELECT c.id FROM categories c
                      WHERE c.workspace_id = br.workspace_id
                        AND c.name = '其他业务收入'
                    ),
                    metadata_json = json_set(
                      metadata_json,
                      '$.normalized_from_record_type', 'adjustment',
                      '$.normalized_as', 'expense_refund_income',
                      '$.normalization_migration', '0008_normalize_cash_records',
                      '$.cash_state', 'received'
                    )
                WHERE {REFUND_FILTER}
                """
            )
        )

        # Existing top-up and subscription records already have valid expense vouchers.
        _audit(
            "migration.legacy_expense_type.normalize",
            "br.record_type IN ('topup', 'subscription')",
            "legacy_expense_type",
            "expense",
        )
        op.execute(
            sa.text(
                """
                UPDATE business_records
                SET metadata_json = json_set(
                      metadata_json,
                      '$.normalized_from_record_type', record_type,
                      '$.normalization_migration', '0008_normalize_cash_records',
                      '$.cash_state', 'paid'
                    ),
                    record_type = 'expense'
                WHERE record_type IN ('topup', 'subscription')
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE business_records
                SET metadata_json = json_set(
                      metadata_json,
                      '$.normalized_from_record_type', 'adjustment',
                      '$.normalization_migration', '0008_normalize_cash_records'
                    ),
                    record_type = 'expense'
                WHERE record_type = 'adjustment'
                """
            )
        )

        # Clearing and pending-difference accounts have no place in the simplified model.
        op.execute(
            sa.text(
                """
                DELETE FROM accounts
                WHERE subtype IN ('clearing', 'pending_difference')
                  AND NOT EXISTS (
                    SELECT 1 FROM journal_lines jl WHERE jl.account_id = accounts.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM categories c WHERE c.account_id = accounts.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM payment_accounts pa
                    WHERE pa.ledger_account_id = accounts.id
                  )
                """
            )
        )

        bad_entries = bind.scalar(
            sa.text(
                """
                SELECT COUNT(*) FROM (
                  SELECT je.id
                  FROM journal_entries je
                  JOIN journal_lines jl ON jl.entry_id = je.id
                  WHERE je.status = 'posted'
                  GROUP BY je.id
                  HAVING SUM(jl.debit_cny_e8) != SUM(jl.credit_cny_e8)
                )
                """
            )
        )
        if int(bad_entries or 0):
            raise RuntimeError("Cash normalization produced unbalanced posted journals")
        _install_posted_line_guard()
        bind.exec_driver_sql("RELEASE SAVEPOINT normalize_cash_records")
    except Exception:
        bind.exec_driver_sql("ROLLBACK TO SAVEPOINT normalize_cash_records")
        bind.exec_driver_sql("RELEASE SAVEPOINT normalize_cash_records")
        raise


def downgrade() -> None:
    # Historical semantic normalization is intentionally irreversible.
    pass
