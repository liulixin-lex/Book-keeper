"""Link providers to expense categories and remove legacy roles.

Revision ID: 0010_link_providers_categories
Revises: 0009_repair_cash_metadata
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_link_providers_categories"
down_revision: str | None = "0009_repair_cash_metadata"
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

CATEGORY_SQL = """
COALESCE(
  (
    SELECT br.category_id
    FROM business_records br
    JOIN categories linked_category ON linked_category.id = br.category_id
    WHERE br.counterparty_id = counterparties.id
      AND br.record_type = 'expense'
      AND linked_category.kind = 'expense'
      AND linked_category.is_active = 1
    GROUP BY br.category_id
    ORDER BY COUNT(*) DESC, MAX(br.accounting_date) DESC, br.category_id
    LIMIT 1
  ),
  (
    SELECT fallback.id
    FROM categories fallback
    WHERE fallback.workspace_id = counterparties.workspace_id
      AND fallback.kind = 'expense'
      AND fallback.name = '其他支出'
    LIMIT 1
  ),
  (
    SELECT fallback.id
    FROM categories fallback
    WHERE fallback.workspace_id = counterparties.workspace_id
      AND fallback.kind = 'expense'
      AND fallback.is_active = 1
    ORDER BY fallback.name
    LIMIT 1
  )
)
"""


def _has_expense_category_column(bind: sa.Connection) -> bool:
    return any(
        column["name"] == "expense_category_id"
        for column in sa.inspect(bind).get_columns("counterparties")
    )


def _has_expense_category_fk(bind: sa.Connection) -> bool:
    return any(
        foreign_key.get("referred_table") == "categories"
        and foreign_key.get("constrained_columns") == ["expense_category_id"]
        for foreign_key in sa.inspect(bind).get_foreign_keys("counterparties")
    )


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("SAVEPOINT link_providers_categories")
    try:
        if not _has_expense_category_column(bind):
            bind.exec_driver_sql(
                "ALTER TABLE counterparties "
                "ADD COLUMN expense_category_id VARCHAR(36) REFERENCES categories(id)"
            )
        elif not _has_expense_category_fk(bind):
            raise RuntimeError("Provider category column exists without its foreign key")

        bind.execute(
            sa.text(
                f"""
                INSERT INTO audit_events (
                  id, workspace_id, actor_type, action, entity_type, entity_id,
                  before_json, after_json
                )
                SELECT
                  {UUID_SQL}, counterparties.workspace_id, 'system',
                  'migration.provider.normalize', 'provider', counterparties.id,
                  json_object('roles', json(counterparties.roles_json)),
                  json_object(
                    'role', 'supplier',
                    'expense_category_id', {CATEGORY_SQL},
                    'migration', '0010_link_providers_categories'
                  )
                FROM counterparties
                WHERE NOT EXISTS (
                  SELECT 1 FROM audit_events audit
                  WHERE audit.entity_id = counterparties.id
                    AND audit.action = 'migration.provider.normalize'
                )
                """
            )
        )
        bind.execute(
            sa.text(
                f"""
                UPDATE counterparties
                SET roles_json = '["supplier"]',
                    expense_category_id = {CATEGORY_SQL}
                """
            )
        )

        invalid = bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM counterparties provider
                LEFT JOIN categories category ON category.id = provider.expense_category_id
                WHERE provider.expense_category_id IS NULL
                   OR category.workspace_id != provider.workspace_id
                   OR category.kind != 'expense'
                """
            )
        ).scalar_one()
        if invalid:
            raise RuntimeError(f"Provider category normalization failed for {invalid} rows")
    except Exception:
        bind.exec_driver_sql("ROLLBACK TO SAVEPOINT link_providers_categories")
        bind.exec_driver_sql("RELEASE SAVEPOINT link_providers_categories")
        raise
    bind.exec_driver_sql("RELEASE SAVEPOINT link_providers_categories")


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM audit_events WHERE action = 'migration.provider.normalize'"
        )
    )
    if _has_expense_category_column(bind):
        bind.exec_driver_sql("ALTER TABLE counterparties DROP COLUMN expense_category_id")
