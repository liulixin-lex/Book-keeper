"""Year-end close: base-only ``closing`` lines (P&L balances carried only in base amounts).

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "amount <> 0 OR (base_amount <> 0 AND line_role IN ('rounding','fx_realization','revaluation'))"
NEW = "amount <> 0 OR (base_amount <> 0 AND line_role IN ('rounding','fx_realization','revaluation','closing'))"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_journal_lines_base_only_roles"), "journal_lines", type_="check")
    op.create_check_constraint(op.f("ck_journal_lines_base_only_roles"), "journal_lines", NEW)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_journal_lines_base_only_roles"), "journal_lines", type_="check")
    op.create_check_constraint(op.f("ck_journal_lines_base_only_roles"), "journal_lines", OLD)
