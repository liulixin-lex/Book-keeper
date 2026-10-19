"""ledger core: reference data, transactions, journal, balances, periods, checks.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18 16:37:31.072175+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEDGER_INVARIANTS_SQL = r"""
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE commodity_price_rules ADD CONSTRAINT ex_commodity_price_rules_range
    EXCLUDE USING gist (
        book_id WITH =, commodity WITH =, quote_commodity WITH =, purpose WITH =,
        daterange(valid_from, valid_to, '[]') WITH &&
    );

-- DB-01: every entry balances per commodity and in base currency (checked at commit).
CREATE FUNCTION bk_check_entry_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    entry text := coalesce(to_jsonb(NEW) ->> 'entry_id', to_jsonb(NEW) ->> 'id');
    bad text;
    base_sum bigint;
    n integer;
    expected integer;
BEGIN
    SELECT commodity INTO bad FROM journal_lines WHERE entry_id = entry
        GROUP BY commodity HAVING sum(amount) <> 0 LIMIT 1;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'journal entry % is not balanced in %', entry, bad
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT coalesce(sum(base_amount), 0), count(*) INTO base_sum, n
        FROM journal_lines WHERE entry_id = entry;
    IF base_sum <> 0 THEN
        RAISE EXCEPTION 'journal entry % is not balanced in base currency (%)', entry, base_sum
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT line_count INTO expected FROM journal_entries WHERE id = entry;
    IF n <> expected THEN
        RAISE EXCEPTION 'journal entry % has % lines, expected %', entry, n, expected
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER journal_lines_balanced
    AFTER INSERT ON journal_lines DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION bk_check_entry_balanced();
CREATE CONSTRAINT TRIGGER journal_entries_balanced
    AFTER INSERT ON journal_entries DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION bk_check_entry_balanced();

-- DB-02 / DB-03: append-only ledger with a short list of mutable columns.
CREATE FUNCTION bk_guard_mutable_columns() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    allowed text[] := TG_ARGV::text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - allowed) IS DISTINCT FROM (to_jsonb(OLD) - allowed) THEN
        RAISE EXCEPTION 'only % may change on %', allowed, TG_TABLE_NAME
            USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(OLD) ->> 'reversed_by_entry_id') IS NOT NULL
       AND (to_jsonb(NEW) ->> 'reversed_by_entry_id') IS DISTINCT FROM (to_jsonb(OLD) ->> 'reversed_by_entry_id') THEN
        RAISE EXCEPTION 'entry % is already reversed', OLD.id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER journal_entries_immutable
    BEFORE UPDATE OR DELETE ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION bk_guard_mutable_columns('reversed_by_entry_id');
CREATE TRIGGER journal_lines_immutable
    BEFORE UPDATE OR DELETE ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION bk_guard_mutable_columns(
        'cleared_status', 'cleared_at', 'reconciliation_id', 'open_amount', 'open_base_amount');
CREATE TRIGGER journal_entries_no_truncate BEFORE TRUNCATE ON journal_entries
    FOR EACH STATEMENT EXECUTE FUNCTION bk_reject_modification();
CREATE TRIGGER journal_lines_no_truncate BEFORE TRUNCATE ON journal_lines
    FOR EACH STATEMENT EXECUTE FUNCTION bk_reject_modification();
CREATE TRIGGER journal_line_dimensions_immutable
    BEFORE UPDATE OR DELETE ON journal_line_dimensions
    FOR EACH ROW EXECUTE FUNCTION bk_reject_modification();

-- DB-04 / DB-05: server-side recording time; hard lock and locked periods.
CREATE FUNCTION bk_journal_entry_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    hard date;
    p fiscal_periods%ROWTYPE;
BEGIN
    NEW.recorded_at := now();
    SELECT hard_lock_date INTO hard FROM lock_settings WHERE book_id = NEW.book_id;
    IF hard IS NOT NULL AND NEW.effective_date <= hard THEN
        RAISE EXCEPTION 'business date % is on or before the hard lock date %', NEW.effective_date, hard
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT * INTO p FROM fiscal_periods WHERE id = NEW.period_id;
    IF NOT FOUND OR p.book_id <> NEW.book_id
       OR NEW.effective_date NOT BETWEEN p.start_date AND p.end_date THEN
        RAISE EXCEPTION 'period % does not contain %', NEW.period_id, NEW.effective_date
            USING ERRCODE = 'check_violation';
    END IF;
    IF p.status = 'locked' THEN
        RAISE EXCEPTION 'period %-% is locked', p.year, p.month USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER journal_entries_insert BEFORE INSERT ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION bk_journal_entry_insert();

-- DB-06 / DB-07 / DB-13: postable account, allowed commodity, dates, base-currency consistency.
CREATE FUNCTION bk_journal_line_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    acc accounts%ROWTYPE;
    base text;
    entry_date date;
BEGIN
    SELECT * INTO acc FROM accounts WHERE id = NEW.account_id AND book_id = NEW.book_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'account % is not in book %', NEW.account_id, NEW.book_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF acc.is_group OR NOT acc.is_active THEN
        RAISE EXCEPTION 'account % is not postable', acc.code USING ERRCODE = 'check_violation';
    END IF;
    IF acc.allowed_commodities IS NOT NULL AND NOT (NEW.commodity = ANY (acc.allowed_commodities)) THEN
        RAISE EXCEPTION 'account % does not allow %', acc.code, NEW.commodity
            USING ERRCODE = 'check_violation';
    END IF;
    IF (acc.open_date IS NOT NULL AND NEW.effective_date < acc.open_date)
       OR (acc.close_date IS NOT NULL AND NEW.effective_date > acc.close_date) THEN
        RAISE EXCEPTION 'account % is not open on %', acc.code, NEW.effective_date
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT base_commodity INTO base FROM books WHERE id = NEW.book_id;
    IF NEW.commodity = base AND (NEW.base_amount <> NEW.amount OR NEW.fx_rate IS NOT NULL) THEN
        RAISE EXCEPTION 'base-currency line must have base_amount = amount and no rate'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT effective_date INTO entry_date FROM journal_entries WHERE id = NEW.entry_id;
    IF entry_date IS DISTINCT FROM NEW.effective_date THEN
        RAISE EXCEPTION 'line date differs from entry date' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER journal_lines_insert BEFORE INSERT ON journal_lines
    FOR EACH ROW EXECUTE FUNCTION bk_journal_line_insert();

-- DB-08: the hard lock date only moves forward; locked periods stay locked.
CREATE FUNCTION bk_lock_settings_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.hard_lock_date IS NOT NULL
       AND (NEW.hard_lock_date IS NULL OR NEW.hard_lock_date < OLD.hard_lock_date) THEN
        RAISE EXCEPTION 'hard lock date cannot move backwards' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER lock_settings_hard_monotonic BEFORE UPDATE ON lock_settings
    FOR EACH ROW EXECUTE FUNCTION bk_lock_settings_guard();

CREATE FUNCTION bk_period_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'periods cannot be deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'locked' AND NEW.status <> 'locked' THEN
        RAISE EXCEPTION 'locked period cannot be reopened' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER fiscal_periods_guard BEFORE UPDATE OR DELETE ON fiscal_periods
    FOR EACH ROW EXECUTE FUNCTION bk_period_guard();

-- DB-10 / DB-11: account hierarchy and protection of accounts in use.
CREATE FUNCTION bk_accounts_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    p accounts%ROWTYPE;
    in_use boolean;
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        SELECT * INTO p FROM accounts WHERE id = NEW.parent_id;
        IF NOT FOUND OR p.book_id <> NEW.book_id THEN
            RAISE EXCEPTION 'parent account not found in book' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT p.is_group THEN
            RAISE EXCEPTION 'parent % is not a group account', p.code USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.code NOT LIKE p.code || '.%' THEN
            RAISE EXCEPTION 'code % must start with parent code %', NEW.code, p.code
                USING ERRCODE = 'check_violation';
        END IF;
        IF p.classification <> NEW.classification THEN
            RAISE EXCEPTION 'classification must match parent' USING ERRCODE = 'check_violation';
        END IF;
        NEW.level := p.level + 1;
    ELSE
        IF position('.' IN NEW.code) > 0 THEN
            RAISE EXCEPTION 'detail code % requires a parent', NEW.code USING ERRCODE = 'check_violation';
        END IF;
        NEW.level := 1;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        SELECT EXISTS (SELECT 1 FROM account_balances WHERE account_id = OLD.id AND line_count > 0)
            INTO in_use;
        IF in_use THEN
            IF NEW.code <> OLD.code OR NEW.classification <> OLD.classification
               OR NEW.normal_side <> OLD.normal_side OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
               OR (NEW.is_group AND NOT OLD.is_group) THEN
                RAISE EXCEPTION 'account % has postings; code, classification, side, parent and group flag are fixed', OLD.code
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.allowed_commodities IS NOT NULL AND EXISTS (
                SELECT 1 FROM account_balances WHERE account_id = OLD.id AND line_count > 0
                AND NOT (commodity = ANY (NEW.allowed_commodities))) THEN
                RAISE EXCEPTION 'account % already has postings in commodities outside the new list', OLD.code
                    USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER accounts_guard BEFORE INSERT OR UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION bk_accounts_guard();
"""

DROP_LEDGER_INVARIANTS_SQL = r"""
DROP TRIGGER IF EXISTS accounts_guard ON accounts;
DROP TRIGGER IF EXISTS fiscal_periods_guard ON fiscal_periods;
DROP TRIGGER IF EXISTS lock_settings_hard_monotonic ON lock_settings;
DROP TRIGGER IF EXISTS journal_lines_insert ON journal_lines;
DROP TRIGGER IF EXISTS journal_entries_insert ON journal_entries;
DROP TRIGGER IF EXISTS journal_line_dimensions_immutable ON journal_line_dimensions;
DROP TRIGGER IF EXISTS journal_lines_no_truncate ON journal_lines;
DROP TRIGGER IF EXISTS journal_entries_no_truncate ON journal_entries;
DROP TRIGGER IF EXISTS journal_lines_immutable ON journal_lines;
DROP TRIGGER IF EXISTS journal_entries_immutable ON journal_entries;
DROP TRIGGER IF EXISTS journal_entries_balanced ON journal_entries;
DROP TRIGGER IF EXISTS journal_lines_balanced ON journal_lines;
DROP FUNCTION IF EXISTS bk_accounts_guard();
DROP FUNCTION IF EXISTS bk_period_guard();
DROP FUNCTION IF EXISTS bk_lock_settings_guard();
DROP FUNCTION IF EXISTS bk_journal_line_insert();
DROP FUNCTION IF EXISTS bk_journal_entry_insert();
DROP FUNCTION IF EXISTS bk_guard_mutable_columns();
DROP FUNCTION IF EXISTS bk_check_entry_balanced();
ALTER TABLE commodity_price_rules DROP CONSTRAINT IF EXISTS ex_commodity_price_rules_range;
"""


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("base", sa.String(length=12), nullable=False),
        sa.Column("quote", sa.String(length=12), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("rate_type", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("fetched_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "rate_type IN ('reference','actual','derived','manual')", name=op.f("ck_fx_rates_rate_type")
        ),
        sa.CheckConstraint("base <> quote", name=op.f("ck_fx_rates_distinct")),
        sa.CheckConstraint("rate > 0", name=op.f("ck_fx_rates_rate_positive")),
        sa.ForeignKeyConstraint(["base"], ["commodities.code"], name=op.f("fk_fx_rates_base_commodities")),
        sa.ForeignKeyConstraint(["quote"], ["commodities.code"], name=op.f("fk_fx_rates_quote_commodities")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fx_rates")),
        sa.UniqueConstraint(
            "base",
            "quote",
            "rate_date",
            "rate_type",
            "source",
            name=op.f("uq_fx_rates_base_quote_rate_date_rate_type_source"),
        ),
    )
    op.create_index("ix_fx_rates_lookup", "fx_rates", ["base", "quote", "rate_date"], unique=False)
    op.create_table(
        "accounts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("level", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("is_group", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("normal_side", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("is_default_for_role", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("allowed_commodities", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("open_date", sa.Date(), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("balance_rule", sa.Text(), server_default="any", nullable=False),
        sa.Column("manual_entry_allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "required_dimensions", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column(
            "forbidden_dimensions", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column("is_open_item", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_reconcilable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("standard_code", sa.Text(), nullable=True),
        sa.Column("cash_flow_activity", sa.Text(), server_default="operating", nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("balance_rule IN ('any','normal_side_only')", name=op.f("ck_accounts_balance_rule")),
        sa.CheckConstraint(
            "cash_flow_activity IN ('cash','operating','investing','financing','none')",
            name=op.f("ck_accounts_cash_flow_activity"),
        ),
        sa.CheckConstraint(
            "classification IN ('asset','liability','equity','revenue','expense')",
            name=op.f("ck_accounts_classification"),
        ),
        sa.CheckConstraint("code ~ '^[0-9]{4}(\\.[0-9]{2})*$'", name=op.f("ck_accounts_code_format")),
        sa.CheckConstraint("normal_side IN ('debit','credit')", name=op.f("ck_accounts_normal_side")),
        sa.CheckConstraint(
            "close_date IS NULL OR open_date IS NULL OR close_date >= open_date", name=op.f("ck_accounts_dates")
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_accounts_book_id_books")),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], name=op.f("fk_accounts_parent_id_accounts")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("book_id", "code", name=op.f("uq_accounts_book_id_code")),
        sa.UniqueConstraint("book_id", "id", name=op.f("uq_accounts_book_id_id")),
    )
    op.create_index(
        "uq_accounts_default_role",
        "accounts",
        ["book_id", "role"],
        unique=True,
        postgresql_where=sa.text("is_default_for_role"),
    )
    op.create_table(
        "check_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('running','passed','failed')", name=op.f("ck_check_runs_status")),
        sa.CheckConstraint(
            "trigger IN ('scheduled','manual','period_close','post_migration')", name=op.f("ck_check_runs_trigger")
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_check_runs_book_id_books")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_runs")),
    )
    op.create_index(op.f("ix_check_runs_book_id"), "check_runs", ["book_id"], unique=False)
    op.create_table(
        "commodity_price_rules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("commodity", sa.String(length=12), nullable=False),
        sa.Column("quote_commodity", sa.String(length=12), nullable=False),
        sa.Column("rate", sa.Numeric(precision=28, scale=12), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('nominal_valuation','conversion')", name=op.f("ck_commodity_price_rules_purpose")
        ),
        sa.CheckConstraint("commodity <> quote_commodity", name=op.f("ck_commodity_price_rules_distinct")),
        sa.CheckConstraint("rate > 0", name=op.f("ck_commodity_price_rules_rate_positive")),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name=op.f("ck_commodity_price_rules_range")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_commodity_price_rules_book_id_books")),
        sa.ForeignKeyConstraint(
            ["commodity"], ["commodities.code"], name=op.f("fk_commodity_price_rules_commodity_commodities")
        ),
        sa.ForeignKeyConstraint(
            ["quote_commodity"], ["commodities.code"], name=op.f("fk_commodity_price_rules_quote_commodity_commodities")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commodity_price_rules")),
    )
    op.create_table(
        "counterparties",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("domains", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("default_transaction_type_id", sa.Text(), nullable=True),
        sa.Column(
            "default_dimensions",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "category IN ('upstream_site','ai_vendor','cloud_vendor','marketplace','payment_provider','marketing_vendor','business_service','customer','other')",
            name=op.f("ck_counterparties_category"),
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_counterparties_book_id_books")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counterparties")),
        sa.UniqueConstraint("book_id", "name", name=op.f("uq_counterparties_book_id_name")),
    )
    op.create_table(
        "dimension_types",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_hierarchical", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,31}$'", name=op.f("ck_dimension_types_code_format")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_dimension_types_book_id_books")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dimension_types")),
        sa.UniqueConstraint("book_id", "code", name=op.f("uq_dimension_types_book_id_code")),
    )
    op.create_table(
        "fiscal_periods",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("month", sa.SmallInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("closed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("closed_by", sa.Text(), nullable=True),
        sa.Column("locked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("reopen_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("status IN ('open','closed','locked')", name=op.f("ck_fiscal_periods_status")),
        sa.CheckConstraint("end_date >= start_date", name=op.f("ck_fiscal_periods_range")),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name=op.f("ck_fiscal_periods_month")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_fiscal_periods_book_id_books")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fiscal_periods")),
        sa.UniqueConstraint("book_id", "start_date", name=op.f("uq_fiscal_periods_book_id_start_date")),
        sa.UniqueConstraint("book_id", "year", "month", name=op.f("uq_fiscal_periods_book_id_year_month")),
    )
    op.create_table(
        "ledger_heads",
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
        sa.Column("last_entry_hash", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_ledger_heads_book_id_books")),
        sa.PrimaryKeyConstraint("book_id", name=op.f("pk_ledger_heads")),
    )
    op.create_table(
        "lock_settings",
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("soft_lock_date", sa.Date(), nullable=True),
        sa.Column("hard_lock_date", sa.Date(), nullable=True),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_lock_settings_book_id_books")),
        sa.PrimaryKeyConstraint("book_id", name=op.f("pk_lock_settings")),
    )
    op.create_table(
        "sequences",
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("next_value", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_sequences_book_id_books")),
        sa.PrimaryKeyConstraint("book_id", "scope", "period", name=op.f("pk_sequences")),
    )
    op.create_table(
        "transaction_types",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "category IN ('income','expense','transfer','adjustment','other')",
            name=op.f("ck_transaction_types_category"),
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_transaction_types_book_id_books")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_types")),
        sa.UniqueConstraint("book_id", "code", name=op.f("uq_transaction_types_book_id_code")),
    )
    op.create_table(
        "account_balances",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("commodity", sa.String(length=12), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("base_balance", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("debit_total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credit_total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("base_debit_total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("base_credit_total", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("line_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_seq", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_account_balances_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["commodity"], ["commodities.code"], name=op.f("fk_account_balances_commodity_commodities")
        ),
        sa.PrimaryKeyConstraint("account_id", "commodity", name=op.f("pk_account_balances")),
    )
    op.create_index(op.f("ix_account_balances_book_id"), "account_balances", ["book_id"], unique=False)
    op.create_table(
        "check_results",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("check_code", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint("severity IN ('error','warning','info')", name=op.f("ck_check_results_severity")),
        sa.CheckConstraint("status IN ('pass','fail','skip')", name=op.f("ck_check_results_status")),
        sa.ForeignKeyConstraint(["run_id"], ["check_runs.id"], name=op.f("fk_check_results_run_id_check_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_results")),
    )
    op.create_index(op.f("ix_check_results_run_id"), "check_results", ["run_id"], unique=False)
    op.create_table(
        "counterparty_accounts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("counterparty_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_counterparty_accounts_book_id_books")),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["counterparties.id"],
            name=op.f("fk_counterparty_accounts_counterparty_id_counterparties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counterparty_accounts")),
        sa.UniqueConstraint("counterparty_id", "label", name=op.f("uq_counterparty_accounts_counterparty_id_label")),
    )
    op.create_table(
        "counterparty_aliases",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("counterparty_id", sa.Text(), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("match_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="100", nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "match_type IN ('exact','contains','regex','domain')", name=op.f("ck_counterparty_aliases_match_type")
        ),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_counterparty_aliases_book_id_books")),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["counterparties.id"],
            name=op.f("fk_counterparty_aliases_counterparty_id_counterparties"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counterparty_aliases")),
        sa.UniqueConstraint(
            "book_id", "match_type", "pattern", name=op.f("uq_counterparty_aliases_book_id_match_type_pattern")
        ),
    )
    op.create_table(
        "daily_balances",
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("commodity", sa.String(length=12), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("debit", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credit", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("base_debit", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("base_credit", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("line_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name=op.f("fk_daily_balances_account_id_accounts")),
        sa.ForeignKeyConstraint(
            ["commodity"], ["commodities.code"], name=op.f("fk_daily_balances_commodity_commodities")
        ),
        sa.PrimaryKeyConstraint("account_id", "commodity", "date", name=op.f("pk_daily_balances")),
    )
    op.create_index("ix_daily_balances_book_date", "daily_balances", ["book_id", "date"], unique=False)
    op.create_table(
        "dimension_values",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("type_id", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("counterparty_id", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9][a-z0-9_]{0,47}$'", name=op.f("ck_dimension_values_code_format")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_dimension_values_book_id_books")),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["dimension_values.id"], name=op.f("fk_dimension_values_parent_id_dimension_values")
        ),
        sa.ForeignKeyConstraint(
            ["type_id"], ["dimension_types.id"], name=op.f("fk_dimension_values_type_id_dimension_types")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dimension_values")),
        sa.UniqueConstraint("type_id", "code", name=op.f("uq_dimension_values_type_id_code")),
    )
    op.create_table(
        "lock_exceptions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("token_id", sa.Text(), nullable=True),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("used_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("length(reason) >= 2", name=op.f("ck_lock_exceptions_reason")),
        sa.CheckConstraint("to_date >= from_date", name=op.f("ck_lock_exceptions_range")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_lock_exceptions_book_id_books")),
        sa.ForeignKeyConstraint(["token_id"], ["api_tokens.id"], name=op.f("fk_lock_exceptions_token_id_api_tokens")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_lock_exceptions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lock_exceptions")),
    )
    op.create_table(
        "period_checkpoints",
        sa.Column("period_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("commodity", sa.String(length=12), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("closing_balance", sa.BigInteger(), nullable=False),
        sa.Column("base_closing_balance", sa.BigInteger(), nullable=False),
        sa.Column("debit_total", sa.BigInteger(), nullable=False),
        sa.Column("credit_total", sa.BigInteger(), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_period_checkpoints_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["commodity"], ["commodities.code"], name=op.f("fk_period_checkpoints_commodity_commodities")
        ),
        sa.ForeignKeyConstraint(
            ["period_id"], ["fiscal_periods.id"], name=op.f("fk_period_checkpoints_period_id_fiscal_periods")
        ),
        sa.PrimaryKeyConstraint("period_id", "account_id", "commodity", name=op.f("pk_period_checkpoints")),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("transaction_type_id", sa.Text(), nullable=False),
        sa.Column("template_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("occurred_offset_minutes", sa.SmallInteger(), nullable=True),
        sa.Column("date_precision", sa.Text(), server_default="day", nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("counterparty_id", sa.Text(), nullable=True),
        sa.Column("counterparty_account_id", sa.Text(), nullable=True),
        sa.Column(
            "inputs",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "computed",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "default_dimensions",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("external_ref", sa.Text(), nullable=True),
        sa.Column("order_no", sa.Text(), nullable=True),
        sa.Column("is_estimate", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("review_status", sa.Text(), server_default="unreviewed", nullable=False),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_channel", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("created_token_id", sa.Text(), nullable=True),
        sa.Column("mcp_client", sa.Text(), nullable=True),
        sa.Column("created_change_set_id", sa.Text(), nullable=True),
        sa.Column("posted_entry_id", sa.Text(), nullable=True),
        sa.Column("posted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("posted_by", sa.Text(), nullable=True),
        sa.Column("reversed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reverse_reason", sa.Text(), nullable=True),
        sa.Column("corrects_transaction_id", sa.Text(), nullable=True),
        sa.Column("corrected_by_transaction_id", sa.Text(), nullable=True),
        sa.Column("discarded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("discard_reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "created_channel IN ('ui','api','mcp','import','system','migration','cli')",
            name=op.f("ck_transactions_created_channel"),
        ),
        sa.CheckConstraint(
            "date_precision IN ('timestamp','day','month')", name=op.f("ck_transactions_date_precision")
        ),
        sa.CheckConstraint("review_status IN ('unreviewed','reviewed')", name=op.f("ck_transactions_review_status")),
        sa.CheckConstraint("status IN ('draft','posted','reversed','discarded')", name=op.f("ck_transactions_status")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_transactions_book_id_books")),
        sa.ForeignKeyConstraint(
            ["corrected_by_transaction_id"],
            ["transactions.id"],
            name=op.f("fk_transactions_corrected_by_transaction_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["corrects_transaction_id"],
            ["transactions.id"],
            name=op.f("fk_transactions_corrects_transaction_id_transactions"),
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_account_id"],
            ["counterparty_accounts.id"],
            name=op.f("fk_transactions_counterparty_account_id_counterparty_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_id"], ["counterparties.id"], name=op.f("fk_transactions_counterparty_id_counterparties")
        ),
        sa.ForeignKeyConstraint(
            ["transaction_type_id"],
            ["transaction_types.id"],
            name=op.f("fk_transactions_transaction_type_id_transaction_types"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        sa.UniqueConstraint("book_id", "number", name=op.f("uq_transactions_book_id_number")),
    )
    op.create_index(
        "ix_transactions_book_counterparty",
        "transactions",
        ["book_id", "counterparty_id", "effective_date"],
        unique=False,
    )
    op.create_index("ix_transactions_book_date", "transactions", ["book_id", "effective_date"], unique=False)
    op.create_index("ix_transactions_book_status", "transactions", ["book_id", "status"], unique=False)
    op.create_index(op.f("ix_transactions_order_no"), "transactions", ["order_no"], unique=False)
    op.create_index(
        "uq_transactions_external_ref",
        "transactions",
        ["book_id", "external_ref"],
        unique=True,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("journal_code", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=False),
        sa.Column("period_id", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("recorded_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("template_id", sa.Text(), nullable=True),
        sa.Column("fee_rule_ids", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reverses_entry_id", sa.Text(), nullable=True),
        sa.Column("reversed_by_entry_id", sa.Text(), nullable=True),
        sa.Column("attachment_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("line_count", sa.SmallInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("created_token_id", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("change_set_id", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('posting','reversal','repost_reversal','repost','adjustment')",
            name=op.f("ck_journal_entries_kind"),
        ),
        sa.CheckConstraint("line_count >= 2", name=op.f("ck_journal_entries_line_count")),
        sa.ForeignKeyConstraint(["book_id"], ["books.id"], name=op.f("fk_journal_entries_book_id_books")),
        sa.ForeignKeyConstraint(
            ["period_id"], ["fiscal_periods.id"], name=op.f("fk_journal_entries_period_id_fiscal_periods")
        ),
        sa.ForeignKeyConstraint(
            ["reversed_by_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_journal_entries_reversed_by_entry_id_journal_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["reverses_entry_id"],
            ["journal_entries.id"],
            name=op.f("fk_journal_entries_reverses_entry_id_journal_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], name=op.f("fk_journal_entries_transaction_id_transactions")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_entries")),
        sa.UniqueConstraint("book_id", "id", name=op.f("uq_journal_entries_book_id_id")),
        sa.UniqueConstraint("book_id", "number", name=op.f("uq_journal_entries_book_id_number")),
        sa.UniqueConstraint("book_id", "seq", name=op.f("uq_journal_entries_book_id_seq")),
    )
    op.create_index("ix_journal_entries_book_date", "journal_entries", ["book_id", "effective_date"], unique=False)
    op.create_index("ix_journal_entries_transaction", "journal_entries", ["transaction_id"], unique=False)
    op.create_table(
        "journal_lines",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.Column("entry_id", sa.Text(), nullable=False),
        sa.Column("line_no", sa.SmallInteger(), nullable=False),
        sa.Column("account_id", sa.Text(), nullable=False),
        sa.Column("commodity", sa.String(length=12), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("base_amount", sa.BigInteger(), nullable=False),
        sa.Column("fx_rate", sa.Numeric(precision=28, scale=12), nullable=True),
        sa.Column("fx_rate_id", sa.Text(), nullable=True),
        sa.Column("fx_source", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=28, scale=8), nullable=True),
        sa.Column("quantity_unit", sa.Text(), nullable=True),
        sa.Column("counterparty_id", sa.Text(), nullable=True),
        sa.Column("counterparty_account_id", sa.Text(), nullable=True),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("line_role", sa.Text(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("account_seq", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("base_balance_after", sa.BigInteger(), nullable=False),
        sa.Column("cleared_status", sa.Text(), server_default="uncleared", nullable=False),
        sa.Column("cleared_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reconciliation_id", sa.Text(), nullable=True),
        sa.Column("open_amount", sa.BigInteger(), nullable=True),
        sa.Column("open_base_amount", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "amount <> 0 OR (base_amount <> 0 AND line_role IN ('rounding','fx_realization','revaluation'))",
            name=op.f("ck_journal_lines_base_only_roles"),
        ),
        sa.CheckConstraint(
            "cleared_status IN ('uncleared','cleared','reconciled')", name=op.f("ck_journal_lines_cleared_status")
        ),
        sa.CheckConstraint("(quantity IS NULL) = (quantity_unit IS NULL)", name=op.f("ck_journal_lines_quantity_unit")),
        sa.CheckConstraint(
            "open_amount IS NULL OR (sign(open_amount) IN (0, sign(amount)) AND abs(open_amount) <= abs(amount))",
            name=op.f("ck_journal_lines_open_amount"),
        ),
        sa.ForeignKeyConstraint(
            ["book_id", "account_id"],
            ["accounts.book_id", "accounts.id"],
            name=op.f("fk_journal_lines_book_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["book_id", "entry_id"],
            ["journal_entries.book_id", "journal_entries.id"],
            name=op.f("fk_journal_lines_book_id_journal_entries"),
        ),
        sa.ForeignKeyConstraint(
            ["commodity"], ["commodities.code"], name=op.f("fk_journal_lines_commodity_commodities")
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_account_id"],
            ["counterparty_accounts.id"],
            name=op.f("fk_journal_lines_counterparty_account_id_counterparty_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_id"], ["counterparties.id"], name=op.f("fk_journal_lines_counterparty_id_counterparties")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal_lines")),
        sa.UniqueConstraint(
            "account_id", "commodity", "account_seq", name=op.f("uq_journal_lines_account_id_commodity_account_seq")
        ),
        sa.UniqueConstraint("entry_id", "line_no", name=op.f("uq_journal_lines_entry_id_line_no")),
    )
    op.create_index(
        "ix_journal_lines_account_date", "journal_lines", ["book_id", "account_id", "effective_date"], unique=False
    )
    op.create_index(
        "ix_journal_lines_counterparty", "journal_lines", ["book_id", "counterparty_id", "effective_date"], unique=False
    )
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry_id"], unique=False)
    op.create_index(
        "ix_journal_lines_open",
        "journal_lines",
        ["account_id"],
        unique=False,
        postgresql_where=sa.text("open_amount IS NOT NULL AND open_amount <> 0"),
    )
    op.create_table(
        "journal_line_dimensions",
        sa.Column("line_id", sa.Text(), nullable=False),
        sa.Column("dimension_type_id", sa.Text(), nullable=False),
        sa.Column("dimension_value_id", sa.Text(), nullable=False),
        sa.Column("book_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dimension_type_id"],
            ["dimension_types.id"],
            name=op.f("fk_journal_line_dimensions_dimension_type_id_dimension_types"),
        ),
        sa.ForeignKeyConstraint(
            ["dimension_value_id"],
            ["dimension_values.id"],
            name=op.f("fk_journal_line_dimensions_dimension_value_id_dimension_values"),
        ),
        sa.ForeignKeyConstraint(
            ["line_id"], ["journal_lines.id"], name=op.f("fk_journal_line_dimensions_line_id_journal_lines")
        ),
        sa.PrimaryKeyConstraint("line_id", "dimension_type_id", name=op.f("pk_journal_line_dimensions")),
    )
    op.create_index(
        op.f("ix_journal_line_dimensions_dimension_value_id"),
        "journal_line_dimensions",
        ["dimension_value_id"],
        unique=False,
    )
    # ### end Alembic commands ###
    op.execute(LEDGER_INVARIANTS_SQL)


def downgrade() -> None:
    op.execute(DROP_LEDGER_INVARIANTS_SQL)
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_journal_line_dimensions_dimension_value_id"), table_name="journal_line_dimensions")
    op.drop_table("journal_line_dimensions")
    op.drop_index(
        "ix_journal_lines_open",
        table_name="journal_lines",
        postgresql_where=sa.text("open_amount IS NOT NULL AND open_amount <> 0"),
    )
    op.drop_index("ix_journal_lines_entry", table_name="journal_lines")
    op.drop_index("ix_journal_lines_counterparty", table_name="journal_lines")
    op.drop_index("ix_journal_lines_account_date", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_transaction", table_name="journal_entries")
    op.drop_index("ix_journal_entries_book_date", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_index(
        "uq_transactions_external_ref", table_name="transactions", postgresql_where=sa.text("external_ref IS NOT NULL")
    )
    op.drop_index(op.f("ix_transactions_order_no"), table_name="transactions")
    op.drop_index("ix_transactions_book_status", table_name="transactions")
    op.drop_index("ix_transactions_book_date", table_name="transactions")
    op.drop_index("ix_transactions_book_counterparty", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("period_checkpoints")
    op.drop_table("lock_exceptions")
    op.drop_table("dimension_values")
    op.drop_index("ix_daily_balances_book_date", table_name="daily_balances")
    op.drop_table("daily_balances")
    op.drop_table("counterparty_aliases")
    op.drop_table("counterparty_accounts")
    op.drop_index(op.f("ix_check_results_run_id"), table_name="check_results")
    op.drop_table("check_results")
    op.drop_index(op.f("ix_account_balances_book_id"), table_name="account_balances")
    op.drop_table("account_balances")
    op.drop_table("transaction_types")
    op.drop_table("sequences")
    op.drop_table("lock_settings")
    op.drop_table("ledger_heads")
    op.drop_table("fiscal_periods")
    op.drop_table("dimension_types")
    op.drop_table("counterparties")
    op.drop_table("commodity_price_rules")
    op.drop_index(op.f("ix_check_runs_book_id"), table_name="check_runs")
    op.drop_table("check_runs")
    op.drop_index("uq_accounts_default_role", table_name="accounts", postgresql_where=sa.text("is_default_for_role"))
    op.drop_table("accounts")
    op.drop_index("ix_fx_rates_lookup", table_name="fx_rates")
    op.drop_table("fx_rates")
    # ### end Alembic commands ###
