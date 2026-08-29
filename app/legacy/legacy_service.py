from __future__ import annotations

import mimetypes
from contextlib import nullcontext
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.enums import ActorType, DatePrecision, RecordType
from app.legacy.legacy import extract_legacy_workbooks
from app.legacy.types import LegacyRecord
from app.models import BusinessRecord, Category, Counterparty, SourceDocument, Workspace
from app.schemas import ExpenseCreate, IncomeCreate, MoneyInput, TopupCreate
from app.services.accounting import create_expense, create_income, create_topup
from app.services.seed import seed_defaults


class LegacyMigrationResult(BaseModel):
    extracted: int
    created: int
    skipped: int
    failed: int
    by_source: dict[str, int]
    gross_revenue: str
    channel_fees: str
    net_revenue: str
    operating_expenses: str
    cash_expenses: str
    errors: list[str]


CATEGORY_MAP = {
    "account_purchase": "账号采购",
    "subscription": "软件订阅",
    "other_expense": "其他支出",
    "cloud_service": "云服务",
    "upstream_recharge": "上游采购",
}


def _decimal_total(records: tuple[LegacyRecord, ...], field: str) -> str:
    total = sum((Decimal(getattr(record, field) or "0") for record in records), Decimal("0"))
    return format(total, "f")


def _category(session: Session, workspace_id: str, record: LegacyRecord) -> Category:
    if record.record_type == "income":
        name = "主营业务收入"
    elif record.status == "退款" or record.operating_amount_cny.startswith("-"):
        name = "其他业务收入"
    else:
        name = CATEGORY_MAP[record.category]
    category = session.scalar(
        select(Category).where(Category.workspace_id == workspace_id, Category.name == name)
    )
    if category is None:
        raise RuntimeError(f"Seeded category not found: {name}")
    return category


def _counterparty(
    session: Session,
    workspace_id: str,
    name: str | None,
    expense_category_id: str,
) -> Counterparty | None:
    if not name:
        return None
    existing = session.scalar(
        select(Counterparty).where(
            Counterparty.workspace_id == workspace_id, Counterparty.name == name
        )
    )
    if existing:
        if existing.expense_category_id is None:
            existing.expense_category_id = expense_category_id
        return existing
    item = Counterparty(
        workspace_id=workspace_id,
        name=name,
        roles_json=["supplier"],
        expense_category_id=expense_category_id,
        metadata_json={},
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _occurred_at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(get_settings().timezone))
    return parsed.astimezone(UTC)


def _precision(value: str) -> DatePrecision:
    return {
        "second": DatePrecision.TIMESTAMP,
        "date": DatePrecision.DAY,
        "month": DatePrecision.MONTH,
    }[value]


def _service_period(value: str | None) -> tuple[date | None, date | None]:
    if not value:
        return None, None
    year, month = (int(part) for part in value.split("-", 1))
    start = date(year, month, 1)
    if month == 12:
        following = date(year + 1, 1, 1)
    else:
        following = date(year, month + 1, 1)
    return start, date.fromordinal(following.toordinal() - 1)


def _locator(record: LegacyRecord) -> dict:
    return {
        "migration_fingerprint": record.fingerprint,
        "business_fingerprint": record.business_fingerprint,
        "source_fingerprint": record.source_fingerprint,
        "evidence": [asdict(item) for item in record.evidence],
    }


def _dedup_identity(record: LegacyRecord) -> tuple[str, str]:
    if record.record_type == "upstream_recharge":
        return record.counterparty or "未知站点", record.fingerprint
    trusted = record.source_system in {"stripe", "liandong", "account_purchase"}
    if trusted and record.external_id:
        return record.source_system, record.external_id
    return f"legacy:{record.source_system}", record.fingerprint


def _source_documents(
    session: Session, workspace_id: str, root: Path, source_hashes: dict[str, str]
) -> dict[str, SourceDocument]:
    documents: dict[str, SourceDocument] = {}
    for relative, digest in source_hashes.items():
        existing = session.scalar(
            select(SourceDocument).where(
                SourceDocument.workspace_id == workspace_id,
                SourceDocument.sha256 == digest,
            )
        )
        if existing is None:
            path = root / relative
            existing = SourceDocument(
                workspace_id=workspace_id,
                filename=path.name,
                mime_type=mimetypes.guess_type(path.name)[0]
                or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                sha256=digest,
                storage_path=str(path.resolve()),
                size_bytes=path.stat().st_size,
            )
            session.add(existing)
            session.commit()
            session.refresh(existing)
        documents[relative] = existing
    return documents


def _migrate_one(
    session: Session,
    workspace_id: str,
    workspace: Workspace,
    record: LegacyRecord,
    documents: dict[str, SourceDocument],
) -> bool:
    source_channel, external_id = _dedup_identity(record)
    duplicate = session.scalar(
        select(BusinessRecord.id).where(
            BusinessRecord.workspace_id == workspace_id,
            BusinessRecord.source_channel == source_channel,
            BusinessRecord.external_id == external_id,
        )
    )
    if duplicate:
        return False
    category = _category(session, workspace_id, record)
    provider_category = (
        category
        if str(category.kind) == "expense"
        else session.scalar(
            select(Category).where(
                Category.workspace_id == workspace_id,
                Category.name == "其他支出",
            )
        )
    )
    if provider_category is None:
        raise RuntimeError("Seeded category not found: 其他支出")
    counterparty = _counterparty(
        session,
        workspace_id,
        record.counterparty,
        provider_category.id,
    )
    source_file = record.evidence[0].source.file
    source_document = documents[source_file]
    metadata = {
        **record.metadata,
        "legacy_status": record.status,
        "legacy_external_id": record.external_id,
        "migration_fingerprint": record.fingerprint,
    }
    accounting_date = date.fromisoformat(record.accounting_date)

    if record.record_type == "income":
        fee_currency = str(record.metadata.get("fee_currency") or record.currency)
        original_fee = str(record.metadata.get("original_fee") or "0")
        income_payload = IncomeCreate(
            accounting_date=accounting_date,
            occurred_at=_occurred_at(record.occurred_at),
            date_precision=_precision(record.date_precision),
            description=record.description,
            channel=source_channel,
            external_id=external_id,
            gross=MoneyInput(
                currency=record.currency,
                amount=record.original_amount,
                amount_cny=record.gross_amount_cny,
                fx_rate=record.fx_rate,
            ),
            fee=MoneyInput(
                currency=fee_currency,
                amount=original_fee,
                amount_cny=record.fee_amount_cny or "0",
            ),
            cash_received=True,
            category_id=category.id,
            counterparty_id=counterparty.id if counterparty else None,
            recognition_method=record.recognition_method or "transaction",
            note=record.notes,
            source_locator=_locator(record),
            metadata=metadata,
        )
        created = create_income(
            session,
            workspace,
            income_payload,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    elif record.record_type == "upstream_recharge":
        topup_payload = TopupCreate(
            accounting_date=accounting_date,
            occurred_at=_occurred_at(record.occurred_at),
            upstream_name=record.counterparty or "未知站点",
            amount_cny=record.operating_amount_cny,
            external_id=external_id,
            note=record.notes,
            source_locator=_locator(record),
            metadata=metadata,
        )
        created = create_topup(
            session,
            workspace,
            topup_payload,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
        )
    else:
        period_start, period_end = _service_period(record.service_period)
        cash_original = str(record.metadata.get("cash_original") or record.original_amount)
        is_expense_credit = record.status == "退款" or record.operating_amount_cny.startswith("-")
        if is_expense_credit:
            refund_amount = abs(Decimal(cash_original))
            refund_cny = abs(Decimal(record.cash_amount_cny))
            created = create_income(
                session,
                workspace,
                IncomeCreate(
                    accounting_date=accounting_date,
                    occurred_at=_occurred_at(record.occurred_at),
                    date_precision=_precision(record.date_precision),
                    description=record.description,
                    channel=source_channel,
                    external_id=external_id,
                    gross=MoneyInput(
                        currency=record.currency,
                        amount=format(refund_amount, "f"),
                        amount_cny=format(refund_cny, "f"),
                        fx_rate=record.fx_rate,
                    ),
                    category_id=category.id,
                    counterparty_id=counterparty.id if counterparty else None,
                    recognition_method="expense_refund",
                    note=record.notes,
                    source_locator=_locator(record),
                    metadata={
                        **metadata,
                        "normalized_from_record_type": "adjustment",
                        "normalized_as": "expense_refund_income",
                    },
                ),
                actor_type=ActorType.SYSTEM,
                actor_id=None,
            )
            created.business_fingerprint = record.business_fingerprint
            created.source_document_id = source_document.id
            session.commit()
            return True

        normalized_metadata = {
            **metadata,
            "legacy_operating_amount_cny": record.operating_amount_cny,
            "unreconciled_difference_cny": "0",
        }
        expense_payload = ExpenseCreate(
            accounting_date=accounting_date,
            occurred_at=_occurred_at(record.occurred_at),
            date_precision=_precision(record.date_precision),
            description=record.description,
            cost=MoneyInput(
                currency=record.currency,
                amount=cash_original,
                amount_cny=record.cash_amount_cny,
                fx_rate=record.fx_rate,
            ),
            cash=MoneyInput(
                currency=record.currency,
                amount=cash_original,
                amount_cny=record.cash_amount_cny,
                fx_rate=record.fx_rate,
            ),
            category_id=category.id,
            counterparty_id=counterparty.id if counterparty else None,
            source_channel=source_channel,
            external_id=external_id,
            service_period_start=period_start,
            service_period_end=period_end,
            note=record.notes,
            source_locator=_locator(record),
            metadata=normalized_metadata,
        )
        created = create_expense(
            session,
            workspace,
            expense_payload,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            record_type=RecordType.EXPENSE,
        )
    created.business_fingerprint = record.business_fingerprint
    created.source_document_id = source_document.id
    session.commit()
    return True


def migrate_legacy_workbooks(
    source_root: str | Path, *, session: Session | None = None
) -> LegacyMigrationResult:
    root = Path(source_root).resolve()
    extraction = extract_legacy_workbooks(root)
    manager = nullcontext(session) if session is not None else SessionLocal()
    created = 0
    skipped = 0
    failed = 0
    errors: list[str] = []
    by_source: dict[str, int] = {}
    with manager as db:
        assert db is not None
        workspace = seed_defaults(db)
        documents = _source_documents(db, workspace.id, root, extraction.source_hashes)
        for item in extraction.records:
            by_source[item.source_system] = by_source.get(item.source_system, 0) + 1
            try:
                if _migrate_one(db, workspace.id, workspace, item, documents):
                    created += 1
                else:
                    skipped += 1
            except Exception as exc:
                db.rollback()
                failed += 1
                errors.append(f"{item.source_system}/{item.fingerprint[:12]}: {exc}")

    income = tuple(item for item in extraction.records if item.record_type == "income")
    refunds = tuple(
        item
        for item in extraction.records
        if item.status == "退款" or item.operating_amount_cny.startswith("-")
    )
    expenses = tuple(
        item for item in extraction.records if item.record_type != "income" and item not in refunds
    )
    gross_revenue = sum(
        (Decimal(item.gross_amount_cny or "0") for item in income), Decimal("0")
    ) + sum((abs(Decimal(item.cash_amount_cny)) for item in refunds), Decimal("0"))
    channel_fees = sum((Decimal(item.fee_amount_cny or "0") for item in income), Decimal("0"))
    cash_expenses = sum((Decimal(item.cash_amount_cny) for item in expenses), Decimal("0"))
    return LegacyMigrationResult(
        extracted=len(extraction.records),
        created=created,
        skipped=skipped,
        failed=failed,
        by_source=by_source,
        gross_revenue=format(gross_revenue, "f"),
        channel_fees=format(channel_fees, "f"),
        net_revenue=format(gross_revenue - channel_fees, "f"),
        operating_expenses=format(cash_expenses, "f"),
        cash_expenses=format(cash_expenses, "f"),
        errors=errors,
    )
