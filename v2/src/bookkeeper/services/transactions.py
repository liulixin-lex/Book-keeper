"""Transactions: every write takes effect at once; the ledger keeps the full history (docs/05 §10).

Two kinds of types:
- line types (``manual_journal``, ``opening_balance``): the client gives the journal lines;
- business types (``sale``, ``credit_purchase``, ``expense``, ``transfer`` and refunds): the client
  gives business inputs and the lines are built by code plus versioned fee rules.

Life cycle, all on one transaction (its number never changes):
- ``create`` builds the lines and posts them;
- ``edit`` changes header fields in place; a change that affects the books reverses the current entry
  and posts the rebuilt lines (``repost_reversal`` + ``repost``);
- ``delete`` reverses the current entry (status ``reversed``); ``restore`` posts its lines again;
- ``repost`` rebuilds with the current fee rules and rates.
Journal entries are never changed or removed, so every step can be undone (services/undo.py).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Account,
    Book,
    Counterparty,
    CounterpartyAccount,
    DimensionValue,
    JournalEntry,
    JournalLine,
    JournalLineDimension,
    Transaction,
    TransactionLink,
    TransactionType,
)
from bookkeeper.domain import chart
from bookkeeper.domain.business import BUSINESS_TYPES
from bookkeeper.domain.errors import DomainError, FieldError, not_found, version_conflict
from bookkeeper.domain.fees import FEE_TYPES
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.ledger import (
    BuildResult,
    BuildSettings,
    BuiltLine,
    LineInput,
    build_lines,
    reverse_lines,
)
from bookkeeper.domain.money import AmountError, format_amount, from_minor, parse_decimal, to_minor
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import accounts, audit, business, ledger, reference, tags
from bookkeeper.services.context import RequestContext

HEADER_FIELDS = ("description", "notes", "metadata", "tags", "order_no", "external_ref")  # changed in place
BOOK_FIELDS = (  # a change re-posts the transaction
    "effective_date",
    "occurred_at",
    "date_precision",
    "counterparty",
    "inputs",
    "lines",
    "allow_conversion",
    "journal_code",
)
EDITABLE = HEADER_FIELDS + BOOK_FIELDS


@dataclass(frozen=True)
class LineSpec:
    """A line as given by a client (references unresolved)."""

    account: str
    side: str
    amount: str
    commodity: str
    fx_rate: str | None = None
    base_amount: str | None = None
    counterparty: str | None = None
    counterparty_account: str | None = None
    dimensions: dict[str, str] | None = None
    memo: str | None = None
    quantity: str | None = None
    quantity_unit: str | None = None


def _txn_type(session: Session, book_id: str, code: str) -> TransactionType:
    item = session.execute(
        select(TransactionType).where(TransactionType.book_id == book_id, TransactionType.code == code)
    ).scalar_one_or_none()
    if item is None or not item.is_active:
        raise DomainError("VALIDATION_FAILED", f"未知或已停用的交易类型 {code}。")
    if code not in chart.LINE_INPUT_TYPES and code not in BUSINESS_TYPES:
        raise DomainError("VALIDATION_FAILED", f"交易类型 {code} 暂不支持录入。")
    return item


def is_business(type_code: str) -> bool:
    return type_code in BUSINESS_TYPES


def _book(session: Session, book_id: str) -> Book:
    book = session.get(Book, book_id)
    if book is None:
        raise not_found("账套", book_id)
    return book


def normalise_lines(session: Session, book: Book, specs: Sequence[LineSpec]) -> list[dict[str, Any]]:
    """Resolve references and convert amounts; returns the JSON stored in ``inputs.lines``."""
    scales = reference.active_scales(session)
    errors: list[FieldError] = []
    result: list[dict[str, Any]] = []
    for i, spec in enumerate(specs):
        path = f"lines.{i}"
        row: dict[str, Any] = {"side": spec.side, "commodity": spec.commodity, "memo": spec.memo}
        try:
            account = accounts.get_account(session, book.id, spec.account)
            row["account_id"] = account.id
        except DomainError:
            errors.append(FieldError(f"{path}.account", "NOT_FOUND", f"科目 {spec.account} 不存在"))
        if spec.commodity not in scales:
            errors.append(
                FieldError(f"{path}.amount.commodity", "INPUT_INVALID", reference.unknown_commodity(spec.commodity))
            )
        else:
            try:
                row["amount_minor"] = to_minor(spec.amount, scales[spec.commodity])
                if spec.base_amount is not None:
                    row["base_amount_minor"] = to_minor(spec.base_amount, scales[book.base_commodity])
                if spec.fx_rate is not None:
                    row["fx_rate"] = str(parse_decimal(spec.fx_rate))
                if spec.quantity is not None:
                    row["quantity"] = str(parse_decimal(spec.quantity))
                    row["quantity_unit"] = spec.quantity_unit
            except AmountError as exc:
                errors.append(FieldError(f"{path}.amount", "INPUT_INVALID", str(exc)))
        if spec.counterparty:
            try:
                row["counterparty_id"] = reference.get_counterparty(session, book.id, spec.counterparty).id
            except DomainError:
                errors.append(FieldError(f"{path}.counterparty", "NOT_FOUND", f"往来方 {spec.counterparty} 不存在"))
        if spec.counterparty_account:
            cpa = session.get(CounterpartyAccount, spec.counterparty_account)
            if cpa is None or cpa.book_id != book.id:
                errors.append(FieldError(f"{path}.counterparty_account", "NOT_FOUND", "往来方子账户不存在"))
            else:
                row["counterparty_account_id"] = cpa.id
        if spec.dimensions:
            try:
                row["dimensions"] = reference.resolve_dimensions(session, book.id, spec.dimensions)
            except DomainError as exc:
                errors.append(FieldError(f"{path}.dimensions", "VALIDATION_FAILED", exc.detail))
        result.append(row)
    if errors:
        raise DomainError("INPUT_INVALID", f"分录行有 {len(errors)} 处问题：{errors[0].message}。", errors=errors)
    return result


def _line_inputs(
    session: Session,
    book: Book,
    stored: Sequence[dict[str, Any]],
    effective_date: date,
    txn_type: str,
) -> list[LineInput]:
    ids = {row["account_id"] for row in stored}
    loaded = {a.id: a for a in session.execute(select(Account).where(Account.id.in_(ids))).scalars()}
    inputs = []
    for row in stored:
        inputs.append(
            LineInput(
                account=accounts.to_info(loaded[row["account_id"]]),
                side=row["side"],
                amount_minor=row["amount_minor"],
                commodity=row["commodity"],
                fx_rate=Decimal(row["fx_rate"]) if row.get("fx_rate") else None,
                base_amount_minor=row.get("base_amount_minor"),
                counterparty_id=row.get("counterparty_id"),
                counterparty_account_id=row.get("counterparty_account_id"),
                dimensions=row.get("dimensions") or {},
                memo=row.get("memo"),
                quantity=Decimal(row["quantity"]) if row.get("quantity") else None,
                quantity_unit=row.get("quantity_unit"),
                line_role="manual",
            )
        )
    if txn_type == "opening_balance":
        _check_opening_lines(inputs)
    return inputs


def _check_opening_lines(inputs: list[LineInput]) -> None:
    errors = [
        FieldError(
            f"lines.{i}.account",
            "INPUT_INVALID",
            f"期初余额只能录入资产、负债、权益科目（{line.account.code}）",
        )
        for i, line in enumerate(inputs)
        if line.account.classification not in ("asset", "liability", "equity")
    ]
    if errors:
        raise DomainError("INPUT_INVALID", errors[0].message + "。", errors=errors)


@dataclass
class Plan:
    """Lines ready to post, plus what the business layer computed."""

    result: BuildResult
    computed: dict[str, Any] = field(default_factory=dict)
    business_warnings: list[dict[str, str]] = field(default_factory=list)
    fee_rule_ids: tuple[str, ...] = ()
    is_estimate: bool = False

    @property
    def warnings(self) -> list[dict[str, str]]:
        return self.business_warnings + list(self.result.warnings)


def build(session: Session, book: Book, txn: Transaction, txn_type: str) -> Plan:
    prepared = business.prepare(session, book, txn, txn_type) if is_business(txn_type) else None
    if prepared is not None:
        inputs = prepared.lines
    else:
        inputs = _line_inputs(session, book, txn.inputs.get("lines", []), txn.effective_date, txn_type)
    roles = ("trading", "fx_gain_loss", "rounding", "opening_balance")
    system = {role: accounts.default_for_role(session, book.id, role) for role in roles}
    offset = system["opening_balance"] if txn_type == "opening_balance" else None
    if txn_type == "opening_balance" and offset is None:
        raise DomainError("ACCOUNT_NOT_POSTABLE", "账套缺少系统科目：期初余额调整（opening_balance）。")
    settings = BuildSettings(
        base_commodity=book.base_commodity,
        scales=reference.commodity_scales(session),
        effective_date=txn.effective_date,
        rounding_mode=book.rounding_mode,
        tolerance_per_line=book.rounding_tolerance_per_line,
        enforce_manual_flag=txn_type == "manual_journal",
        allow_conversion=prepared.allow_conversion if prepared else bool(txn.inputs.get("allow_conversion")),
        fx_realization=book.settings.get("fx_realization", "immediate"),
        trading_account=accounts.to_info(system["trading"]) if system["trading"] else None,
        fx_gain_loss_account=accounts.to_info(system["fx_gain_loss"]) if system["fx_gain_loss"] else None,
        rounding_account=accounts.to_info(system["rounding"]) if system["rounding"] else None,
        offset_account=accounts.to_info(offset) if offset else None,
        quote_for=reference.QuoteProvider(session, book, txn.effective_date),
    )
    result = build_lines(inputs, settings)
    if prepared is None:
        debit = sum(line.base_amount for line in result.lines if line.base_amount > 0)
        return Plan(result, computed={"headline": headline(session, debit, book.base_commodity)})
    return Plan(
        result,
        computed=prepared.computed,
        business_warnings=prepared.warnings,
        fee_rule_ids=(prepared.fee_rule.id,) if prepared.fee_rule else (),
        is_estimate=prepared.is_estimate,
    )


def headline(session: Session, minor: int, commodity: str) -> dict[str, Any]:
    """The one amount shown in lists and used by amount filters."""
    item = reference.commodities_by_code(session)[commodity]
    return money_view(minor, commodity, item.scale, item.symbol)


def transaction_number(session: Session, book: Book) -> str:
    year = datetime.now(ZoneInfo(book.timezone)).year
    return f"T{year}-{ledger.next_number(session, book.id, 'TXN', str(year)):06d}"


def _effective_date(book: Book, effective: date | None, occurred_at: datetime | None) -> date:
    if effective is not None:
        return effective
    if occurred_at is None:
        raise DomainError("VALIDATION_FAILED", "必须提供 effective_date 或 occurred_at。")
    if occurred_at.tzinfo is None:
        raise DomainError("VALIDATION_FAILED", "occurred_at 必须带时区偏移。")
    return occurred_at.astimezone(ZoneInfo(book.timezone)).date()


def _provenance(ctx: RequestContext, fields: Sequence[str]) -> dict[str, Any]:
    source = (
        f"mcp:{ctx.actor.token_id}"
        if ctx.channel == "mcp"
        else (f"token:{ctx.actor.token_id}" if ctx.actor.token_id else f"user:{ctx.actor.user_id}")
    )
    now = datetime.now(UTC).isoformat()
    return {f: {"by": source, "at": now, "locked": ctx.channel in ("ui", "api", "mcp", "cli")} for f in fields}


def _check_external_ref(session: Session, book_id: str, external_ref: str) -> None:
    existing = session.execute(
        select(Transaction.number, Transaction.status).where(
            Transaction.book_id == book_id, Transaction.external_ref == external_ref
        )
    ).first()
    if existing:
        number, status = existing
        raise DomainError(
            "DUPLICATE_SUSPECTED",
            f"外部单号 {external_ref} 已存在（交易 {number}"
            + ("，已删除，可恢复" if status == "reversed" else "")
            + "）。",
            extra={"existing_transaction": number},
        )


def new_transaction(session: Session, ctx: RequestContext, data: dict[str, Any]) -> tuple[Transaction, str]:
    """Validate ``data`` and resolve its references into an unsaved transaction (no number yet)."""
    book = _book(session, ctx.require_book())
    counterparty_id = _counterparty_id(session, book.id, data.get("counterparty"))
    defaults_applied: dict[str, str] = {}
    type_code = data.get("type")
    if not type_code and counterparty_id:
        cp = session.get(Counterparty, counterparty_id)
        type_code = reference.counterparty_defaults(session, cp)["type"] if cp else None
        if type_code:
            defaults_applied["type"] = type_code
    if not type_code:
        raise DomainError(
            "VALIDATION_FAILED",
            "缺少交易类型：请填写 type，或先给往来方设置默认交易类型。",
            errors=[FieldError("type", "INPUT_INVALID", "缺少交易类型")],
        )
    txn_type = _txn_type(session, book.id, type_code)
    code = txn_type.code
    occurred_at = data.get("occurred_at")
    effective = _effective_date(book, data.get("effective_date"), occurred_at)
    journal_code = data.get("journal_code") or book.journal_codes[0]
    if journal_code not in book.journal_codes:
        raise DomainError("VALIDATION_FAILED", f"凭证字 {journal_code} 未在账套中定义。")
    description = (data.get("description") or "").strip() or ("期初余额" if code == "opening_balance" else "")
    if not is_business(code) and len(description) < 2:
        raise DomainError("VALIDATION_FAILED", "手工凭证必须填写摘要，格式“调整 · 原因”。")
    external_ref = data.get("external_ref")
    if external_ref:
        _check_external_ref(session, book.id, external_ref)
    header: dict[str, Any] = {"counterparty_id": counterparty_id}
    stored: dict[str, Any] = {"journal_code": journal_code}
    if is_business(code):
        if data.get("lines"):
            raise DomainError("VALIDATION_FAILED", f"交易类型 {code} 不接受 lines，请填写 inputs。")
        stored |= business.normalise(session, book, code, data.get("inputs") or {}, header)
    else:
        if data.get("inputs"):
            raise DomainError("VALIDATION_FAILED", f"交易类型 {code} 不接受 inputs，请填写 lines。")
        stored |= {
            "lines": normalise_lines(session, book, data.get("lines") or []),
            "allow_conversion": bool(data.get("allow_conversion")),
        }
    applied = defaults_applied | header.get("defaults_applied", {})
    txn = Transaction(
        id=new_id("txn"),
        book_id=book.id,
        transaction_type_id=txn_type.id,
        status="posted",
        effective_date=effective,
        date_precision=data.get("date_precision") or ("timestamp" if occurred_at else "day"),
        description=description or code,
        counterparty_id=header["counterparty_id"],
        inputs=stored,
        computed={},
        default_dimensions={"channel": stored["channel_id"]} if stored.get("channel_id") else {},
        external_ref=external_ref,
        order_no=data.get("order_no"),
        notes=data.get("notes"),
        metadata_=data.get("metadata") or {},
        is_estimate=False,
        created_channel=ctx.channel if ctx.channel != "worker" else "system",
        created_by_user_id=ctx.actor.user_id,
        created_token_id=ctx.actor.token_id,
        mcp_client=ctx.actor.mcp_client,
        provenance=_provenance(ctx, [k for k in ("description", "counterparty", "lines", "inputs") if data.get(k)])
        | ({"defaults": dict.fromkeys(applied, "counterparty")} if applied else {}),
        version=1,
    )
    set_occurred_at(txn, occurred_at)
    return txn, code


def set_occurred_at(txn: Transaction, occurred: datetime | None) -> None:
    txn.occurred_at = occurred
    offset = occurred.utcoffset() if occurred else None
    txn.occurred_offset_minutes = int(offset.total_seconds() // 60) if offset is not None else None


def _post(session: Session, ctx: RequestContext, book: Book, txn: Transaction, plan: Plan) -> JournalEntry:
    entry = ledger.write_entry(
        session,
        ctx,
        ledger.EntryRequest(
            transaction=txn,
            kind="posting",
            effective_date=txn.effective_date,
            journal_code=txn.inputs.get("journal_code") or book.journal_codes[0],
            description=txn.description,
            lines=plan.result.lines,
            fee_rule_ids=plan.fee_rule_ids,
        ),
    )
    txn.posted_entry_id = entry.id
    txn.posted_at = datetime.now(UTC)
    txn.posted_by = ctx.actor.user_id
    txn.computed = txn.computed | {"entry_number": entry.number}
    return entry


def create(session: Session, ctx: RequestContext, data: dict[str, Any]) -> tuple[Transaction, JournalEntry, Plan]:
    """Record a transaction: build its lines and post them. Line types take ``lines``; business types
    take ``inputs`` (see the type's input_schema)."""
    ctx.require(Scope.LEDGER_WRITE)
    txn, code = new_transaction(session, ctx, data)
    book = _book(session, txn.book_id)
    txn.number = transaction_number(session, book)
    session.add(txn)
    session.flush()
    if data.get("tags"):
        tags.set_tags(session, ctx, txn, data["tags"])
    plan = refresh(session, book, txn, code)
    audit.ensure_change_set(session, ctx, "transaction.create")
    txn.created_change_set_id = ctx.change_set_id
    entry = _post(session, ctx, book, txn, plan)
    if txn.inputs.get("original_id"):
        link(session, txn, txn.inputs["original_id"], "refund_of")
    session.flush()
    audit.record(session, ctx, "transaction.create", "transaction", txn.id, after=header_view(txn, code))
    return txn, entry, plan


def hypothetical(session: Session, ctx: RequestContext, data: dict[str, Any]) -> tuple[Transaction, str]:
    """What ``create`` would record (computed summary filled in), without saving anything."""
    txn, code = new_transaction(session, ctx, data)
    refresh(session, _book(session, txn.book_id), txn, code)
    return txn, code


def _counterparty_id(session: Session, book_id: str, ref: str | None) -> str | None:
    """Exact name or id; otherwise a NOT_FOUND carrying resolver candidates (domains, aliases)."""
    if not ref:
        return None
    try:
        return reference.get_counterparty(session, book_id, ref).id
    except DomainError as exc:
        candidates = reference.resolve_counterparty_text(session, book_id, ref)[:5]
        if candidates:
            exc.candidates = candidates
            exc.detail += " 可能是：" + "、".join(c["name"] for c in candidates) + "。"
        raise


def refresh(session: Session, book: Book, txn: Transaction, code: str) -> Plan:
    """Rebuild the lines: computed summary, estimate flag and (unless user-set) the description."""
    plan = build(session, book, txn, code)
    txn.computed = computed_summary(plan)
    txn.is_estimate = plan.is_estimate
    if is_business(code) and "description" not in txn.provenance:
        txn.description = business.default_description(session, book, txn, code, plan.computed)
    return plan


def computed_summary(plan: Plan) -> dict[str, Any]:
    return plan.computed | {
        "warnings": plan.warnings,
        "fx": list(plan.result.fx),
        "line_count": len(plan.result.lines),
    }


def load(session: Session, ctx: RequestContext, ref: str, *, lock: bool = False) -> tuple[Transaction, str]:
    book_id = ctx.require_book()
    stmt = select(Transaction, TransactionType.code).join(
        TransactionType, TransactionType.id == Transaction.transaction_type_id
    )
    stmt = stmt.where(Transaction.book_id == book_id)
    stmt = (
        stmt.where(Transaction.number == ref)
        if ref.startswith("T") and not ref.startswith("txn_")
        else stmt.where(Transaction.id == ref)
    )
    if lock:
        stmt = stmt.with_for_update(of=Transaction)
    row = session.execute(stmt).first()
    if row is None:
        raise not_found("交易", ref)
    return row[0], row[1]


def _load_live(
    session: Session, ctx: RequestContext, ref: str, expected_version: int | None
) -> tuple[Transaction, str]:
    txn, code = load(session, ctx, ref, lock=True)
    if expected_version is not None and txn.version != expected_version:
        raise version_conflict("交易", expected_version, txn.version)
    return txn, code


def edit(
    session: Session,
    ctx: RequestContext,
    ref: str,
    changes: dict[str, Any],
    expected_version: int | None = None,
) -> tuple[Transaction, Plan | None]:
    """Change a transaction; ``inputs`` may be partial (merged into the current ones, null removes a key).

    Header fields change in place. A change to the books (date, counterparty, inputs or lines) rebuilds
    the lines; if they, the date or the voucher prefix differ from the current entry, that entry is
    reversed and the new lines are posted on the same transaction. Returns the plan when rebuilt.
    """
    ctx.require(Scope.LEDGER_WRITE)
    txn, code = _load_live(session, ctx, ref, expected_version)
    if txn.status != "posted":
        raise DomainError(
            "INVALID_STATE",
            f"交易 {txn.number} 已删除，恢复后才能修改。",
            next_action={"operation": "transactions_restore", "mcp_tool": "restore_transaction"},
        )
    unknown = set(changes) - set(EDITABLE)
    if unknown:
        raise DomainError("VALIDATION_FAILED", f"不可修改的字段：{', '.join(sorted(unknown))}。")
    book = _book(session, txn.book_id)
    before = state_view(session, txn, code)
    if "counterparty" in changes:
        txn.counterparty_id = _counterparty_id(session, book.id, changes["counterparty"])
    if "lines" in changes:
        if is_business(code):
            raise DomainError("VALIDATION_FAILED", f"交易类型 {code} 不接受 lines，请修改 inputs。")
        txn.inputs = {**txn.inputs, "lines": normalise_lines(session, book, changes["lines"] or [])}
    if "inputs" in changes:
        if not is_business(code):
            raise DomainError("VALIDATION_FAILED", f"交易类型 {code} 不接受 inputs，请修改 lines。")
        header = {"counterparty_id": txn.counterparty_id}
        merged = merge_inputs(business.raw_inputs(session, txn.inputs), changes["inputs"] or {})
        txn.inputs = {"journal_code": txn.inputs.get("journal_code")} | business.normalise(
            session, book, code, merged, header
        )
        txn.counterparty_id = header["counterparty_id"]
        txn.default_dimensions = {"channel": txn.inputs["channel_id"]} if txn.inputs.get("channel_id") else {}
    if "allow_conversion" in changes:
        txn.inputs = {**txn.inputs, "allow_conversion": bool(changes["allow_conversion"])}
    if "journal_code" in changes:
        if changes["journal_code"] not in book.journal_codes:
            raise DomainError("VALIDATION_FAILED", "凭证字未在账套中定义。")
        txn.inputs = {**txn.inputs, "journal_code": changes["journal_code"]}
    if "occurred_at" in changes or "effective_date" in changes:
        occurred = changes.get("occurred_at", txn.occurred_at)
        set_occurred_at(txn, occurred)
        txn.effective_date = (
            _effective_date(book, changes.get("effective_date"), occurred)
            if ("effective_date" in changes or occurred)
            else txn.effective_date
        )
    if changes.get("external_ref") and changes["external_ref"] != txn.external_ref:
        _check_external_ref(session, book.id, changes["external_ref"])
    reset_description = "description" in changes and not (changes["description"] or "").strip()
    if reset_description and not is_business(code):
        raise DomainError("VALIDATION_FAILED", "手工凭证必须填写摘要，格式“调整 · 原因”。")
    for key in ("description", "external_ref", "order_no", "notes", "date_precision"):
        if key in changes:
            setattr(txn, key, changes[key])
    if "metadata" in changes:
        txn.metadata_ = changes["metadata"] or {}
    if "tags" in changes:
        tags.set_tags(session, ctx, txn, changes["tags"] or [])
    txn.provenance = {**txn.provenance, **_provenance(ctx, [k for k in changes if k != "tags"])}
    if reset_description:
        txn.provenance = {k: v for k, v in txn.provenance.items() if k != "description"}  # back to automatic
    plan = None
    if reset_description or set(changes) & set(BOOK_FIELDS):
        plan = refresh(session, book, txn, code)
        _repost_if_changed(session, ctx, book, txn, plan)
    txn.version += 1
    session.flush()
    audit.record(
        session,
        ctx,
        "transaction.update",
        "transaction",
        txn.id,
        before=before,
        after=state_view(session, txn, code),
    )
    return txn, plan


def merge_inputs(current: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge for partial edits: a key set to null is removed."""
    merged = dict(current)
    for key, value in changes.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _repost_if_changed(session: Session, ctx: RequestContext, book: Book, txn: Transaction, plan: Plan) -> None:
    current = session.get(JournalEntry, txn.posted_entry_id)
    assert current is not None
    journal_code = txn.inputs.get("journal_code") or book.journal_codes[0]
    if (
        current.effective_date == txn.effective_date
        and current.journal_code == journal_code
        and same_lines(ledger.load_built_lines(session, current.id), plan.result.lines)
    ):
        txn.computed = txn.computed | {"entry_number": current.number}
        return
    entry = rebook(
        session,
        ctx,
        txn,
        plan.result.lines,
        effective_date=txn.effective_date,
        journal_code=journal_code,
        fee_rule_ids=plan.fee_rule_ids,
        note="修改",
    )
    txn.computed = txn.computed | {"entry_number": entry.number}


def rebook(
    session: Session,
    ctx: RequestContext,
    txn: Transaction,
    lines: Sequence[BuiltLine],
    *,
    effective_date: date,
    journal_code: str,
    fee_rule_ids: Sequence[str],
    note: str,
) -> JournalEntry:
    """Reverse the transaction's current entry and post ``lines`` as its new entry."""
    current = session.get(JournalEntry, txn.posted_entry_id, with_for_update=True)
    assert current is not None
    reversal = ledger.write_entry(
        session,
        ctx,
        ledger.EntryRequest(
            transaction=txn,
            kind="repost_reversal",
            effective_date=current.effective_date,
            journal_code=current.journal_code,
            description=f"冲销 · {current.number} · {note}"[:200],
            lines=reverse_lines(ledger.load_built_lines(session, current.id)),
            reverses_entry_id=current.id,
        ),
    )
    current.reversed_by_entry_id = reversal.id
    entry = ledger.write_entry(
        session,
        ctx,
        ledger.EntryRequest(
            transaction=txn,
            kind="repost",
            effective_date=effective_date,
            journal_code=journal_code,
            description=txn.description,
            lines=lines,
            fee_rule_ids=fee_rule_ids,
        ),
    )
    txn.posted_entry_id = entry.id
    return entry


def delete(
    session: Session,
    ctx: RequestContext,
    ref: str,
    reason: str | None = None,
    expected_version: int | None = None,
) -> tuple[Transaction, JournalEntry]:
    """Delete a transaction: its current entry is reversed and it drops out of lists and reports.
    The ledger keeps both entries; ``restore`` (or undoing the change set) brings it back."""
    ctx.require(Scope.LEDGER_WRITE)
    txn, code = _load_live(session, ctx, ref, expected_version)
    if txn.status != "posted":
        raise DomainError("INVALID_STATE", f"交易 {txn.number} 已删除。")
    reason = (reason or "").strip() or None
    current = session.get(JournalEntry, txn.posted_entry_id, with_for_update=True)
    assert current is not None
    entry = ledger.write_entry(
        session,
        ctx,
        ledger.EntryRequest(
            transaction=txn,
            kind="reversal",
            effective_date=current.effective_date,
            journal_code=current.journal_code,
            description=f"删除 · {current.number}" + (f" · {reason}" if reason else ""),
            lines=reverse_lines(ledger.load_built_lines(session, current.id)),
            reverses_entry_id=current.id,
        ),
    )
    current.reversed_by_entry_id = entry.id
    before = header_view(txn, code)
    txn.status = "reversed"
    txn.reversed_at = datetime.now(UTC)
    txn.reverse_reason = reason
    txn.version += 1
    session.flush()
    audit.record(
        session,
        ctx,
        "transaction.delete",
        "transaction",
        txn.id,
        before=before,
        after=header_view(txn, code) | {"reversal_number": entry.number},
    )
    return txn, entry


def restore(
    session: Session, ctx: RequestContext, ref: str, expected_version: int | None = None
) -> tuple[Transaction, JournalEntry]:
    """Bring back a deleted transaction: the lines it had are posted again on their original date."""
    ctx.require(Scope.LEDGER_WRITE)
    txn, code = _load_live(session, ctx, ref, expected_version)
    if txn.status != "reversed":
        raise DomainError("INVALID_STATE", f"交易 {txn.number} 没有被删除。")
    last = session.get(JournalEntry, txn.posted_entry_id)
    assert last is not None
    entry = ledger.write_entry(
        session,
        ctx,
        ledger.EntryRequest(
            transaction=txn,
            kind="posting",
            effective_date=last.effective_date,
            journal_code=last.journal_code,
            description=txn.description,
            lines=ledger.load_built_lines(session, last.id),
            fee_rule_ids=last.fee_rule_ids,
        ),
    )
    before = header_view(txn, code)
    txn.status = "posted"
    txn.posted_entry_id = entry.id
    txn.posted_at = datetime.now(UTC)
    txn.posted_by = ctx.actor.user_id
    txn.reversed_at = None
    txn.reverse_reason = None
    txn.computed = txn.computed | {"entry_number": entry.number}
    txn.version += 1
    session.flush()
    audit.record(
        session, ctx, "transaction.restore", "transaction", txn.id, before=before, after=header_view(txn, code)
    )
    return txn, entry


def link(session: Session, txn: Transaction, target_id: str, kind: str, note: str | None = None) -> None:
    session.add(
        TransactionLink(
            id=new_id("tln"),
            book_id=txn.book_id,
            from_transaction_id=txn.id,
            to_transaction_id=target_id,
            kind=kind,
            note=note,
        )
    )


def stored_line_specs(session: Session, book: Book, rows: Sequence[dict[str, Any]]) -> list[LineSpec]:
    """Inverse of :func:`normalise_lines` (ids are accepted wherever codes are)."""
    scales = reference.commodity_scales(session)
    return [
        LineSpec(
            account=r["account_id"],
            side=r["side"],
            amount=str(from_minor(r["amount_minor"], scales[r["commodity"]])),
            commodity=r["commodity"],
            fx_rate=r.get("fx_rate"),
            base_amount=str(from_minor(r["base_amount_minor"], scales[book.base_commodity]))
            if r.get("base_amount_minor") is not None
            else None,
            counterparty=r.get("counterparty_id"),
            counterparty_account=r.get("counterparty_account_id"),
            dimensions=r.get("dimensions") or None,
            memo=r.get("memo"),
            quantity=r.get("quantity"),
            quantity_unit=r.get("quantity_unit"),
        )
        for r in rows
    ]


def _line_key(line: Any) -> tuple[Any, ...]:
    return (
        line.account_id,
        line.commodity,
        line.amount,
        line.base_amount,
        line.line_role,
        tuple(line.dimensions),
        line.counterparty_id,
        line.counterparty_account_id,
        line.quantity,
    )


def same_lines(a: Sequence[BuiltLine], b: Sequence[BuiltLine]) -> bool:
    return sorted(map(_line_key, a), key=repr) == sorted(map(_line_key, b), key=repr)


REPOSTABLE = FEE_TYPES  # every type whose fee can come from a rule


def repost_candidates(
    session: Session,
    ctx: RequestContext,
    *,
    ids: Sequence[str] = (),
    types: Sequence[str] = (),
    channels: Sequence[str] = (),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    lock: bool = False,
) -> list[tuple[Transaction, str]]:
    """Live transactions of fee-bearing types matching the filters, oldest first (limit + 1 rows)."""
    book_id = ctx.require_book()
    if set(types) - set(REPOSTABLE):
        raise DomainError("VALIDATION_FAILED", f"按新规则重算只适用于 {', '.join(REPOSTABLE)}。")
    stmt = (
        select(Transaction, TransactionType.code)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .where(
            Transaction.book_id == book_id,
            Transaction.status == "posted",
            TransactionType.code.in_(types or REPOSTABLE),
        )
    )
    if ids:
        stmt = stmt.where(Transaction.id.in_(ids) | Transaction.number.in_(ids))
    if channels:
        channel_ids = [reference.resolve_dimensions(session, book_id, {"channel": c})["channel"] for c in channels]
        stmt = stmt.where(Transaction.default_dimensions["channel"].astext.in_(channel_ids))
    if date_from:
        stmt = stmt.where(Transaction.effective_date >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.effective_date <= date_to)
    stmt = stmt.order_by(Transaction.effective_date, Transaction.id).limit(limit + 1)
    if lock:
        stmt = stmt.with_for_update(of=Transaction)
    return [(row[0], row[1]) for row in session.execute(stmt).all()]


def repost(
    session: Session,
    ctx: RequestContext,
    *,
    reason: str,
    ids: Sequence[str] = (),
    types: Sequence[str] = (),
    channels: Sequence[str] = (),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Rebuild transactions with the current fee rules and rates; where the lines differ, the current
    entry is reversed and the new lines are posted on the original date. Try it with dry_run first."""
    ctx.require(Scope.LEDGER_WRITE)
    reason = reason.strip()
    if len(reason) < 2:
        raise DomainError("VALIDATION_FAILED", "请写明重算原因（如“Stripe 费率调整”）。")
    book = _book(session, ctx.require_book())
    rows = repost_candidates(
        session,
        ctx,
        ids=ids,
        types=types,
        channels=channels,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        lock=True,
    )
    items: list[dict[str, Any]] = []
    unchanged = 0
    for txn, code in rows[:limit]:
        plan = build(session, book, txn, code)
        if same_lines(ledger.load_built_lines(session, txn.posted_entry_id or ""), plan.result.lines):
            unchanged += 1
            continue
        old_fee, new_fee = txn.computed.get("fee"), plan.computed.get("fee")
        before = state_view(session, txn, code)
        entry = rebook(
            session,
            ctx,
            txn,
            plan.result.lines,
            effective_date=txn.effective_date,
            journal_code=txn.inputs.get("journal_code") or book.journal_codes[0],
            fee_rule_ids=plan.fee_rule_ids,
            note=reason,
        )
        txn.computed = computed_summary(plan) | {"entry_number": entry.number}
        txn.is_estimate = plan.is_estimate
        txn.version += 1
        session.flush()
        audit.record(
            session,
            ctx,
            "transaction.repost",
            "transaction",
            txn.id,
            before=before,
            after=state_view(session, txn, code) | {"reason": reason},
        )
        items.append(
            {
                "id": txn.id,
                "number": txn.number,
                "type": code,
                "effective_date": txn.effective_date.isoformat(),
                "commodity": plan.computed.get("commodity"),
                "old_fee": old_fee,
                "new_fee": new_fee,
                "fee_delta": (new_fee or 0) - (old_fee or 0),
                "fee_rule": plan.computed.get("fee_rule"),
                "entry_number": entry.number,
            }
        )
    return {
        "checked": min(len(rows), limit),
        "unchanged": unchanged,
        "reposted": len(items),
        "fee_delta": sum(i["fee_delta"] for i in items),
        "truncated": len(rows) > limit,
        "items": items,
    }


def header_view(txn: Transaction, type_code: str) -> dict[str, Any]:
    return {
        "id": txn.id,
        "number": txn.number,
        "type": type_code,
        "status": txn.status,
        "effective_date": txn.effective_date.isoformat(),
        "occurred_at": txn.occurred_at.isoformat() if txn.occurred_at else None,
        "date_precision": txn.date_precision,
        "description": txn.description,
        "counterparty_id": txn.counterparty_id,
        "channel_id": txn.default_dimensions.get("channel"),
        "amount": txn.computed.get("headline"),
        "external_ref": txn.external_ref,
        "order_no": txn.order_no,
        "is_estimate": txn.is_estimate,
        "created_channel": txn.created_channel,
        "posted_entry_id": txn.posted_entry_id,
        "reverse_reason": txn.reverse_reason,
        "notes": txn.notes,
        "version": txn.version,
    }


def state_view(session: Session, txn: Transaction, type_code: str) -> dict[str, Any]:
    """Everything needed to put a transaction back as it was (audit before / after of edits)."""
    return header_view(txn, type_code) | {
        "inputs": txn.inputs,
        "computed": txn.computed,
        "default_dimensions": txn.default_dimensions,
        "metadata": txn.metadata_,
        "provenance": txn.provenance,
        "tags": tags.tags_for(session, [txn.id]).get(txn.id, []),
    }


def entry_lines_view(session: Session, entry_ids: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    if not entry_ids:
        return {}
    scales = reference.commodity_scales(session)
    symbols = {c: x.symbol for c, x in reference.commodities_by_code(session).items()}
    rows = session.execute(
        select(JournalLine, Account.code, Account.name, Counterparty.name)
        .join(Account, Account.id == JournalLine.account_id)
        .outerjoin(Counterparty, Counterparty.id == JournalLine.counterparty_id)
        .where(JournalLine.entry_id.in_(entry_ids))
        .order_by(JournalLine.entry_id, JournalLine.line_no)
    ).all()
    dims: dict[str, dict[str, str]] = {}
    for line_id, value_code, value_name in session.execute(
        select(JournalLineDimension.line_id, DimensionValue.code, DimensionValue.name)
        .join(DimensionValue, DimensionValue.id == JournalLineDimension.dimension_value_id)
        .join(JournalLine, JournalLine.id == JournalLineDimension.line_id)
        .where(JournalLine.entry_id.in_(entry_ids))
    ).all():
        dims.setdefault(line_id, {})[value_code] = value_name
    result: dict[str, list[dict[str, Any]]] = {}
    for line, code, name, cp_name in rows:
        scale = scales[line.commodity]
        result.setdefault(line.entry_id, []).append(
            {
                "id": line.id,
                "line_no": line.line_no,
                "account_id": line.account_id,
                "account_code": code,
                "account_name": name,
                "commodity": line.commodity,
                "amount": money_view(line.amount, line.commodity, scale, symbols.get(line.commodity)),
                "base_amount": line.base_amount,
                "fx_rate": str(line.fx_rate) if line.fx_rate is not None else None,
                "fx_source": line.fx_source,
                "counterparty": cp_name,
                "dimensions": dims.get(line.id, {}),
                "memo": line.memo,
                "line_role": line.line_role,
                "quantity": str(line.quantity) if line.quantity is not None else None,
                "quantity_unit": line.quantity_unit,
                "balance_after": line.balance_after,
            }
        )
    return result


def money_view(minor: int, commodity: str, scale: int, symbol: str | None) -> dict[str, Any]:
    return {
        "minor": minor,
        "commodity": commodity,
        "display": format_amount(minor, scale, symbol, commodity),
    }


def entry_view(entry: JournalEntry, lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": entry.id,
        "seq": entry.seq,
        "number": entry.number,
        "kind": entry.kind,
        "transaction_id": entry.transaction_id,
        "effective_date": entry.effective_date.isoformat(),
        "recorded_at": entry.recorded_at.isoformat(),
        "description": entry.description,
        "reverses_entry_id": entry.reverses_entry_id,
        "reversed_by_entry_id": entry.reversed_by_entry_id,
        "channel": entry.channel,
        "hash": bytes(entry.hash).hex(),
        "lines": lines,
    }


def preview_lines(session: Session, result: BuildResult) -> list[dict[str, Any]]:
    """Lines of a plan that has not been posted (hypothetical entries)."""
    scales = reference.commodity_scales(session)
    symbols = {c: x.symbol for c, x in reference.commodities_by_code(session).items()}
    codes = dict(
        session.execute(
            select(Account.id, Account.name).where(Account.id.in_({line.account_id for line in result.lines}))
        ).all()
    )
    return [
        {
            "line_no": line.line_no,
            "account_code": line.account_code,
            "account_name": codes.get(line.account_id),
            "commodity": line.commodity,
            "amount": money_view(line.amount, line.commodity, scales[line.commodity], symbols.get(line.commodity)),
            "base_amount": line.base_amount,
            "fx_rate": str(line.fx_rate) if line.fx_rate is not None else None,
            "fx_source": line.fx_source,
            "line_role": line.line_role,
            "memo": line.memo,
            "dimensions": dict(line.dimensions),
        }
        for line in result.lines
    ]


def full_view(session: Session, txn: Transaction, type_code: str) -> dict[str, Any]:
    entries = list(
        session.execute(
            select(JournalEntry).where(JournalEntry.transaction_id == txn.id).order_by(JournalEntry.seq)
        ).scalars()
    )
    lines = entry_lines_view(session, [e.id for e in entries])
    counterparty = session.get(Counterparty, txn.counterparty_id) if txn.counterparty_id else None
    channel_id = txn.default_dimensions.get("channel")
    channel = session.get(DimensionValue, channel_id) if channel_id else None
    data = header_view(txn, type_code) | {
        "counterparty": {"id": counterparty.id, "name": counterparty.name} if counterparty else None,
        "channel": {"id": channel.id, "code": channel.code, "name": channel.name} if channel else None,
        "inputs": txn.inputs,
        "computed": txn.computed,
        "provenance": txn.provenance,
        "metadata": txn.metadata_,
        "links": links_view(session, txn.id),
        "tags": tags.tags_for(session, [txn.id]).get(txn.id, []),
        "sources": _evidence(session, txn.id),
        "entries": [entry_view(e, lines.get(e.id, [])) for e in entries],
        "fee_rule": _fee_view(session, type_code, txn),
    }
    return data


def explain(session: Session, txn: Transaction, type_code: str) -> dict[str, Any]:
    book = _book(session, txn.book_id)
    if is_business(type_code):
        data = business.explain(session, book, txn, type_code)
    else:
        data = {
            "type": type_code,
            "inputs": {"lines": len(txn.inputs.get("lines", []))},
            "computed": txn.computed,
            "warnings": txn.computed.get("warnings", []),
            "fx": txn.computed.get("fx", []),
        }
    if txn.posted_entry_id:
        data["lines"] = entry_lines_view(session, [txn.posted_entry_id]).get(txn.posted_entry_id, [])
    else:  # hypothetical: built but not saved
        data["lines"] = preview_lines(session, build(session, book, txn, type_code).result)
    data["links"] = links_view(session, txn.id)
    return data


def _evidence(session: Session, txn_id: str) -> list[dict[str, Any]]:
    from bookkeeper.services import imports  # imports depends on this module

    return imports.evidence_for(session, txn_id)


def links_view(session: Session, txn_id: str) -> list[dict[str, Any]]:
    """Related transactions in both directions (refunds), with enough to display."""
    rows = session.execute(
        select(TransactionLink, Transaction, TransactionType.code)
        .join(
            Transaction,
            ((TransactionLink.from_transaction_id == txn_id) & (Transaction.id == TransactionLink.to_transaction_id))
            | ((TransactionLink.to_transaction_id == txn_id) & (Transaction.id == TransactionLink.from_transaction_id)),
        )
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .order_by(TransactionLink.created_at)
    ).all()
    labels = {
        ("refund_of", True): "退款自",
        ("refund_of", False): "退款",
        ("related", True): "关联",
        ("related", False): "关联",
    }
    return [
        {
            "kind": link.kind,
            "direction": "outgoing" if link.from_transaction_id == txn_id else "incoming",
            "label": labels[(link.kind, link.from_transaction_id == txn_id)],
            "note": link.note,
            "transaction": {
                "id": other.id,
                "number": other.number,
                "type": code,
                "status": other.status,
                "effective_date": other.effective_date.isoformat(),
                "description": other.description,
                "amount": other.computed.get("headline"),
            },
        }
        for link, other, code in rows
    ]


def search(
    session: Session,
    ctx: RequestContext,
    *,
    status: str | None,
    type_code: str | None,
    date_from: date | None,
    date_to: date | None,
    counterparty: str | None,
    text: str | None,
    created_channel: str | None,
    cursor: tuple[str, str] | None,
    limit: int,
    channel: str | None = None,
    account: str | None = None,
    amount_min: int | None = None,
    amount_max: int | None = None,
    is_estimate: bool | None = None,
    linked_to: str | None = None,
    tag: str | None = None,
    commodity: str | None = None,
) -> list[tuple[Transaction, str]]:
    """Filters combine with AND. ``account`` matches transactions whose current entry touches the
    account or any of its children; ``commodity`` those with a line in that currency (on that account
    when both are given); amounts are minor units of the headline amount."""
    book_id = ctx.require_book()
    stmt = (
        select(Transaction, TransactionType.code)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .where(Transaction.book_id == book_id)
    )
    if status:
        stmt = stmt.where(Transaction.status == status)
    if type_code:
        stmt = stmt.where(TransactionType.code.in_([c.strip() for c in type_code.split(",") if c.strip()]))
    if date_from:
        stmt = stmt.where(Transaction.effective_date >= date_from)
    if date_to:
        stmt = stmt.where(Transaction.effective_date <= date_to)
    if counterparty:
        stmt = stmt.where(Transaction.counterparty_id == reference.get_counterparty(session, book_id, counterparty).id)
    if created_channel:
        stmt = stmt.where(Transaction.created_channel == created_channel)
    if channel:
        channel_id = reference.resolve_dimensions(session, book_id, {"channel": channel})["channel"]
        stmt = stmt.where(Transaction.default_dimensions["channel"].astext == channel_id)
    if account or commodity:
        line = select(JournalLine.id).where(JournalLine.entry_id == Transaction.posted_entry_id)
        if account:
            acc = accounts.get_account(session, book_id, account)
            tree = select(Account.id).where(
                Account.book_id == book_id, (Account.id == acc.id) | Account.code.startswith(acc.code + ".")
            )
            line = line.where(JournalLine.account_id.in_(tree))
        if commodity:
            line = line.where(JournalLine.commodity == commodity.strip().upper())
        stmt = stmt.where(line.exists())
    headline_minor = Transaction.computed["headline"]["minor"].as_integer()
    if amount_min is not None:
        stmt = stmt.where(headline_minor >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(headline_minor <= amount_max)
    if is_estimate is not None:
        stmt = stmt.where(Transaction.is_estimate.is_(is_estimate))
    if tag:
        stmt = stmt.where(Transaction.id.in_(tags.tagged([tag])))
    if linked_to:
        target, _code = load(session, ctx, linked_to)
        linked = (
            select(TransactionLink.from_transaction_id)
            .where(TransactionLink.to_transaction_id == target.id)
            .union(select(TransactionLink.to_transaction_id).where(TransactionLink.from_transaction_id == target.id))
        )
        stmt = stmt.where(Transaction.id.in_(linked))
    if text:
        like = f"%{text.strip()}%"
        stmt = stmt.where(
            Transaction.description.ilike(like) | Transaction.number.ilike(like) | Transaction.order_no.ilike(like)
        )
    if cursor:
        stmt = stmt.where(
            tuple_(Transaction.effective_date, Transaction.id) < tuple_(date.fromisoformat(cursor[0]), cursor[1])
        )
    stmt = stmt.order_by(Transaction.effective_date.desc(), Transaction.id.desc()).limit(limit + 1)
    return [(row[0], row[1]) for row in session.execute(stmt).all()]


def _fee_view(session: Session, type_code: str, txn: Transaction) -> dict[str, Any] | None:
    """Which fee rule this transaction used, or that its fee was given, or that no rule matched (fee 0)."""
    from bookkeeper.db.models import FeeRuleRow
    from bookkeeper.services import fees

    used = (txn.computed or {}).get("fee_rule") or {}
    found = fees.basis(type_code, txn.inputs or {}, used.get("id"))
    if found is None:
        return None
    row = session.get(FeeRuleRow, used["id"]) if used.get("id") else None
    return {"basis": found, "rule": fees.rule_brief(row) if found == "rule" else None}
