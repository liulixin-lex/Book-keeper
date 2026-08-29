"""Normalize legacy counterparty roles.

Revision ID: 0007_normalize_counterparty_roles
Revises: 0006_simplify_master_data
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_normalize_counterparty_roles"
down_revision: str | None = "0006_simplify_master_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE counterparties
            SET roles_json = CASE
              WHEN EXISTS (
                SELECT 1 FROM json_each(counterparties.roles_json)
                WHERE value = 'customer'
              ) THEN '["customer", "supplier"]'
              ELSE '["supplier"]'
            END
            WHERE EXISTS (
              SELECT 1 FROM json_each(counterparties.roles_json)
              WHERE value IN ('upstream', 'vendor')
            )
            """
        )
    )


def downgrade() -> None:
    pass
