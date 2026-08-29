"""Repair normalized cash metadata after the historical difference was removed.

Revision ID: 0009_repair_cash_metadata
Revises: 0008_normalize_cash_records
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_repair_cash_metadata"
down_revision: str | None = "0008_normalize_cash_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("SAVEPOINT repair_cash_metadata")
    try:
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
        bind.exec_driver_sql("RELEASE SAVEPOINT repair_cash_metadata")
    except Exception:
        bind.exec_driver_sql("ROLLBACK TO SAVEPOINT repair_cash_metadata")
        bind.exec_driver_sql("RELEASE SAVEPOINT repair_cash_metadata")
        raise


def downgrade() -> None:
    pass
