"""Lean ledger: every write takes effect at once; history stays in the append-only ledger.

Removed: drafts and the separate posting step, corrections as new transactions (edits now re-post the
same transaction), review flags, two-phase previews, fiscal periods with close / lock / lock exceptions
/ checkpoints, period-end revaluation and year close, reconciliation sessions, balance assertions and
open-item settlement. Scopes ``ledger:draft`` / ``ledger:post`` / ``ledger:correct`` merge into
``ledger:write``; ``periods:manage`` and ``reconcile:write`` go away.

Drafts and discarded drafts never reached the ledger: they are deleted and their source records return
to the import queue. One-way: to go back, restore the pre-upgrade backup.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATA = """
CREATE TEMP TABLE lean_unposted ON COMMIT DROP AS
    SELECT id FROM transactions WHERE status IN ('draft', 'discarded');
UPDATE source_records SET
    status = CASE WHEN classification ? 'type' THEN 'classified' ELSE 'new' END,
    transaction_id = NULL,
    version = version + 1
WHERE transaction_id IN (SELECT id FROM lean_unposted);
DELETE FROM match_suggestions WHERE transaction_id IN (SELECT id FROM lean_unposted);
DELETE FROM transaction_sources WHERE transaction_id IN (SELECT id FROM lean_unposted);
DELETE FROM transaction_tags WHERE transaction_id IN (SELECT id FROM lean_unposted);
DELETE FROM transaction_links
WHERE from_transaction_id IN (SELECT id FROM lean_unposted) OR to_transaction_id IN (SELECT id FROM lean_unposted);
DELETE FROM attachments WHERE entity_type = 'transaction' AND entity_id IN (SELECT id FROM lean_unposted);
UPDATE transactions SET corrects_transaction_id = NULL, corrected_by_transaction_id = NULL
WHERE corrects_transaction_id IS NOT NULL OR corrected_by_transaction_id IS NOT NULL;
DELETE FROM transactions WHERE id IN (SELECT id FROM lean_unposted);

UPDATE api_tokens SET scopes = ARRAY(
    SELECT DISTINCT CASE WHEN s IN ('ledger:draft', 'ledger:post', 'ledger:correct') THEN 'ledger:write' ELSE s END
    FROM unnest(scopes) AS s
    WHERE s NOT IN ('periods:manage', 'reconcile:write')
    ORDER BY 1
);

UPDATE import_sources SET config = config - 'commit_mode' WHERE config ? 'commit_mode';
UPDATE rules SET actions = coalesce(
    (SELECT jsonb_agg(a) FROM jsonb_array_elements(actions) a WHERE a ->> 'type' <> 'mark_review'), '[]'::jsonb)
WHERE actions::text LIKE '%mark_review%';

DELETE FROM transaction_types tt
WHERE tt.code IN ('fx_revaluation', 'year_end_close', 'adjustment')
  AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.transaction_type_id = tt.id);
UPDATE transaction_types SET is_active = false WHERE code IN ('fx_revaluation', 'year_end_close', 'adjustment');
"""

TRIGGERS = """
DROP TRIGGER IF EXISTS lock_settings_hard_monotonic ON lock_settings;
DROP TRIGGER IF EXISTS fiscal_periods_guard ON fiscal_periods;
DROP FUNCTION IF EXISTS bk_lock_settings_guard();
DROP FUNCTION IF EXISTS bk_period_guard();

-- Business dates are always writable now; the insert trigger only stamps the recording time.
CREATE OR REPLACE FUNCTION bk_journal_entry_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.recorded_at := now();
    RETURN NEW;
END $$;

-- Journal lines had mutable reconciliation / open-item columns; with those gone a line never changes.
DROP TRIGGER journal_lines_immutable ON journal_lines;
CREATE TRIGGER journal_lines_immutable
    BEFORE UPDATE OR DELETE ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION bk_reject_modification();
"""


def upgrade() -> None:
    op.execute(DATA)
    op.execute(TRIGGERS)

    for table in (
        "previews",
        "line_matches",
        "reconciliations",
        "balance_assertions",
        "lock_exceptions",
        "period_checkpoints",
        "lock_settings",
    ):
        op.drop_table(table)

    op.execute("DELETE FROM transaction_links WHERE kind = 'correction_of'")
    op.drop_constraint(op.f("ck_transaction_links_kind"), "transaction_links", type_="check")
    op.create_check_constraint(
        op.f("ck_transaction_links_kind"), "transaction_links", "kind IN ('refund_of','related')"
    )

    op.drop_constraint(op.f("ck_transactions_review_status"), "transactions", type_="check")
    op.drop_constraint(op.f("ck_transactions_status"), "transactions", type_="check")
    op.create_check_constraint(op.f("ck_transactions_status"), "transactions", "status IN ('posted','reversed')")
    op.alter_column("transactions", "status", server_default="posted")
    for column in (
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "corrects_transaction_id",
        "corrected_by_transaction_id",
        "discarded_at",
        "discard_reason",
    ):
        op.drop_column("transactions", column)

    op.drop_index(op.f("ix_journal_lines_open"), table_name="journal_lines")
    op.drop_constraint(op.f("ck_journal_lines_cleared_status"), "journal_lines", type_="check")
    op.drop_constraint(op.f("ck_journal_lines_open_amount"), "journal_lines", type_="check")
    for column in ("cleared_status", "cleared_at", "reconciliation_id", "open_amount", "open_base_amount"):
        op.drop_column("journal_lines", column)

    op.drop_constraint(op.f("ck_accounts_cash_flow_activity"), "accounts", type_="check")
    for column in ("is_open_item", "is_reconcilable", "cash_flow_activity"):
        op.drop_column("accounts", column)

    op.drop_column("journal_entries", "period_id")
    op.drop_table("fiscal_periods")

    op.drop_column("api_tokens", "require_preview_for")
    op.drop_column("mcp_calls", "preview_id")


def downgrade() -> None:
    raise NotImplementedError("0011 removes features and their data; restore the pre-upgrade backup instead.")
