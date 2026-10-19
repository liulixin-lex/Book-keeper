"""Currencies become data: the app may add and edit them; a used one keeps its number of decimals.

Grants are applied by ``bookkeeper migrate`` (``db/roles.py``): INSERT / UPDATE allowed, DELETE never.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARD = """
CREATE FUNCTION bk_commodities_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.code <> OLD.code THEN
        RAISE EXCEPTION 'commodity code % cannot change', OLD.code USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.scale <> OLD.scale AND (
        EXISTS (SELECT 1 FROM journal_lines WHERE commodity = OLD.code)
        OR EXISTS (SELECT 1 FROM source_records WHERE commodity = OLD.code)
        OR EXISTS (SELECT 1 FROM fee_rules WHERE commodity = OLD.code)
        OR EXISTS (SELECT 1 FROM transactions WHERE inputs::text LIKE '%"commodity": "' || OLD.code || '"%')
    ) THEN
        RAISE EXCEPTION 'commodity % is in use: its scale cannot change', OLD.code USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER commodities_guard BEFORE UPDATE ON commodities
    FOR EACH ROW EXECUTE FUNCTION bk_commodities_guard();
"""


def upgrade() -> None:
    op.execute(GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER commodities_guard ON commodities; DROP FUNCTION bk_commodities_guard();")
