"""ORM models (docs/04-data-model.md): identity, books, audit, jobs, files, ledger, imports, legacy, OAuth."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bookkeeper.db.base import TZ, Base, Timestamps, Versioned

JSON = JSONB(none_as_null=True)


class User(Base, Timestamps, Versioned):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(TZ)
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_secret: Mapped[str] = mapped_column(Text, nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)


class Commodity(Base):
    __tablename__ = "commodities"
    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    scale: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('fiat','credit','other')", name="kind"),
        CheckConstraint("scale BETWEEN 0 AND 8", name="scale"),
        CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{1,11}$'", name="code_format"),
    )


class Book(Base, Timestamps, Versioned):
    __tablename__ = "books"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Shanghai", nullable=False)
    rounding_mode: Mapped[str] = mapped_column(Text, server_default="half_up", nullable=False)
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, server_default="1", nullable=False)
    journal_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("ARRAY['记']::text[]"), nullable=False
    )
    rounding_tolerance_per_line: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    fx_lookback_days: Mapped[int] = mapped_column(SmallInteger, server_default="7", nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="active", nullable=False)
    __table_args__ = (
        CheckConstraint("rounding_mode IN ('half_up','half_even')", name="rounding_mode"),
        CheckConstraint("status IN ('active','archived')", name="status"),
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fy_month"),
    )


class BookMember(Base):
    __tablename__ = "book_members"
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("role IN ('viewer','accountant','admin','owner')", name="role"),)


class ApiToken(Base, Versioned):
    __tablename__ = "api_tokens"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    token_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    preset: Mapped[str] = mapped_column(Text, nullable=False)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    ip_allowlist: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, server_default="120", nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(TZ)
    last_used_at: Mapped[datetime | None] = mapped_column(TZ)
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("preset IN ('reader','bookkeeper','admin','custom')", name="preset"),)


class AuditHead(Base):
    """Head of each audit hash chain; scope = book id or 'global'."""

    __tablename__ = "audit_heads"
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)


class ChangeSet(Base):
    __tablename__ = "change_sets"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"), index=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    token_id: Mapped[str | None] = mapped_column(ForeignKey("api_tokens.id"))
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    mcp_client: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    entity_counts: Mapped[dict[str, int]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="applied", nullable=False)
    reverts_change_set_id: Mapped[str | None] = mapped_column(ForeignKey("change_sets.id"))
    reverted_by_change_set_id: Mapped[str | None] = mapped_column(ForeignKey("change_sets.id"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('applied','reverted','partially_reverted')", name="status"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"))
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str | None] = mapped_column(Text)
    token_id: Mapped[str | None] = mapped_column(Text)
    mcp_client: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    change_set_id: Mapped[str | None] = mapped_column(Text, index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    diff: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    __table_args__ = (
        UniqueConstraint("scope", "seq"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_book_occurred", "book_id", "occurred_at"),
        CheckConstraint("actor_type IN ('user','token','system','migration')", name="actor_type"),
        CheckConstraint(
            "channel IN ('ui','api','mcp','import','worker','cli','migration','system')",
            name="channel",
        ),
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_key: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False, index=True)
    __table_args__ = (CheckConstraint("status IN ('in_progress','completed')", name="status"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"), index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="queued", nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="100", nullable=False)
    run_after: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="5", nullable=False)
    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(TZ)
    heartbeat_at: Mapped[datetime | None] = mapped_column(TZ)
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text)
    change_set_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name="status"),
        Index(
            "ix_jobs_queue",
            "priority",
            "run_after",
            postgresql_where=text("status = 'queued'"),
        ),
    )


class JobSchedule(Base):
    __tablename__ = "job_schedules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    schedule: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Shanghai", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(TZ)
    last_job_id: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("kind", "book_id", postgresql_nulls_not_distinct=True),)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(Text, primary_key=True)
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    beat_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


class StoredFile(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    token_id: Mapped[str | None] = mapped_column(ForeignKey("api_tokens.id"))
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("book_id", "sha256"),)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    detached_at: Mapped[datetime | None] = mapped_column(TZ)
    __table_args__ = (
        Index("ix_attachments_entity", "entity_type", "entity_id"),
        CheckConstraint(
            "role IN ('receipt','invoice','statement','screenshot','order_export','contract','other')",
            name="role",
        ),
    )


# ---------------------------------------------------------------- M1: reference data


RATE = Numeric(28, 12)
QUANTITY = Numeric(28, 8)


class CommodityPriceRule(Base):
    __tablename__ = "commodity_price_rules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    quote_commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("purpose IN ('nominal_valuation','conversion')", name="purpose"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="range"),
        CheckConstraint("commodity <> quote_commodity", name="distinct"),
    )


class FxRate(Base):
    __tablename__ = "fx_rates"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    base: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    quote: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    rate_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[Any] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        UniqueConstraint("base", "quote", "rate_date", "rate_type", "source"),
        Index("ix_fx_rates_lookup", "base", "quote", "rate_date"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base <> quote", name="distinct"),
        CheckConstraint("rate_type IN ('reference','actual','derived','manual')", name="rate_type"),
    )


class Account(Base, Timestamps, Versioned):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    level: Mapped[int] = mapped_column(SmallInteger, server_default="1", nullable=False)
    is_group: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    classification: Mapped[str] = mapped_column(Text, nullable=False)
    normal_side: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str | None] = mapped_column(Text)
    is_default_for_role: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    allowed_commodities: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    open_date: Mapped[date | None] = mapped_column(Date)
    close_date: Mapped[date | None] = mapped_column(Date)
    balance_rule: Mapped[str] = mapped_column(Text, server_default="any", nullable=False)
    manual_entry_allowed: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    required_dimensions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    forbidden_dimensions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    standard_code: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("book_id", "code"),
        UniqueConstraint("book_id", "id"),
        Index(
            "uq_accounts_default_role",
            "book_id",
            "role",
            unique=True,
            postgresql_where=text("is_default_for_role"),
        ),
        CheckConstraint(r"code ~ '^[0-9]{4}(\.[0-9]{2})*$'", name="code_format"),
        CheckConstraint(
            "classification IN ('asset','liability','equity','revenue','expense')",
            name="classification",
        ),
        CheckConstraint("normal_side IN ('debit','credit')", name="normal_side"),
        CheckConstraint("balance_rule IN ('any','normal_side_only')", name="balance_rule"),
        CheckConstraint("close_date IS NULL OR open_date IS NULL OR close_date >= open_date", name="dates"),
    )


class DimensionType(Base, Versioned):
    __tablename__ = "dimension_types"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_hierarchical: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "code"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,31}$'", name="code_format"),
    )


class DimensionValue(Base, Versioned):
    __tablename__ = "dimension_values"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    type_id: Mapped[str] = mapped_column(ForeignKey("dimension_types.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("dimension_values.id"))
    counterparty_id: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("type_id", "code"),
        CheckConstraint("code ~ '^[a-z0-9][a-z0-9_]{0,47}$'", name="code_format"),
    )


class Counterparty(Base, Timestamps, Versioned):
    __tablename__ = "counterparties"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False)
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False)
    default_transaction_type_id: Mapped[str | None] = mapped_column(Text)
    default_dimensions: Mapped[dict[str, str]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, server_default=text("'{}'::jsonb"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "name"),
        CheckConstraint(
            "category IN ('upstream_site','ai_vendor','cloud_vendor','marketplace',"
            "'payment_provider','marketing_vendor','business_service','customer','other')",
            name="category",
        ),
    )


class CounterpartyAlias(Base):
    __tablename__ = "counterparty_aliases"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="100", nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "match_type", "pattern"),
        CheckConstraint("match_type IN ('exact','contains','regex','domain')", name="match_type"),
    )


class CounterpartyAccount(Base, Versioned):
    __tablename__ = "counterparty_accounts"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    identifier: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("counterparty_id", "label"),)


class TransactionType(Base, Versioned):
    __tablename__ = "transaction_types"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "code"),
        CheckConstraint("category IN ('income','expense','transfer','adjustment','other')", name="category"),
    )


# ---------------------------------------------------------------- M1: transactions & ledger


class Transaction(Base, Timestamps, Versioned):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    number: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_type_id: Mapped[str] = mapped_column(ForeignKey("transaction_types.id"), nullable=False)
    template_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="posted", nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(TZ)
    occurred_offset_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    date_precision: Mapped[str] = mapped_column(Text, server_default="day", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    counterparty_id: Mapped[str | None] = mapped_column(ForeignKey("counterparties.id"))
    counterparty_account_id: Mapped[str | None] = mapped_column(ForeignKey("counterparty_accounts.id"))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    computed: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    default_dimensions: Mapped[dict[str, str]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(Text)
    order_no: Mapped[str | None] = mapped_column(Text, index=True)
    is_estimate: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    created_channel: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    created_token_id: Mapped[str | None] = mapped_column(Text)
    mcp_client: Mapped[str | None] = mapped_column(Text)
    created_change_set_id: Mapped[str | None] = mapped_column(Text)
    posted_entry_id: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(TZ)
    posted_by: Mapped[str | None] = mapped_column(Text)
    reversed_at: Mapped[datetime | None] = mapped_column(TZ)
    reverse_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, server_default=text("'{}'::jsonb"), nullable=False
    )
    __table_args__ = (
        UniqueConstraint("book_id", "number"),
        Index(
            "uq_transactions_external_ref",
            "book_id",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index("ix_transactions_book_date", "book_id", "effective_date"),
        Index("ix_transactions_book_status", "book_id", "status"),
        Index("ix_transactions_book_counterparty", "book_id", "counterparty_id", "effective_date"),
        Index("ix_transactions_channel", "book_id", text("(default_dimensions ->> 'channel')")),
        CheckConstraint("status IN ('posted','reversed')", name="status"),
        CheckConstraint("date_precision IN ('timestamp','day','month')", name="date_precision"),
        CheckConstraint(
            "created_channel IN ('ui','api','mcp','import','system','migration','cli')",
            name="created_channel",
        ),
    )


class LedgerHead(Base):
    __tablename__ = "ledger_heads"
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_entry_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)


class NumberSequence(Base):
    __tablename__ = "sequences"
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    period: Mapped[str] = mapped_column(Text, primary_key=True)
    next_value: Mapped[int] = mapped_column(BigInteger, nullable=False)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    journal_code: Mapped[str] = mapped_column(Text, nullable=False)
    number: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    template_id: Mapped[str | None] = mapped_column(Text)
    fee_rule_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reverses_entry_id: Mapped[str | None] = mapped_column(ForeignKey("journal_entries.id"))
    reversed_by_entry_id: Mapped[str | None] = mapped_column(ForeignKey("journal_entries.id"))
    attachment_count: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    line_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    created_token_id: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    change_set_id: Mapped[str | None] = mapped_column(Text)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "seq"),
        UniqueConstraint("book_id", "number"),
        UniqueConstraint("book_id", "id"),
        Index("ix_journal_entries_transaction", "transaction_id"),
        Index("ix_journal_entries_book_date", "book_id", "effective_date"),
        CheckConstraint("kind IN ('posting','reversal','repost_reversal','repost','adjustment')", name="kind"),
        CheckConstraint("line_count >= 2", name="line_count"),
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(Text, nullable=False)
    entry_id: Mapped[str] = mapped_column(Text, nullable=False)
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(Text, nullable=False)
    commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column(RATE)
    fx_rate_id: Mapped[str | None] = mapped_column(Text)
    fx_source: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    quantity_unit: Mapped[str | None] = mapped_column(Text)
    counterparty_id: Mapped[str | None] = mapped_column(ForeignKey("counterparties.id"))
    counterparty_account_id: Mapped[str | None] = mapped_column(ForeignKey("counterparty_accounts.id"))
    memo: Mapped[str | None] = mapped_column(Text)
    line_role: Mapped[str] = mapped_column(Text, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    base_balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["book_id", "entry_id"], ["journal_entries.book_id", "journal_entries.id"]),
        ForeignKeyConstraint(["book_id", "account_id"], ["accounts.book_id", "accounts.id"]),
        UniqueConstraint("entry_id", "line_no"),
        UniqueConstraint("account_id", "commodity", "account_seq"),
        Index("ix_journal_lines_account_date", "book_id", "account_id", "effective_date"),
        Index("ix_journal_lines_book_date", "book_id", "effective_date"),
        Index("ix_journal_lines_entry", "entry_id"),
        Index("ix_journal_lines_counterparty", "book_id", "counterparty_id", "effective_date"),
        CheckConstraint(
            "amount <> 0 OR (base_amount <> 0 AND line_role IN ('rounding','fx_realization','revaluation','closing'))",
            name="base_only_roles",
        ),
        CheckConstraint("(quantity IS NULL) = (quantity_unit IS NULL)", name="quantity_unit"),
    )


class JournalLineDimension(Base):
    __tablename__ = "journal_line_dimensions"
    line_id: Mapped[str] = mapped_column(ForeignKey("journal_lines.id"), primary_key=True)
    dimension_type_id: Mapped[str] = mapped_column(ForeignKey("dimension_types.id"), primary_key=True)
    dimension_value_id: Mapped[str] = mapped_column(ForeignKey("dimension_values.id"), nullable=False, index=True)
    book_id: Mapped[str] = mapped_column(Text, nullable=False)


class AccountBalance(Base):
    __tablename__ = "account_balances"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), primary_key=True)
    book_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    balance: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    base_balance: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    debit_total: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    credit_total: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    base_debit_total: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    base_credit_total: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    line_count: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)


class DailyBalance(Base):
    """Per-day activity by business date. Balance at D = Σ activity up to D (no cascades)."""

    __tablename__ = "daily_balances"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), primary_key=True)
    commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    book_id: Mapped[str] = mapped_column(Text, nullable=False)
    debit: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    credit: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    base_debit: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    base_credit: Mapped[int] = mapped_column(BigInteger, server_default="0", nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    __table_args__ = (Index("ix_daily_balances_book_date", "book_id", "date"),)


# ---------------------------------------------------------------- M1: health checks


class CheckRun(Base):
    __tablename__ = "check_runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("trigger IN ('scheduled','manual','period_close','post_migration')", name="trigger"),
        CheckConstraint("status IN ('running','passed','failed')", name="status"),
    )


class CheckResult(Base):
    __tablename__ = "check_results"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("check_runs.id"), nullable=False, index=True)
    check_code: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Any] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint("severity IN ('error','warning','info')", name="severity"),
        CheckConstraint("status IN ('pass','fail','skip')", name="status"),
    )


# ---------------------------------------------------------------- M2: fee rules, links


class FeeRuleRow(Base):
    __tablename__ = "fee_rules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    fixed_minor: Mapped[int | None] = mapped_column(BigInteger)
    min_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_minor: Mapped[int | None] = mapped_column(BigInteger)
    commodity: Mapped[str | None] = mapped_column(Text, ForeignKey("commodities.code"))
    transaction_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    channel_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False)
    counterparty_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="0", nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_estimate: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="active", nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "code", "version"),
        CheckConstraint(
            "(rate IS NOT NULL OR fixed_minor IS NOT NULL) AND (rate IS NULL OR (rate >= 0 AND rate < 1)) "
            "AND (fixed_minor IS NULL OR fixed_minor >= 0)",
            name="amount",
        ),
        CheckConstraint(
            "commodity IS NOT NULL OR (fixed_minor IS NULL AND min_minor IS NULL AND max_minor IS NULL)",
            name="commodity",
        ),
        CheckConstraint("min_minor IS NULL OR max_minor IS NULL OR min_minor <= max_minor", name="bounds"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="range"),
        CheckConstraint("status IN ('active','retired')", name="status"),
    )


class TransactionLink(Base):
    __tablename__ = "transaction_links"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    from_transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), nullable=False, index=True)
    to_transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("from_transaction_id", "to_transaction_id", "kind"),
        CheckConstraint("kind IN ('refund_of','related')", name="kind"),
        CheckConstraint("from_transaction_id <> to_transaction_id", name="distinct"),
    )


# ------------------------------------------------------------------ M3: MCP call log, rate limits


class McpCall(Base):
    __tablename__ = "mcp_calls"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"))
    token_id: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    client: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str | None] = mapped_column(Text)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_code: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    change_set_id: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        Index("ix_mcp_calls_book_created", "book_id", "created_at"),
        Index("ix_mcp_calls_token_created", "token_id", "created_at"),
    )


class RateCounter(Base):
    """Fixed-window request counters shared by all processes."""

    __tablename__ = "rate_counters"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(TZ, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)


# ------------------------------------------------------------------ M4: import, rules, matching


class ImportSource(Base, Versioned):
    """Where records come from (a wallet bill, a card shop, an upstream site) and how to read them."""

    __tablename__ = "import_sources"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Shanghai", nullable=False)
    watermark_at: Mapped[datetime | None] = mapped_column(TZ)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "code"),
        CheckConstraint(
            "kind IN ('wechat_bill','alipay_bill','stripe_balance','card_shop_orders','upstream_usage_log',"
            "'generic_tabular','records','redeem_page','ai_extract')",
            name="kind",
        ),
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("import_sources.id"), nullable=False, index=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("files.id"))
    parser: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="parsed", nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(TZ)
    commit_change_set_id: Mapped[str | None] = mapped_column(Text)
    reverted_at: Mapped[datetime | None] = mapped_column(TZ)
    __table_args__ = (
        CheckConstraint("status IN ('extracting','failed','parsed','committed','reverted')", name="status"),
        Index("ix_import_batches_book_created", "book_id", "created_at"),
    )


class SourceRecord(Base, Versioned):
    __tablename__ = "source_records"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    source_id: Mapped[str] = mapped_column(ForeignKey("import_sources.id"), nullable=False)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), nullable=False, index=True)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commodity: Mapped[str] = mapped_column(ForeignKey("commodities.code"), nullable=False)
    fee_minor: Mapped[int | None] = mapped_column(BigInteger)
    balance_after_minor: Mapped[int | None] = mapped_column(BigInteger)
    counterparty_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    order_no: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    status_text: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="new", nullable=False)
    duplicate_of: Mapped[str | None] = mapped_column(Text)
    ignore_reason: Mapped[str | None] = mapped_column(Text)
    classification: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    rule_trace: Mapped[list[Any]] = mapped_column(JSON, server_default=text("'[]'::jsonb"), nullable=False)
    locked_fields: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False)
    paired_with: Mapped[str | None] = mapped_column(Text)
    transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        Index(
            "uq_source_records_external",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text(
                "external_id IS NOT NULL AND status <> 'duplicate' AND ignore_reason IS DISTINCT FROM 'batch_reverted'"
            ),
        ),
        Index(
            "uq_source_records_fingerprint",
            "source_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status <> 'duplicate' AND ignore_reason IS DISTINCT FROM 'batch_reverted'"),
        ),
        Index("ix_source_records_book_status", "book_id", "status", "effective_date"),
        CheckConstraint("direction IN ('in','out','neutral')", name="direction"),
        CheckConstraint("status IN ('new','classified','duplicate','ignored','matched','booked')", name="status"),
        CheckConstraint("amount_minor >= 0", name="amount_positive"),
    )


class TransactionSource(Base):
    __tablename__ = "transaction_sources"
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("role IN ('primary','evidence','settlement','counterpart')", name="role"),)


class Rule(Base, Versioned):
    __tablename__ = "rules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, server_default="classify", nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="100", nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actions: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    stop_processing: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    last_hit_at: Mapped[datetime | None] = mapped_column(TZ)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("book_id", "code"),
        CheckConstraint("stage IN ('normalize','classify','enrich')", name="stage"),
    )


class PairingRule(Base, Versioned):
    __tablename__ = "pairing_rules"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("book_id", "code"),)


class MatchSuggestion(Base):
    __tablename__ = "match_suggestions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[str] = mapped_column(ForeignKey("source_records.id"), nullable=False, index=True)
    other_record_id: Mapped[str | None] = mapped_column(ForeignKey("source_records.id"), index=True)
    transaction_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"), index=True)
    pairing_rule_id: Mapped[str | None] = mapped_column(Text)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSON, server_default=text("'{}'::jsonb"), nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="pending", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('record_transaction','record_record','duplicate')", name="kind"),
        CheckConstraint("status IN ('pending','accepted','auto_accepted','rejected','superseded')", name="status"),
        Index("ix_match_suggestions_book_status", "book_id", "status"),
    )


class MatchExclusion(Base):
    """A pair the user said does not belong together; never suggested again."""

    __tablename__ = "match_exclusions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    left_id: Mapped[str] = mapped_column(Text, nullable=False)
    right_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("book_id", "left_id", "right_id"),)


# ------------------------------------------------------------------ M5: legacy migration


class LegacyMap(Base):
    """Which v2 entity each v1 row became (docs/11 V1)."""

    __tablename__ = "legacy_map"
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), primary_key=True)
    legacy_table: Mapped[str] = mapped_column(Text, primary_key=True)
    legacy_id: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_legacy_map_entity", "entity_type", "entity_id"),)


class LegacyArchive(Base):
    """v1 rows kept verbatim for reference (journal, audit trail, documents)."""

    __tablename__ = "legacy_archive"
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), primary_key=True)
    legacy_table: Mapped[str] = mapped_column(Text, primary_key=True)
    legacy_id: Mapped[str] = mapped_column(Text, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ------------------------------------------------------------------ M6: OAuth 2.1 for remote MCP clients


class OAuthClient(Base):
    """Dynamically registered client (RFC 7591); the secret, if any, is stored as a SHA-256 hash."""

    __tablename__ = "oauth_clients"
    client_id: Mapped[str] = mapped_column(Text, primary_key=True)
    secret_hash: Mapped[str | None] = mapped_column(String(64))
    client_name: Mapped[str | None] = mapped_column(Text)
    registration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    registered_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TZ)


class OAuthRequest(Base):
    """An authorization request waiting for the user to sign in and consent (10 minutes)."""

    __tablename__ = "oauth_requests"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    csrf: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)


class OAuthCode(Base):
    """Authorization code: hashed, single use, bound to client, redirect URI and PKCE challenge."""

    __tablename__ = "oauth_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    preset: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("preset IN ('reader','bookkeeper','admin')", name="preset"),)


class OAuthRefreshToken(Base):
    """Refresh token (hashed); every use rotates it and replaces the API token it stands for."""

    __tablename__ = "oauth_refresh_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    family_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)  # one sign-in; replay revokes all
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.client_id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    preset: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text)
    api_token_id: Mapped[str] = mapped_column(ForeignKey("api_tokens.id"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(TZ)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("preset IN ('reader','bookkeeper','admin')", name="preset"),)


# ------------------------------------------------------------------ tags


class Tag(Base):
    """Free-form label for cross-cutting grouping (campaigns, projects, “to reimburse”)."""

    __tablename__ = "tags"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint("book_id", "name"),)


class TransactionTag(Base):
    """Tags annotate transactions; changing them never touches the ledger, so posted ones can be tagged."""

    __tablename__ = "transaction_tags"
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZ, server_default=func.now(), nullable=False)
    __table_args__ = (Index("ix_transaction_tags_tag", "tag_id"),)
