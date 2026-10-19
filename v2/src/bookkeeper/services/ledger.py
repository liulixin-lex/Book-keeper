"""Writes journal entries: numbering, hash chain, balances, daily activity (docs/03 §4.3)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Account,
    AccountBalance,
    DailyBalance,
    DimensionType,
    JournalEntry,
    JournalLine,
    JournalLineDimension,
    LedgerHead,
    NumberSequence,
    Transaction,
)
from bookkeeper.domain.canonical import chain_hash, genesis_hash
from bookkeeper.domain.errors import DomainError, FieldError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.ledger import ENGINE_VERSION, BuiltLine, entry_hash_payload
from bookkeeper.services.context import RequestContext


def next_number(session: Session, book_id: str, scope: str, period: str) -> int:
    session.execute(
        insert(NumberSequence)
        .values(book_id=book_id, scope=scope, period=period, next_value=1)
        .on_conflict_do_nothing(index_elements=["book_id", "scope", "period"])
    )
    row = session.execute(
        select(NumberSequence)
        .where(
            NumberSequence.book_id == book_id,
            NumberSequence.scope == scope,
            NumberSequence.period == period,
        )
        .with_for_update()
    ).scalar_one()
    value = row.next_value
    row.next_value = value + 1
    return value


def _lock_head(session: Session, book_id: str) -> LedgerHead:
    session.execute(
        insert(LedgerHead)
        .values(book_id=book_id, last_seq=0, last_entry_hash=genesis_hash("ledger", book_id))
        .on_conflict_do_nothing(index_elements=["book_id"])
    )
    return session.execute(select(LedgerHead).where(LedgerHead.book_id == book_id).with_for_update()).scalar_one()


def _check_balance_rules(
    session: Session,
    book_id: str,
    lines: Sequence[BuiltLine],
    balances: dict[tuple[str, str], AccountBalance],
) -> None:
    deltas: dict[tuple[str, str], int] = {}
    for line in lines:
        key = (line.account_id, line.commodity)
        deltas[key] = deltas.get(key, 0) + line.amount
    account_ids = {k[0] for k in deltas}
    accounts = {a.id: a for a in session.execute(select(Account).where(Account.id.in_(account_ids))).scalars()}
    errors = []
    for (account_id, commodity), delta in deltas.items():
        account = accounts[account_id]
        if account.balance_rule != "normal_side_only":
            continue
        projected = balances[(account_id, commodity)].balance + delta
        wrong = projected < 0 if account.normal_side == "debit" else projected > 0
        if wrong:
            errors.append(
                FieldError(
                    "lines",
                    "BALANCE_RULE_VIOLATION",
                    f"科目 {account.code} {account.name} 的 {commodity} 余额将出现反向",
                )
            )
    if errors:
        raise DomainError("BALANCE_RULE_VIOLATION", errors[0].message + "。", errors=errors)


@dataclass(frozen=True)
class EntryRequest:
    transaction: Transaction
    kind: str
    effective_date: date
    journal_code: str
    description: str
    lines: Sequence[BuiltLine]
    reverses_entry_id: str | None = None
    template_id: str | None = None
    fee_rule_ids: Sequence[str] = ()


def write_entry(session: Session, ctx: RequestContext, request: EntryRequest) -> JournalEntry:
    """Persist one balanced entry: number, hash chain, balances and daily activity."""
    book_id = ctx.require_book()
    balances = _lock_balances(session, book_id, request.lines)
    _check_balance_rules(session, book_id, request.lines, balances)
    head = _lock_head(session, book_id)
    seq = head.last_seq + 1
    yyyymm = f"{request.effective_date.year}{request.effective_date.month:02d}"
    number = f"{request.journal_code}-{yyyymm}-{next_number(session, book_id, request.journal_code, yyyymm):04d}"
    recorded_at = session.execute(select(func.now())).scalar_one()
    entry_id = new_id("jen")
    lines = sorted(request.lines, key=lambda line: line.line_no)
    payload = entry_hash_payload(
        book_id=book_id,
        seq=seq,
        entry_id=entry_id,
        number=number,
        transaction_id=request.transaction.id,
        kind=request.kind,
        journal_code=request.journal_code,
        effective_date=request.effective_date,
        recorded_at=recorded_at,
        reverses_entry_id=request.reverses_entry_id,
        template_id=request.template_id,
        fee_rule_ids=request.fee_rule_ids,
        lines=lines,
    )
    entry_hash = chain_hash(head.last_entry_hash, payload)
    entry = JournalEntry(
        id=entry_id,
        book_id=book_id,
        seq=seq,
        transaction_id=request.transaction.id,
        kind=request.kind,
        journal_code=request.journal_code,
        number=number,
        effective_date=request.effective_date,
        recorded_at=recorded_at,
        template_id=request.template_id,
        fee_rule_ids=list(request.fee_rule_ids),
        engine_version=ENGINE_VERSION,
        description=request.description,
        reverses_entry_id=request.reverses_entry_id,
        line_count=len(lines),
        created_by_user_id=ctx.actor.user_id,
        created_token_id=ctx.actor.token_id,
        channel=ctx.channel,
        change_set_id=ctx.change_set_id,
        prev_hash=head.last_entry_hash,
        hash=entry_hash,
    )
    session.add(entry)
    session.flush()
    dim_types = _dimension_type_ids(session, book_id, lines)
    line_rows: list[dict[str, Any]] = []
    dim_rows: list[dict[str, Any]] = []
    daily: dict[tuple[str, str], list[int]] = {}
    for line in lines:
        balance = balances[(line.account_id, line.commodity)]
        balance.balance += line.amount
        balance.base_balance += line.base_amount
        if line.amount > 0:
            balance.debit_total += line.amount
        else:
            balance.credit_total -= line.amount
        if line.base_amount > 0:
            balance.base_debit_total += line.base_amount
        else:
            balance.base_credit_total -= line.base_amount
        balance.line_count += 1
        balance.last_seq = seq
        line_id = new_id("jln")
        line_rows.append(
            {
                "id": line_id,
                "book_id": book_id,
                "entry_id": entry_id,
                "line_no": line.line_no,
                "account_id": line.account_id,
                "commodity": line.commodity,
                "amount": line.amount,
                "base_amount": line.base_amount,
                "fx_rate": line.fx_rate,
                "fx_rate_id": line.fx_rate_id,
                "fx_source": line.fx_source,
                "quantity": line.quantity,
                "quantity_unit": line.quantity_unit,
                "counterparty_id": line.counterparty_id,
                "counterparty_account_id": line.counterparty_account_id,
                "memo": line.memo,
                "line_role": line.line_role,
                "effective_date": request.effective_date,
                "account_seq": balance.line_count,
                "balance_after": balance.balance,
                "base_balance_after": balance.base_balance,
            }
        )
        for type_code, value_id in line.dimensions:
            dim_rows.append(
                {
                    "line_id": line_id,
                    "dimension_type_id": dim_types[type_code],
                    "dimension_value_id": value_id,
                    "book_id": book_id,
                }
            )
        bucket = daily.setdefault((line.account_id, line.commodity), [0, 0, 0, 0, 0])
        bucket[0] += max(line.amount, 0)
        bucket[1] += max(-line.amount, 0)
        bucket[2] += max(line.base_amount, 0)
        bucket[3] += max(-line.base_amount, 0)
        bucket[4] += 1
    session.execute(insert(JournalLine), line_rows)
    if dim_rows:
        session.execute(insert(JournalLineDimension), dim_rows)
    for (account_id, commodity), (debit, credit, base_debit, base_credit, count) in daily.items():
        stmt = insert(DailyBalance).values(
            account_id=account_id,
            commodity=commodity,
            date=request.effective_date,
            book_id=book_id,
            debit=debit,
            credit=credit,
            base_debit=base_debit,
            base_credit=base_credit,
            line_count=count,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["account_id", "commodity", "date"],
                set_={
                    "debit": DailyBalance.debit + stmt.excluded.debit,
                    "credit": DailyBalance.credit + stmt.excluded.credit,
                    "base_debit": DailyBalance.base_debit + stmt.excluded.base_debit,
                    "base_credit": DailyBalance.base_credit + stmt.excluded.base_credit,
                    "line_count": DailyBalance.line_count + stmt.excluded.line_count,
                },
            )
        )
    head.last_seq = seq
    head.last_entry_hash = entry_hash
    head.updated_at = recorded_at
    session.flush()
    return entry


def _lock_balances(session: Session, book_id: str, lines: Sequence[BuiltLine]) -> dict[tuple[str, str], AccountBalance]:
    keys = sorted({(line.account_id, line.commodity) for line in lines})
    for account_id, commodity in keys:
        session.execute(
            insert(AccountBalance)
            .values(account_id=account_id, commodity=commodity, book_id=book_id)
            .on_conflict_do_nothing(index_elements=["account_id", "commodity"])
        )
    rows = session.execute(
        select(AccountBalance)
        .where(AccountBalance.account_id.in_({k[0] for k in keys}))
        .order_by(AccountBalance.account_id, AccountBalance.commodity)
        .with_for_update()
    ).scalars()
    return {(r.account_id, r.commodity): r for r in rows if (r.account_id, r.commodity) in set(keys)}


def _dimension_type_ids(session: Session, book_id: str, lines: Sequence[BuiltLine]) -> dict[str, str]:
    codes = {code for line in lines for code, _ in line.dimensions}
    if not codes:
        return {}
    rows = session.execute(
        select(DimensionType.code, DimensionType.id).where(
            DimensionType.book_id == book_id, DimensionType.code.in_(codes)
        )
    ).all()
    return dict(rows)


def load_built_lines(session: Session, entry_id: str) -> list[BuiltLine]:
    return load_lines_for_entries(session, [entry_id]).get(entry_id, [])


def load_lines_for_entries(session: Session, entry_ids: Sequence[str]) -> dict[str, list[BuiltLine]]:
    """Journal lines of several entries as BuiltLine, in three queries."""
    if not entry_ids:
        return {}
    table = JournalLine.__table__
    lines = session.execute(
        select(table).where(table.c.entry_id.in_(entry_ids)).order_by(table.c.entry_id, table.c.line_no)
    ).all()
    dims: dict[str, list[tuple[str, str]]] = {}
    for line_id, code, value_id in session.execute(
        select(
            JournalLineDimension.line_id,
            DimensionType.code,
            JournalLineDimension.dimension_value_id,
        )
        .join(DimensionType, DimensionType.id == JournalLineDimension.dimension_type_id)
        .join(JournalLine, JournalLine.id == JournalLineDimension.line_id)
        .where(JournalLine.entry_id.in_(entry_ids))
    ).all():
        dims.setdefault(line_id, []).append((code, value_id))
    codes = dict(
        session.execute(
            select(Account.id, Account.code).where(Account.id.in_({line.account_id for line in lines}))
        ).all()
    )
    result: dict[str, list[BuiltLine]] = {}
    for line in lines:
        result.setdefault(line.entry_id, []).append(
            BuiltLine(
                line_no=line.line_no,
                account_id=line.account_id,
                account_code=codes[line.account_id],
                commodity=line.commodity,
                amount=line.amount,
                base_amount=line.base_amount,
                fx_rate=line.fx_rate,
                fx_rate_id=line.fx_rate_id,
                fx_source=line.fx_source,
                counterparty_id=line.counterparty_id,
                counterparty_account_id=line.counterparty_account_id,
                dimensions=tuple(sorted(dims.get(line.id, []))),
                memo=line.memo,
                quantity=line.quantity,
                quantity_unit=line.quantity_unit,
                line_role=line.line_role,
            )
        )
    return result


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    entries: int
    first_bad_seq: int | None = None
    reason: str | None = None


def verify_chain(session: Session, book_id: str, batch: int = 500) -> ChainResult:
    prev = genesis_hash("ledger", book_id)
    expected = 1
    last = 0
    while True:
        table = JournalEntry.__table__
        entries = session.execute(
            select(table).where(table.c.book_id == book_id, table.c.seq > last).order_by(table.c.seq).limit(batch)
        ).all()
        if not entries:
            break
        batch_lines = load_lines_for_entries(session, [e.id for e in entries])
        for entry in entries:
            if entry.seq != expected:
                return ChainResult(False, expected - 1, expected, "sequence gap")
            if bytes(entry.prev_hash) != prev:
                return ChainResult(False, expected - 1, entry.seq, "prev_hash mismatch")
            payload = entry_hash_payload(
                book_id=book_id,
                seq=entry.seq,
                entry_id=entry.id,
                number=entry.number,
                transaction_id=entry.transaction_id,
                kind=entry.kind,
                journal_code=entry.journal_code,
                effective_date=entry.effective_date,
                recorded_at=entry.recorded_at,
                reverses_entry_id=entry.reverses_entry_id,
                template_id=entry.template_id,
                fee_rule_ids=entry.fee_rule_ids,
                lines=batch_lines.get(entry.id, []),
            )
            if chain_hash(prev, payload) != bytes(entry.hash):
                return ChainResult(False, expected - 1, entry.seq, "hash mismatch")
            prev = bytes(entry.hash)
            expected += 1
            last = entry.seq
    head = session.get(LedgerHead, book_id)
    if head is not None and (head.last_seq != last or bytes(head.last_entry_hash) != prev):
        return ChainResult(False, last, last + 1, "head mismatch")
    return ChainResult(True, last)
