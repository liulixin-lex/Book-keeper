from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from app.amounts import as_decimal, convert_e8, to_e8, to_e12
from app.enums import (
    ActorType,
    AmountRole,
    CategoryKind,
    DatePrecision,
    JournalStatus,
    RecordStatus,
    RecordType,
)
from app.models import (
    Account,
    ApprovalRequest,
    AuditEvent,
    BusinessRecord,
    Category,
    Counterparty,
    FxRate,
    JournalEntry,
    JournalLine,
    KnowledgeIndexJob,
    MoneyComponent,
    PaymentAccount,
    RecordLink,
    RecordTag,
    Workspace,
)
from app.schemas import ExpenseCreate, IncomeCreate, MoneyInput, RefundCreate, TopupCreate


class AccountingError(ValueError):
    pass


class DuplicateRecordError(AccountingError):
    pass


@dataclass(frozen=True)
class ResolvedMoney:
    currency: str
    amount_e8: int
    amount_cny_e8: int
    fx_rate_id: str | None
    raw_amount_text: str


def account_by_code(session: Session, workspace_id: str, code: str) -> Account:
    account = session.scalar(
        select(Account).where(Account.workspace_id == workspace_id, Account.code == code)
    )
    if account is None:
        raise AccountingError(f"Missing seeded account {code}")
    return account


def category_by_name(session: Session, workspace_id: str, name: str) -> Category:
    category = session.scalar(
        select(Category).where(
            Category.workspace_id == workspace_id,
            Category.name == name,
            Category.is_active.is_(True),
        )
    )
    if category is None:
        raise AccountingError(f"Unknown category: {name}")
    return category


def resolve_counterparty(session: Session, workspace_id: str, counterparty_id: str) -> Counterparty:
    counterparty = session.scalar(
        select(Counterparty).where(
            Counterparty.id == counterparty_id,
            Counterparty.workspace_id == workspace_id,
            Counterparty.is_active.is_(True),
        )
    )
    if counterparty is None:
        raise AccountingError("提供商不存在、已停用或不属于当前账本")
    return counterparty


def resolve_payment_account(
    session: Session, workspace_id: str, payment_account_id: str
) -> PaymentAccount:
    account = session.scalar(
        select(PaymentAccount).where(
            PaymentAccount.id == payment_account_id,
            PaymentAccount.workspace_id == workspace_id,
            PaymentAccount.is_active.is_(True),
        )
    )
    if account is None:
        raise AccountingError("支付账户不存在、已停用或不属于当前账本")
    return account


def resolve_category(
    session: Session,
    workspace_id: str,
    category_id: str,
    allowed_kinds: set[CategoryKind],
) -> Category:
    category = session.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.workspace_id == workspace_id,
            Category.is_active.is_(True),
        )
    )
    if category is None or CategoryKind(category.kind) not in allowed_kinds:
        raise AccountingError("分类不存在、已停用、类型不正确或不属于当前账本")
    return category


def _persist_transaction_fx_snapshot(
    session: Session,
    *,
    currency: str,
    rate_e12: int,
    effective_date: date,
    source_kind: str,
) -> FxRate:
    source = f"{source_kind}:{rate_e12}"
    effective_at = datetime.combine(effective_date, time.min, tzinfo=UTC)
    snapshot = session.scalar(
        select(FxRate).where(
            FxRate.base_currency == currency,
            FxRate.quote_currency == "CNY",
            FxRate.effective_at == effective_at,
            FxRate.source == source,
            FxRate.rate_type == "transaction_snapshot",
        )
    )
    if snapshot is None:
        snapshot = FxRate(
            base_currency=currency,
            quote_currency="CNY",
            rate_e12=rate_e12,
            effective_at=effective_at,
            source=source,
            rate_type="transaction_snapshot",
        )
        session.add(snapshot)
        session.flush()
    return snapshot


def resolve_money(
    session: Session,
    value: MoneyInput,
    *,
    effective_date: date | None = None,
    persist_snapshot: bool = True,
) -> ResolvedMoney:
    amount_e8 = to_e8(value.amount)
    currency = value.currency.upper()
    rate = session.get(FxRate, value.fx_rate_id) if value.fx_rate_id else None
    if value.fx_rate_id and rate is None:
        raise AccountingError("FX rate snapshot not found")
    if rate is not None and (rate.base_currency != currency or rate.quote_currency != "CNY"):
        raise AccountingError("FX rate snapshot does not match the currency pair")
    amount_cny_e8 = to_e8(value.amount_cny) if value.amount_cny is not None else None
    if amount_e8 == 0:
        if amount_cny_e8 not in {None, 0}:
            raise AccountingError("Zero original amount must have zero CNY amount")
        return ResolvedMoney(currency, 0, 0, value.fx_rate_id, value.amount)
    if currency in {"CNY", "UPSTREAM_CREDIT"}:
        if rate is not None:
            raise AccountingError(f"{currency} must not reference an FX rate")
        if value.fx_rate is not None and to_e12(value.fx_rate) != 1_000_000_000_000:
            raise AccountingError(f"{currency} inline rate must be exactly 1")
        if amount_cny_e8 is not None and amount_cny_e8 != amount_e8:
            raise AccountingError(f"{currency} amount must equal its CNY amount")
        return ResolvedMoney(currency, amount_e8, amount_e8, value.fx_rate_id, value.amount)

    rate_e12 = rate.rate_e12 if rate is not None else None
    source_kind = "inline"
    if value.fx_rate is not None:
        inline_rate_e12 = to_e12(value.fx_rate)
        if rate_e12 is not None and inline_rate_e12 != rate_e12:
            raise AccountingError("Inline FX rate conflicts with the referenced snapshot")
        rate_e12 = inline_rate_e12
    if rate_e12 is None and amount_cny_e8 is not None:
        rate_e12 = to_e12(str(as_decimal(value.amount_cny) / as_decimal(value.amount)))
        source_kind = "derived"
    if rate_e12 is None:
        raise AccountingError(f"CNY amount or FX rate is required for {currency}")
    if rate_e12 <= 0:
        raise AccountingError("FX rate must be positive")

    converted_e8 = convert_e8(amount_e8, rate_e12)
    if amount_cny_e8 is not None and abs(amount_cny_e8 - converted_e8) > 500_000:
        raise AccountingError("CNY amount does not match original amount multiplied by FX rate")
    resolved_cny_e8 = amount_cny_e8 if amount_cny_e8 is not None else converted_e8
    snapshot_id = rate.id if rate is not None else None
    if snapshot_id is None and persist_snapshot:
        snapshot = _persist_transaction_fx_snapshot(
            session,
            currency=currency,
            rate_e12=rate_e12,
            effective_date=effective_date or datetime.now(UTC).date(),
            source_kind=source_kind,
        )
        snapshot_id = snapshot.id
    return ResolvedMoney(currency, amount_e8, resolved_cny_e8, snapshot_id, value.amount)


def add_component(
    record: BusinessRecord,
    role: AmountRole,
    money: ResolvedMoney,
    *,
    sequence: int = 0,
    derived: bool = False,
) -> None:
    record.amounts.append(
        MoneyComponent(
            role=role,
            sequence=sequence,
            currency=money.currency,
            amount_e8=money.amount_e8,
            amount_cny_e8=money.amount_cny_e8,
            fx_rate_id=money.fx_rate_id,
            is_derived=derived,
            raw_amount_text=money.raw_amount_text,
        )
    )


def _check_duplicate(
    session: Session, workspace_id: str, source_channel: str | None, external_id: str | None
) -> None:
    if not external_id:
        return
    statement = select(BusinessRecord.id).where(
        BusinessRecord.workspace_id == workspace_id,
        BusinessRecord.external_id == external_id,
    )
    statement = statement.where(
        BusinessRecord.source_channel == source_channel
        if source_channel
        else BusinessRecord.source_channel.is_(None)
    )
    duplicate = session.scalar(statement)
    if duplicate:
        raise DuplicateRecordError(f"Duplicate external record: {source_channel}/{external_id}")


def _audit(
    session: Session,
    record: BusinessRecord,
    action: str,
    actor_id: str | None,
    actor_type: ActorType,
) -> None:
    record_type = getattr(record.record_type, "value", record.record_type)
    status = getattr(record.status, "value", record.status)
    session.add(
        AuditEvent(
            workspace_id=record.workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="business_record",
            entity_id=record.id,
            after_json={
                "type": record_type,
                "status": status,
                "description": record.description,
            },
        )
    )
    session.add(
        KnowledgeIndexJob(
            workspace_id=record.workspace_id,
            entity_type="business_record",
            entity_id=record.id,
            action="upsert",
            status="pending",
            available_at=datetime.now(UTC),
        )
    )


def create_income(
    session: Session,
    workspace: Workspace,
    payload: IncomeCreate,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
    commit: bool = True,
) -> BusinessRecord:
    _check_duplicate(session, workspace.id, payload.channel, payload.external_id)
    gross = resolve_money(session, payload.gross, effective_date=payload.accounting_date)
    fee = (
        resolve_money(session, payload.fee, effective_date=payload.accounting_date)
        if payload.fee
        else ResolvedMoney("CNY", 0, 0, None, "0")
    )
    if gross.amount_e8 <= 0 or gross.amount_cny_e8 <= 0:
        raise AccountingError("Gross income must be positive")
    if fee.amount_e8 < 0 or fee.amount_cny_e8 < 0:
        raise AccountingError("Income fee cannot be negative")
    if fee.amount_cny_e8 > gross.amount_cny_e8:
        raise AccountingError("Income fee cannot exceed gross income")
    net_cny = gross.amount_cny_e8 - fee.amount_cny_e8
    provider = (
        resolve_counterparty(session, workspace.id, payload.counterparty_id)
        if payload.counterparty_id
        else None
    )
    category = (
        resolve_category(
            session,
            workspace.id,
            payload.category_id,
            {CategoryKind.INCOME, CategoryKind.BOTH},
        )
        if payload.category_id
        else None
    )
    if category is None:
        category = category_by_name(session, workspace.id, "主营业务收入")
    record = BusinessRecord(
        workspace_id=workspace.id,
        record_type=RecordType.INCOME,
        status=RecordStatus.DRAFT,
        accounting_date=payload.accounting_date,
        occurred_at=payload.occurred_at,
        date_precision=payload.date_precision,
        category_id=category.id,
        counterparty_id=provider.id if provider else None,
        payment_account_id=None,
        source_channel=payload.channel,
        external_id=payload.external_id,
        recognition_method=payload.recognition_method,
        description=payload.description,
        note=payload.note,
        source_locator_json=payload.source_locator,
        metadata_json=payload.metadata,
        created_by_user_id=actor_id if actor_type == ActorType.USER else None,
        created_by_ai_run_id=actor_id if actor_type == ActorType.AI else None,
    )
    add_component(record, AmountRole.GROSS, gross)
    add_component(record, AmountRole.FEE, fee)
    add_component(
        record,
        AmountRole.NET,
        ResolvedMoney("CNY", net_cny, net_cny, None, str(net_cny)),
        derived=True,
    )
    add_component(
        record,
        AmountRole.CASH,
        ResolvedMoney("CNY", net_cny, net_cny, None, str(net_cny)),
        derived=True,
    )
    session.add(record)
    session.flush()
    if payload.post:
        post_record(session, record, actor_id=actor_id, actor_type=actor_type)
    _audit(session, record, "record.create", actor_id, actor_type)
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(record)
    return record


def create_expense(
    session: Session,
    workspace: Workspace,
    payload: ExpenseCreate,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
    record_type: RecordType = RecordType.EXPENSE,
    allow_credit: bool = False,
    commit: bool = True,
) -> BusinessRecord:
    _check_duplicate(session, workspace.id, payload.source_channel, payload.external_id)
    cost = resolve_money(session, payload.cost, effective_date=payload.accounting_date)
    fee = (
        resolve_money(session, payload.fee, effective_date=payload.accounting_date)
        if payload.fee
        else ResolvedMoney("CNY", 0, 0, None, "0")
    )
    supplied_cash = (
        resolve_money(session, payload.cash, effective_date=payload.accounting_date)
        if payload.cash
        else None
    )
    if allow_credit:
        if cost.amount_e8 >= 0 or cost.amount_cny_e8 >= 0:
            raise AccountingError("Expense credit must be negative")
        if fee.amount_e8 > 0 or fee.amount_cny_e8 > 0:
            raise AccountingError("Expense credit fee cannot be positive")
        if supplied_cash and (supplied_cash.amount_e8 > 0 or supplied_cash.amount_cny_e8 > 0):
            raise AccountingError("Expense credit cash amount cannot be positive")
    else:
        if cost.amount_e8 <= 0 or cost.amount_cny_e8 <= 0:
            raise AccountingError("Expense cost must be positive")
        if fee.amount_e8 < 0 or fee.amount_cny_e8 < 0:
            raise AccountingError("Expense fee cannot be negative")
        if supplied_cash and (supplied_cash.amount_e8 < 0 or supplied_cash.amount_cny_e8 < 0):
            raise AccountingError("Expense cash amount cannot be negative")
    expected_cash_cny = cost.amount_cny_e8 + fee.amount_cny_e8
    if supplied_cash and supplied_cash.amount_cny_e8 != expected_cash_cny:
        raise AccountingError("Expense cash must equal cost plus fee")
    cash = supplied_cash or ResolvedMoney(
        "CNY",
        expected_cash_cny,
        expected_cash_cny,
        None,
        str(expected_cash_cny),
    )
    provider = (
        resolve_counterparty(session, workspace.id, payload.counterparty_id)
        if payload.counterparty_id
        else None
    )
    category = (
        resolve_category(
            session,
            workspace.id,
            payload.category_id,
            {CategoryKind.EXPENSE, CategoryKind.BOTH},
        )
        if payload.category_id
        else None
    )
    if category is None and provider and provider.expense_category_id:
        category = resolve_category(
            session,
            workspace.id,
            provider.expense_category_id,
            {CategoryKind.EXPENSE},
        )
    if category is None:
        category = category_by_name(session, workspace.id, payload.category_name or "其他支出")
    if category.kind not in {CategoryKind.EXPENSE, CategoryKind.BOTH}:
        raise AccountingError("Expense requires an expense category")
    if provider and provider.expense_category_id and category.id != provider.expense_category_id:
        raise AccountingError("支出类别必须与提供商设置的类别一致")
    record = BusinessRecord(
        workspace_id=workspace.id,
        record_type=record_type,
        status=RecordStatus.DRAFT,
        accounting_date=payload.accounting_date,
        occurred_at=payload.occurred_at,
        date_precision=payload.date_precision,
        service_period_start=payload.service_period_start,
        service_period_end=payload.service_period_end,
        category_id=category.id,
        counterparty_id=provider.id if provider else None,
        payment_account_id=None,
        source_channel=payload.source_channel,
        external_id=payload.external_id,
        description=payload.description,
        note=payload.note,
        source_locator_json=payload.source_locator,
        metadata_json=payload.metadata,
        created_by_user_id=actor_id if actor_type == ActorType.USER else None,
        created_by_ai_run_id=actor_id if actor_type == ActorType.AI else None,
    )
    add_component(record, AmountRole.COST, cost)
    if fee.amount_e8 or fee.amount_cny_e8:
        add_component(record, AmountRole.FEE, fee)
    add_component(record, AmountRole.CASH, cash, derived=supplied_cash is None)
    session.add(record)
    session.flush()
    if payload.post:
        post_record(session, record, actor_id=actor_id, actor_type=actor_type)
    _audit(session, record, "record.create", actor_id, actor_type)
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(record)
    return record


def _get_or_create_counterparty(session: Session, workspace_id: str, name: str) -> Counterparty:
    counterparty = session.scalar(
        select(Counterparty).where(
            Counterparty.workspace_id == workspace_id, Counterparty.name == name
        )
    )
    if counterparty is not None and not counterparty.is_active:
        raise AccountingError("上游提供商已停用")
    if counterparty is None:
        category = category_by_name(session, workspace_id, "上游采购")
        counterparty = Counterparty(
            workspace_id=workspace_id,
            name=name,
            roles_json=["supplier"],
            expense_category_id=category.id,
            metadata_json={},
        )
        session.add(counterparty)
        session.flush()
    return counterparty


def create_topup(
    session: Session,
    workspace: Workspace,
    payload: TopupCreate,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
    commit: bool = True,
) -> BusinessRecord:
    counterparty = _get_or_create_counterparty(session, workspace.id, payload.upstream_name)
    expense = ExpenseCreate(
        accounting_date=payload.accounting_date,
        occurred_at=payload.occurred_at,
        date_precision=DatePrecision.TIMESTAMP if payload.occurred_at else DatePrecision.DAY,
        description=f"上游充值 - {payload.upstream_name}",
        cost=MoneyInput(currency="CNY", amount=payload.amount_cny),
        cash=MoneyInput(currency="CNY", amount=payload.amount_cny),
        category_name="上游采购",
        counterparty_id=counterparty.id,
        source_channel=payload.upstream_name,
        external_id=payload.external_id,
        note=payload.note,
        source_locator=payload.source_locator,
        metadata={**payload.metadata, "credit_rule": "1 CNY = 1 UPSTREAM_CREDIT"},
        post=False,
    )
    record = create_expense(
        session,
        workspace,
        expense,
        actor_id=actor_id,
        actor_type=actor_type,
        record_type=RecordType.EXPENSE,
        commit=False,
    )
    credit = to_e8(payload.amount_cny)
    record.amounts.append(
        MoneyComponent(
            role=AmountRole.CREDITED_VALUE,
            currency="UPSTREAM_CREDIT",
            amount_e8=credit,
            amount_cny_e8=credit,
            is_derived=True,
            raw_amount_text=payload.amount_cny,
        )
    )
    if payload.post:
        post_record(session, record, actor_id=actor_id, actor_type=actor_type)
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(record)
    return record


def create_refund(
    session: Session,
    workspace: Workspace,
    payload: RefundCreate,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
    commit: bool = True,
) -> BusinessRecord:
    original = session.scalar(
        select(BusinessRecord).where(
            BusinessRecord.id == payload.original_record_id,
            BusinessRecord.workspace_id == workspace.id,
            BusinessRecord.record_type == RecordType.INCOME,
            BusinessRecord.status == RecordStatus.POSTED,
        )
    )
    if original is None:
        raise AccountingError("Refund requires a posted income record")
    _check_duplicate(
        session,
        workspace.id,
        payload.channel or original.source_channel,
        payload.external_id,
    )
    refund = resolve_money(session, payload.refund, effective_date=payload.accounting_date)
    fee_refund = (
        resolve_money(session, payload.fee_refund, effective_date=payload.accounting_date)
        if payload.fee_refund
        else ResolvedMoney("CNY", 0, 0, None, "0")
    )
    if (
        refund.amount_e8 <= 0
        or refund.amount_cny_e8 <= 0
        or fee_refund.amount_e8 < 0
        or fee_refund.amount_cny_e8 < 0
    ):
        raise AccountingError("Refund amounts must not be negative")
    if fee_refund.amount_cny_e8 > refund.amount_cny_e8:
        raise AccountingError("Refunded fee cannot exceed the refund")
    expected_cash_e8 = refund.amount_cny_e8 - fee_refund.amount_cny_e8
    cash = (
        resolve_money(session, payload.cash_out, effective_date=payload.accounting_date)
        if payload.cash_out
        else ResolvedMoney("CNY", expected_cash_e8, expected_cash_e8, None, str(expected_cash_e8))
    )
    if cash.amount_cny_e8 != expected_cash_e8:
        raise AccountingError("Cash refund must equal refund less refunded channel fee")
    if cash.amount_e8 < 0 or cash.amount_cny_e8 < 0:
        raise AccountingError("Cash refund cannot be negative")

    original_gross = _component(original, AmountRole.GROSS)
    original_fee = _component(original, AmountRole.FEE)
    if original_gross is None:
        raise AccountingError("Original income has no gross amount")
    prior_refund_e8 = 0
    prior_fee_e8 = 0
    prior_records = session.scalars(
        select(BusinessRecord)
        .join(RecordLink, RecordLink.source_record_id == BusinessRecord.id)
        .where(
            RecordLink.target_record_id == original.id,
            RecordLink.relation_type == "refund_of",
            BusinessRecord.status.in_([RecordStatus.DRAFT, RecordStatus.POSTED]),
        )
    )
    for prior in prior_records:
        prior_refund = _component(prior, AmountRole.REFUND)
        prior_fee = _component(prior, AmountRole.FEE)
        prior_refund_e8 += prior_refund.amount_cny_e8 if prior_refund else 0
        prior_fee_e8 += prior_fee.amount_cny_e8 if prior_fee else 0
    if prior_refund_e8 + refund.amount_cny_e8 > original_gross.amount_cny_e8:
        raise AccountingError("Cumulative refunds cannot exceed original gross income")
    original_fee_e8 = original_fee.amount_cny_e8 if original_fee else 0
    if prior_fee_e8 + fee_refund.amount_cny_e8 > original_fee_e8:
        raise AccountingError("Cumulative fee refunds cannot exceed the original fee")

    record = BusinessRecord(
        workspace_id=workspace.id,
        record_type=RecordType.REFUND,
        status=RecordStatus.DRAFT,
        accounting_date=payload.accounting_date,
        occurred_at=payload.occurred_at,
        date_precision=DatePrecision.TIMESTAMP if payload.occurred_at else DatePrecision.DAY,
        category_id=original.category_id,
        counterparty_id=original.counterparty_id,
        payment_account_id=original.payment_account_id,
        source_channel=payload.channel or original.source_channel,
        external_id=payload.external_id,
        recognition_method="refund",
        description=payload.description or f"退款：{original.description}",
        note=payload.note,
        source_locator_json=payload.source_locator,
        metadata_json={**payload.metadata, "original_record_id": original.id},
        created_by_user_id=actor_id if actor_type == ActorType.USER else None,
        created_by_ai_run_id=actor_id if actor_type == ActorType.AI else None,
    )
    add_component(record, AmountRole.REFUND, refund)
    add_component(record, AmountRole.FEE, fee_refund)
    add_component(record, AmountRole.CASH, cash, derived=payload.cash_out is None)
    session.add(record)
    session.flush()
    session.add(
        RecordLink(
            source_record_id=record.id,
            target_record_id=original.id,
            relation_type="refund_of",
            amount_cny_e8=refund.amount_cny_e8,
        )
    )
    if payload.post:
        post_record(session, record, actor_id=actor_id, actor_type=actor_type)
    _audit(session, record, "record.create", actor_id, actor_type)
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(record)
    return record


def _component(record: BusinessRecord, role: AmountRole) -> MoneyComponent | None:
    return next((item for item in record.amounts if item.role == role), None)


def _append_signed_line(
    entry: JournalEntry,
    account_id: str,
    amount: int,
    *,
    side: str,
    description: str,
    original_currency: str | None = None,
    original_amount_e8: int | None = None,
) -> None:
    if amount == 0:
        return
    debit = 0
    credit = 0
    if (side == "debit" and amount > 0) or (side == "credit" and amount < 0):
        debit = abs(amount)
    else:
        credit = abs(amount)
    entry.lines.append(
        JournalLine(
            account_id=account_id,
            debit_cny_e8=debit,
            credit_cny_e8=credit,
            original_currency=original_currency,
            original_amount_e8=original_amount_e8,
            description=description,
        )
    )


def post_record(
    session: Session,
    record: BusinessRecord,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
) -> JournalEntry:
    if record.status != RecordStatus.DRAFT:
        raise AccountingError("Only draft records can be posted")
    entry = JournalEntry(
        workspace_id=record.workspace_id,
        record_id=record.id,
        entry_date=record.accounting_date,
        status=JournalStatus.DRAFT,
        memo=record.description,
        posted_by_user_id=actor_id if actor_type == ActorType.USER else None,
        posted_by_ai_run_id=actor_id if actor_type == ActorType.AI else None,
    )
    category = (
        session.scalar(
            select(Category).where(
                Category.id == record.category_id,
                Category.workspace_id == record.workspace_id,
                Category.is_active.is_(True),
            )
        )
        if record.category_id
        else None
    )

    if record.record_type == RecordType.INCOME:
        if category is None:
            raise AccountingError("Income category is required before posting")
        if category.kind not in {CategoryKind.INCOME, CategoryKind.BOTH}:
            raise AccountingError("Income category type is invalid")
        gross = _component(record, AmountRole.GROSS)
        fee = _component(record, AmountRole.FEE)
        net = _component(record, AmountRole.NET)
        cash = _component(record, AmountRole.CASH)
        if gross is None or net is None:
            raise AccountingError("Income requires gross and net components")
        destination_account = (
            resolve_payment_account(session, record.workspace_id, record.payment_account_id)
            if record.payment_account_id
            else None
        )
        destination_ledger_id = (
            destination_account.ledger_account_id
            if destination_account is not None
            else account_by_code(session, record.workspace_id, "1002").id
        )
        _append_signed_line(
            entry,
            destination_ledger_id,
            net.amount_cny_e8,
            side="debit",
            description="收入净额",
            original_currency=net.currency,
            original_amount_e8=net.amount_e8,
        )
        if fee and fee.amount_cny_e8:
            _append_signed_line(
                entry,
                account_by_code(session, record.workspace_id, "5603").id,
                fee.amount_cny_e8,
                side="debit",
                description="手续费",
                original_currency=fee.currency,
                original_amount_e8=fee.amount_e8,
            )
        _append_signed_line(
            entry,
            category.account_id,
            gross.amount_cny_e8,
            side="credit",
            description="毛收入",
            original_currency=gross.currency,
            original_amount_e8=gross.amount_e8,
        )
    elif record.record_type == RecordType.REFUND:
        if category is None:
            raise AccountingError("Refund requires the original income category")
        if category.kind not in {CategoryKind.INCOME, CategoryKind.BOTH}:
            raise AccountingError("Refund category type is invalid")
        refund = _component(record, AmountRole.REFUND)
        fee_refund = _component(record, AmountRole.FEE)
        cash = _component(record, AmountRole.CASH)
        if refund is None or cash is None:
            raise AccountingError("Refund requires refund and cash components")
        _append_signed_line(
            entry,
            category.account_id,
            refund.amount_cny_e8,
            side="debit",
            description="冲减收入",
            original_currency=refund.currency,
            original_amount_e8=refund.amount_e8,
        )
        if fee_refund and fee_refund.amount_cny_e8:
            _append_signed_line(
                entry,
                account_by_code(session, record.workspace_id, "5603").id,
                fee_refund.amount_cny_e8,
                side="credit",
                description="退回手续费",
                original_currency=fee_refund.currency,
                original_amount_e8=fee_refund.amount_e8,
            )
        payment_account = (
            resolve_payment_account(session, record.workspace_id, record.payment_account_id)
            if record.payment_account_id
            else None
        )
        asset_account_id = (
            payment_account.ledger_account_id
            if payment_account is not None
            else account_by_code(session, record.workspace_id, "1002").id
        )
        _append_signed_line(
            entry,
            asset_account_id,
            cash.amount_cny_e8,
            side="credit",
            description="退款流出",
            original_currency=cash.currency,
            original_amount_e8=cash.amount_e8,
        )
    elif record.record_type in {
        RecordType.EXPENSE,
        RecordType.TOPUP,
        RecordType.SUBSCRIPTION,
        RecordType.ADJUSTMENT,
    }:
        if category is None:
            raise AccountingError("Expense category is required before posting")
        if category.kind not in {CategoryKind.EXPENSE, CategoryKind.BOTH}:
            raise AccountingError("Expense category type is invalid")
        cost = _component(record, AmountRole.COST)
        fee = _component(record, AmountRole.FEE)
        cash = _component(record, AmountRole.CASH)
        if cost is None:
            raise AccountingError("Expense requires a cost component")
        _append_signed_line(
            entry,
            category.account_id,
            cost.amount_cny_e8,
            side="debit",
            description="费用确认",
            original_currency=cost.currency,
            original_amount_e8=cost.amount_e8,
        )
        fee_cny_e8 = fee.amount_cny_e8 if fee else 0
        if fee is not None and fee_cny_e8:
            _append_signed_line(
                entry,
                account_by_code(session, record.workspace_id, "5603").id,
                fee_cny_e8,
                side="debit",
                description="手续费",
                original_currency=fee.currency,
                original_amount_e8=fee.amount_e8,
            )
        payable_cny_e8 = cost.amount_cny_e8 + fee_cny_e8
        if cash is None:
            _append_signed_line(
                entry,
                account_by_code(session, record.workspace_id, "2202").id,
                payable_cny_e8,
                side="credit",
                description="未支付费用",
            )
        else:
            asset_account_id = (
                resolve_payment_account(
                    session, record.workspace_id, record.payment_account_id
                ).ledger_account_id
                if record.payment_account_id
                else account_by_code(session, record.workspace_id, "1002").id
            )
            _append_signed_line(
                entry,
                asset_account_id,
                cash.amount_cny_e8,
                side="credit",
                description="现金支付",
                original_currency=cash.currency,
                original_amount_e8=cash.amount_e8,
            )
            if payable_cny_e8 != cash.amount_cny_e8:
                raise AccountingError("Expense cash must equal cost plus fee")
    else:
        raise AccountingError(f"Posting is not implemented for {record.record_type.value}")

    debit_total = sum(line.debit_cny_e8 for line in entry.lines)
    credit_total = sum(line.credit_cny_e8 for line in entry.lines)
    if debit_total != credit_total or debit_total == 0:
        raise AccountingError(
            f"Unbalanced journal entry: debit={debit_total}, credit={credit_total}"
        )
    session.add(entry)
    session.flush()
    entry.status = JournalStatus.POSTED
    session.flush()
    record.status = RecordStatus.POSTED
    record.posted_entry_id = entry.id
    record.version += 1
    return entry


def delete_record_graph(
    session: Session,
    record: BusinessRecord,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
    commit: bool = True,
) -> int:
    if record.record_type not in {RecordType.INCOME, RecordType.EXPENSE}:
        raise AccountingError("Only income and expense records can be deleted")

    record_rows = session.execute(
        select(
            BusinessRecord.id,
            BusinessRecord.reversed_by_record_id,
            BusinessRecord.posted_entry_id,
        ).where(BusinessRecord.workspace_id == record.workspace_id)
    ).all()
    valid_record_ids = {row.id for row in record_rows}
    record_edges: dict[str, set[str]] = {record_id: set() for record_id in valid_record_ids}
    record_entries: dict[str, set[str]] = {record_id: set() for record_id in valid_record_ids}

    for row in record_rows:
        if row.reversed_by_record_id in valid_record_ids:
            record_edges[row.id].add(row.reversed_by_record_id)
            record_edges[row.reversed_by_record_id].add(row.id)
        if row.posted_entry_id:
            record_entries[row.id].add(row.posted_entry_id)

    for source_id, target_id in session.execute(
        select(RecordLink.source_record_id, RecordLink.target_record_id)
    ):
        if source_id in valid_record_ids and target_id in valid_record_ids:
            record_edges[source_id].add(target_id)
            record_edges[target_id].add(source_id)

    entry_rows = session.execute(
        select(JournalEntry.id, JournalEntry.record_id, JournalEntry.reversal_of_id).where(
            JournalEntry.workspace_id == record.workspace_id
        )
    ).all()
    valid_entry_ids = {row.id for row in entry_rows}
    entry_edges: dict[str, set[str]] = {entry_id: set() for entry_id in valid_entry_ids}
    entry_records: dict[str, set[str]] = {entry_id: set() for entry_id in valid_entry_ids}
    for row in entry_rows:
        if row.record_id in valid_record_ids:
            record_entries[row.record_id].add(row.id)
            entry_records[row.id].add(row.record_id)
        if row.reversal_of_id in valid_entry_ids:
            entry_edges[row.id].add(row.reversal_of_id)
            entry_edges[row.reversal_of_id].add(row.id)

    record_ids = {record.id}
    entry_ids: set[str] = set()
    while True:
        next_record_ids = set(record_ids)
        next_entry_ids = set(entry_ids)
        for record_id in record_ids:
            next_record_ids.update(record_edges.get(record_id, set()))
            next_entry_ids.update(record_entries.get(record_id, set()))
        for entry_id in entry_ids:
            next_entry_ids.update(entry_edges.get(entry_id, set()))
            next_record_ids.update(entry_records.get(entry_id, set()))
        if next_record_ids == record_ids and next_entry_ids == entry_ids:
            break
        record_ids = next_record_ids
        entry_ids = next_entry_ids

    approvals = session.scalars(
        select(ApprovalRequest).where(ApprovalRequest.workspace_id == record.workspace_id)
    )
    for approval in approvals:
        related_ids = {
            value
            for key, value in approval.payload_json.items()
            if key.endswith("record_id") and isinstance(value, str)
        }
        if related_ids & record_ids:
            session.delete(approval)

    session.execute(
        update(BusinessRecord)
        .where(
            BusinessRecord.workspace_id == record.workspace_id,
            BusinessRecord.id.in_(record_ids),
        )
        .values(posted_entry_id=None, reversed_by_record_id=None)
        .execution_options(synchronize_session=False)
    )
    session.execute(
        delete(RecordLink)
        .where(
            or_(
                RecordLink.source_record_id.in_(record_ids),
                RecordLink.target_record_id.in_(record_ids),
            )
        )
        .execution_options(synchronize_session=False)
    )
    session.execute(
        delete(RecordTag)
        .where(RecordTag.record_id.in_(record_ids))
        .execution_options(synchronize_session=False)
    )
    session.execute(
        delete(MoneyComponent)
        .where(MoneyComponent.record_id.in_(record_ids))
        .execution_options(synchronize_session=False)
    )
    if entry_ids:
        session.execute(
            delete(JournalLine)
            .where(JournalLine.entry_id.in_(entry_ids))
            .execution_options(synchronize_session=False)
        )
        session.execute(
            delete(JournalEntry)
            .where(JournalEntry.id.in_(entry_ids))
            .execution_options(synchronize_session=False)
        )
    session.execute(
        delete(BusinessRecord)
        .where(
            BusinessRecord.workspace_id == record.workspace_id,
            BusinessRecord.id.in_(record_ids),
        )
        .execution_options(synchronize_session=False)
    )
    session.add(
        AuditEvent(
            workspace_id=record.workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="record.delete",
            entity_type="business_record",
            entity_id=record.id,
            before_json={
                "type": str(record.record_type),
                "description": record.description,
                "deleted_record_count": len(record_ids),
                "deleted_entry_count": len(entry_ids),
            },
        )
    )
    session.add_all(
        KnowledgeIndexJob(
            workspace_id=record.workspace_id,
            entity_type="business_record",
            entity_id=record_id,
            action="tombstone",
            status="pending",
            available_at=datetime.now(UTC),
        )
        for record_id in record_ids
    )
    if commit:
        session.commit()
    else:
        session.flush()
    return len(record_ids)


def validate_record_reversal(session: Session, record: BusinessRecord) -> None:
    if record.status != RecordStatus.POSTED or not record.posted_entry_id:
        raise AccountingError("Only posted records can be reversed")

    active_refund = session.scalar(
        select(RecordLink.id)
        .join(BusinessRecord, BusinessRecord.id == RecordLink.source_record_id)
        .where(
            RecordLink.target_record_id == record.id,
            RecordLink.relation_type == "refund_of",
            BusinessRecord.status.in_([RecordStatus.DRAFT, RecordStatus.POSTED]),
        )
        .limit(1)
    )
    if active_refund is not None:
        raise AccountingError("Income has active refunds; reverse those refunds first")

    active_downstream = session.scalar(
        select(RecordLink.relation_type)
        .join(BusinessRecord, BusinessRecord.id == RecordLink.source_record_id)
        .where(
            RecordLink.target_record_id == record.id,
            RecordLink.relation_type != "reversal_of",
            BusinessRecord.status.in_([RecordStatus.DRAFT, RecordStatus.POSTED]),
        )
        .limit(1)
    )
    if active_downstream is not None:
        raise AccountingError(
            f"Record has an active {active_downstream} relationship; resolve it before reversal"
        )


def reverse_record(
    session: Session,
    record: BusinessRecord,
    *,
    actor_id: str | None = None,
    actor_type: ActorType = ActorType.USER,
    reason: str,
    commit: bool = True,
) -> BusinessRecord:
    validate_record_reversal(session, record)
    original_entry = session.get(JournalEntry, record.posted_entry_id)
    if original_entry is None:
        raise AccountingError("Posted journal entry not found")
    reversal_record = BusinessRecord(
        workspace_id=record.workspace_id,
        record_type=record.record_type,
        status=RecordStatus.POSTED,
        accounting_date=record.accounting_date,
        occurred_at=datetime.now(UTC),
        date_precision=DatePrecision.TIMESTAMP,
        category_id=record.category_id,
        counterparty_id=record.counterparty_id,
        payment_account_id=record.payment_account_id,
        source_channel=record.source_channel,
        external_id=f"reversal:{record.id}",
        recognition_method="reversal",
        description=f"冲正：{record.description}",
        note=reason,
        source_locator_json={"reversal_of": record.id},
        metadata_json={},
        created_by_user_id=actor_id if actor_type == ActorType.USER else None,
        created_by_ai_run_id=actor_id if actor_type == ActorType.AI else None,
    )
    for component in record.amounts:
        reversal_record.amounts.append(
            MoneyComponent(
                role=component.role,
                sequence=component.sequence,
                currency=component.currency,
                amount_e8=-component.amount_e8,
                amount_cny_e8=-component.amount_cny_e8,
                fx_rate_id=component.fx_rate_id,
                is_derived=True,
                raw_amount_text=f"-{component.raw_amount_text or component.amount_e8}",
            )
        )
    session.add(reversal_record)
    session.flush()
    reversal_entry = JournalEntry(
        workspace_id=record.workspace_id,
        record_id=reversal_record.id,
        entry_date=record.accounting_date,
        status=JournalStatus.DRAFT,
        memo=reversal_record.description,
        reversal_of_id=original_entry.id,
        posted_by_user_id=actor_id if actor_type == ActorType.USER else None,
        posted_by_ai_run_id=actor_id if actor_type == ActorType.AI else None,
    )
    for line in original_entry.lines:
        reversal_entry.lines.append(
            JournalLine(
                account_id=line.account_id,
                debit_cny_e8=line.credit_cny_e8,
                credit_cny_e8=line.debit_cny_e8,
                original_currency=line.original_currency,
                original_amount_e8=(-line.original_amount_e8 if line.original_amount_e8 else None),
                description=f"冲正：{line.description or ''}",
            )
        )
    session.add(reversal_entry)
    session.flush()
    reversal_entry.status = JournalStatus.POSTED
    session.flush()
    reversal_record.posted_entry_id = reversal_entry.id
    record.status = RecordStatus.REVERSED
    record.reversed_by_record_id = reversal_record.id
    record.version += 1
    session.add(
        RecordLink(
            source_record_id=reversal_record.id,
            target_record_id=record.id,
            relation_type="reversal_of",
        )
    )
    _audit(session, record, "record.reverse", actor_id, actor_type)
    if commit:
        session.commit()
    else:
        session.flush()
    session.refresh(reversal_record)
    return reversal_record
