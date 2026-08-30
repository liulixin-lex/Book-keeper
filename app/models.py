from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import (
    AccountType,
    ActorType,
    AIMode,
    AIProtocol,
    AIStatus,
    AIWorkflowStatus,
    AmountRole,
    ApprovalStatus,
    CategoryKind,
    DatePrecision,
    JournalStatus,
    ReasoningEffort,
    RecordStatus,
    RecordType,
    UserRole,
)


def new_id() -> str:
    return str(uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(12), nullable=False, default="CNY")


class BackupSettings(Base, TimestampMixin):
    __tablename__ = "backup_settings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default="default")
    storage_type: Mapped[str] = mapped_column(String(16), nullable=False, default="s3")
    endpoint_url: Mapped[str | None] = mapped_column(String(1024))
    region: Mapped[str] = mapped_column(String(120), nullable=False, default="us-east-1")
    bucket: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    access_key_id: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    encrypted_secret_access_key: Mapped[str | None] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(String(512), nullable=False, default="backups")
    force_path_style: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cron_expression: Mapped[str] = mapped_column(
        String(120), nullable=False, default="0 2 * * *"
    )
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    retain_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint("storage_type IN ('s3', 'r2')", name="ck_backup_storage_type"),
        CheckConstraint("retain_days >= 0", name="ck_backup_retain_days"),
        CheckConstraint("retain_count >= 0", name="ck_backup_retain_count"),
    )


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    trigger: Mapped[str] = mapped_column(String(24), nullable=False)
    active_slot: Mapped[str | None] = mapped_column(String(40), unique=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(1024))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="ck_backup_run_status"
        ),
        CheckConstraint(
            "trigger IN ('manual', 'scheduled')", name="ck_backup_run_trigger"
        ),
        Index("ix_backup_runs_started_at", "started_at"),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(24), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (Index("uq_users_username_lower", func.lower(username), unique=True),)


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    role: Mapped[UserRole] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    invited_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Base, TimestampMixin):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(String(24), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(80))
    currency: Mapped[str | None] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_account_code"),)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[CategoryKind] = mapped_column(String(24), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_category_name"),)


class Counterparty(Base, TimestampMixin):
    __tablename__ = "counterparties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    roles_json: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=lambda: ["supplier"]
    )
    expense_category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    expense_category: Mapped[Category | None] = relationship(foreign_keys=[expense_category_id])

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_counterparty_name"),)


class PaymentAccount(Base, TimestampMixin):
    __tablename__ = "payment_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    ledger_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    account_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False, default="CNY")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    records: Mapped[list[BusinessRecord]] = relationship(back_populates="project")

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_project_name"),)


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    records: Mapped[list[BusinessRecord]] = relationship(
        secondary="record_tags", back_populates="tags"
    )

    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tag_name"),)


class FxRate(Base):
    __tablename__ = "fx_rates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    base_currency: Mapped[str] = mapped_column(String(12), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(12), nullable=False)
    rate_e12: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(40), nullable=False, default="reference")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "rate_type",
            name="uq_fx_snapshot",
        ),
    )


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (UniqueConstraint("workspace_id", "sha256", name="uq_document_hash"),)


class BusinessRecord(Base, TimestampMixin):
    __tablename__ = "business_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    record_type: Mapped[RecordType] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[RecordStatus] = mapped_column(
        String(32), nullable=False, default=RecordStatus.DRAFT, index=True
    )
    accounting_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_precision: Mapped[DatePrecision] = mapped_column(String(24), nullable=False)
    service_period_start: Mapped[date | None] = mapped_column(Date)
    service_period_end: Mapped[date | None] = mapped_column(Date)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    counterparty_id: Mapped[str | None] = mapped_column(ForeignKey("counterparties.id"))
    payment_account_id: Mapped[str | None] = mapped_column(ForeignKey("payment_accounts.id"))
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("source_documents.id"))
    source_channel: Mapped[str | None] = mapped_column(String(80), index=True)
    external_id: Mapped[str | None] = mapped_column(String(240), index=True)
    business_fingerprint: Mapped[str | None] = mapped_column(String(64))
    recognition_method: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    source_locator_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by_ai_run_id: Mapped[str | None] = mapped_column(String(36))
    posted_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("journal_entries.id", use_alter=True), unique=True
    )
    reversed_by_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_records.id", use_alter=True)
    )

    amounts: Mapped[list[MoneyComponent]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        foreign_keys="MoneyComponent.record_id",
    )
    category: Mapped[Category | None] = relationship(foreign_keys=[category_id])
    counterparty: Mapped[Counterparty | None] = relationship(foreign_keys=[counterparty_id])
    created_by_user: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    project: Mapped[Project | None] = relationship(back_populates="records")
    tags: Mapped[list[Tag]] = relationship(
        secondary="record_tags", back_populates="records", order_by="Tag.name"
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "source_channel", "external_id", name="uq_record_external"
        ),
        Index("ix_records_workspace_date", "workspace_id", "accounting_date"),
        Index(
            "ix_records_workspace_business_fingerprint",
            "workspace_id",
            "business_fingerprint",
        ),
    )


class RecordTag(Base):
    __tablename__ = "record_tags"

    record_id: Mapped[str] = mapped_column(ForeignKey("business_records.id"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class MoneyComponent(Base):
    __tablename__ = "money_components"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    record_id: Mapped[str] = mapped_column(ForeignKey("business_records.id"), nullable=False)
    role: Mapped[AmountRole] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    amount_e8: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_cny_e8: Mapped[int] = mapped_column(Integer, nullable=False)
    fx_rate_id: Mapped[str | None] = mapped_column(ForeignKey("fx_rates.id"))
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_amount_text: Mapped[str | None] = mapped_column(String(100))

    record: Mapped[BusinessRecord] = relationship(
        back_populates="amounts", foreign_keys=[record_id]
    )

    __table_args__ = (
        UniqueConstraint("record_id", "role", "sequence", name="uq_record_amount_role"),
    )


class RecordLink(Base):
    __tablename__ = "record_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("business_records.id"), nullable=False)
    target_record_id: Mapped[str] = mapped_column(ForeignKey("business_records.id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    amount_cny_e8: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint(
            "source_record_id", "target_record_id", "relation_type", name="uq_record_link"
        ),
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    record_id: Mapped[str | None] = mapped_column(
        ForeignKey("business_records.id", use_alter=True), unique=True
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[JournalStatus] = mapped_column(String(24), nullable=False)
    memo: Mapped[str] = mapped_column(String(500), nullable=False)
    reversal_of_id: Mapped[str | None] = mapped_column(ForeignKey("journal_entries.id"))
    posted_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    posted_by_ai_run_id: Mapped[str | None] = mapped_column(String(36))
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lines: Mapped[list[JournalLine]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entry_id: Mapped[str] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    debit_cny_e8: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_cny_e8: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    original_currency: Mapped[str | None] = mapped_column(String(12))
    original_amount_e8: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String(500))

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")

    __table_args__ = (
        CheckConstraint("debit_cny_e8 >= 0", name="ck_line_debit_nonnegative"),
        CheckConstraint("credit_cny_e8 >= 0", name="ck_line_credit_nonnegative"),
        CheckConstraint("(debit_cny_e8 = 0) != (credit_cny_e8 = 0)", name="ck_line_one_side"),
    )


class SubscriptionContract(Base, TimestampMixin):
    __tablename__ = "subscription_contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(40), nullable=False)
    currency: Mapped[str] = mapped_column(String(12), nullable=False)
    expected_amount_e8: Mapped[int | None] = mapped_column(Integer)
    renewal_date: Mapped[date | None] = mapped_column(Date)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AIProvider(Base, TimestampMixin):
    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    protocol: Mapped[AIProtocol] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    model: Mapped[str] = mapped_column(String(240), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    api_key_source: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    reasoning_effort: Mapped[ReasoningEffort] = mapped_column(
        String(24), nullable=False, default=ReasoningEffort.MEDIUM
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    headers_json: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    capabilities_json: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(40))
    last_test_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_ai_provider_name"),
        CheckConstraint(
            "api_key_source IN ('none', 'database', 'environment')",
            name="ck_ai_provider_key_source",
        ),
    )


class AIWorkspaceSettings(Base, TimestampMixin):
    __tablename__ = "ai_workspace_settings"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    agents_md: Mapped[str] = mapped_column(Text, nullable=False)
    web_access_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    mode: Mapped[AIMode] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AIRun(Base):
    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    provider_id: Mapped[str] = mapped_column(ForeignKey("ai_providers.id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("ai_conversations.id"))
    mode: Mapped[AIMode] = mapped_column(String(16), nullable=False)
    tool_scope: Mapped[str] = mapped_column(String(32), nullable=False, default="ledger")
    status: Mapped[AIStatus] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(240), nullable=False)
    reasoning_effort: Mapped[ReasoningEffort] = mapped_column(String(24), nullable=False)
    operation: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str | None] = mapped_column(String(240))
    request_hash: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    event_log_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "created_by_id",
            "operation",
            "idempotency_key",
            name="uq_ai_run_idempotency_scope",
        ),
    )


class AIToolCall(Base):
    __tablename__ = "ai_tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("ai_runs.id"), nullable=False)
    provider_call_id: Mapped[str] = mapped_column(String(240), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("run_id", "provider_call_id", name="uq_ai_tool_call"),
        UniqueConstraint("run_id", "signature", name="uq_ai_tool_call_signature"),
    )


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        String(24), nullable=False, default=ApprovalStatus.PENDING
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    requested_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    requested_by_ai_run_id: Mapped[str | None] = mapped_column(ForeignKey("ai_runs.id"))
    decided_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(120), index=True)
    ai_run_id: Mapped[str | None] = mapped_column(ForeignKey("ai_runs.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_scope",
        ),
    )


class AIWorkflow(Base, TimestampMixin):
    __tablename__ = "ai_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("ai_providers.id"))
    command: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[AIWorkflowStatus] = mapped_column(
        String(32), nullable=False, default=AIWorkflowStatus.COLLECTING
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    canonical_hash: Mapped[str | None] = mapped_column(String(64))
    selected_proposal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    confirmed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    inputs: Mapped[list[AIWorkflowInput]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    proposals: Mapped[list[LedgerProposal]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    events: Mapped[list[AIWorkflowEvent]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_ai_workflow_scope_status", "workspace_id", "created_by_id", "status"),
    )


class AIWorkflowInput(Base):
    __tablename__ = "ai_workflow_inputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ai_workflows.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(200))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    temporary_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow: Mapped[AIWorkflow] = relationship(back_populates="inputs")
    extraction: Mapped[DocumentExtraction | None] = relationship(
        back_populates="workflow_input", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_ai_workflow_input_sequence"),
    )


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_input_id: Mapped[str] = mapped_column(
        ForeignKey("ai_workflow_inputs.id"), nullable=False, unique=True
    )
    parser: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    structure_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow_input: Mapped[AIWorkflowInput] = relationship(back_populates="extraction")


class LedgerProposal(Base, TimestampMixin):
    __tablename__ = "ledger_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ai_workflows.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    record_type: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    journal_preview_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    duplicate_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    entity_versions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    canonical_hash: Mapped[str | None] = mapped_column(String(64))
    committed_record_id: Mapped[str | None] = mapped_column(ForeignKey("business_records.id"))
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approval_requests.id"))

    workflow: Mapped[AIWorkflow] = relationship(back_populates="proposals")

    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_ledger_proposal_sequence"),
    )


class AIWorkflowEvent(Base):
    __tablename__ = "ai_workflow_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("ai_workflows.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow: Mapped[AIWorkflow] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_ai_workflow_event_sequence"),
    )


class AIPluginState(Base, TimestampMixin):
    __tablename__ = "ai_plugin_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    plugin_id: Mapped[str] = mapped_column(String(160), nullable=False)
    plugin_version: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy")
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (UniqueConstraint("workspace_id", "plugin_id", name="uq_ai_plugin_state"),)


class AIEmbeddingProvider(Base, TimestampMixin):
    __tablename__ = "ai_embedding_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    model: Mapped[str] = mapped_column(String(240), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text)
    api_key_source: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=32)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    index_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pending_index_version: Mapped[int | None] = mapped_column(Integer)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(40))
    last_test_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_ai_embedding_provider_name"),
        CheckConstraint("dimension > 0", name="ck_ai_embedding_dimension_positive"),
        CheckConstraint("batch_size > 0", name="ck_ai_embedding_batch_positive"),
        CheckConstraint(
            "api_key_source IN ('none', 'database', 'environment')",
            name="ck_ai_embedding_provider_key_source",
        ),
    )


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    acl_scope: Mapped[str] = mapped_column(String(40), nullable=False, default="workspace")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "entity_type", "entity_id", name="uq_knowledge_document_entity"
        ),
        Index("ix_knowledge_document_scope", "workspace_id", "entity_type", "deleted_at"),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    embedding_index_version: Mapped[int | None] = mapped_column(Integer)
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunk_index"),
    )


class KnowledgeIndexJob(Base, TimestampMixin):
    __tablename__ = "knowledge_index_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    target_index_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_knowledge_job_queue", "status", "available_at", "created_at"),)
