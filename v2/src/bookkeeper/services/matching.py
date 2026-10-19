"""Matching services (docs/06 §7): suggestions between records and transactions, and pairing between
records of different sources (e.g. card-shop orders ↔ upstream redemptions) with the optimal DP."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Counterparty,
    ImportBatch,
    ImportSource,
    MatchExclusion,
    MatchSuggestion,
    PairingRule,
    SourceRecord,
    Transaction,
    TransactionSource,
    TransactionType,
)
from bookkeeper.domain import matching as algo
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit, transactions
from bookkeeper.services.context import RequestContext

TXN_DIRECTION = {
    "sale": "in",
    "purchase_refund": "in",
    "sale_refund": "out",
    "credit_purchase": "out",
    "expense": "out",
}
DEFAULT_MATCH: dict[str, Any] = {
    "days_before": 3,
    "days_after": 3,
    "tolerance_abs": 0,
    "tolerance_pct": "0",
    "auto": True,
}


def suggestion_view(s: MatchSuggestion) -> dict[str, Any]:
    return {
        "id": s.id,
        "kind": s.kind,
        "record_id": s.record_id,
        "other_record_id": s.other_record_id,
        "transaction_id": s.transaction_id,
        "pairing_rule_id": s.pairing_rule_id,
        "score": float(s.score),
        "method": s.method,
        "components": s.components,
        "status": s.status,
        "decided_at": s.decided_at.isoformat() if s.decided_at else None,
    }


def supersede(session: Session, record_id: str) -> None:
    for s in session.execute(
        select(MatchSuggestion).where(
            (MatchSuggestion.record_id == record_id) | (MatchSuggestion.other_record_id == record_id),
            MatchSuggestion.status == "pending",
        )
    ).scalars():
        s.status = "superseded"


def _excluded(session: Session, book_id: str) -> set[tuple[str, str]]:
    return {
        (a, b)
        for a, b in session.execute(
            select(MatchExclusion.left_id, MatchExclusion.right_id).where(MatchExclusion.book_id == book_id)
        ).all()
    }


def match_records(session: Session, ctx: RequestContext, records: Sequence[SourceRecord]) -> None:
    """Suggest existing transactions for records (while staged; nothing is linked until commit)."""
    candidates_records = [r for r in records if r.direction in ("in", "out") and not r.transaction_id]
    if not candidates_records:
        return
    book_id = candidates_records[0].book_id
    sources = {s.id: s for s in session.execute(select(ImportSource).where(ImportSource.book_id == book_id)).scalars()}
    lo = min(r.effective_date for r in candidates_records) - timedelta(days=10)
    hi = max(r.effective_date for r in candidates_records) + timedelta(days=10)
    rows = session.execute(
        select(Transaction, TransactionType.code, Counterparty.name)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .outerjoin(Counterparty, Counterparty.id == Transaction.counterparty_id)
        .where(
            Transaction.book_id == book_id,
            Transaction.status == "posted",
            Transaction.effective_date >= lo,
            Transaction.effective_date <= hi,
        )
    ).all()
    linked: dict[str, set[str]] = defaultdict(set)  # txn id → source ids already linked
    if rows:
        for txn_id, source_id in session.execute(
            select(TransactionSource.transaction_id, SourceRecord.source_id)
            .join(SourceRecord, SourceRecord.id == TransactionSource.source_record_id)
            .where(TransactionSource.transaction_id.in_([t.id for t, _c, _n in rows]))
        ).all():
            linked[txn_id].add(source_id)
    excluded = _excluded(session, book_id)
    for rec in candidates_records:
        src = sources[rec.source_id]
        cfg = DEFAULT_MATCH | dict(src.config.get("match") or {})
        if cfg.get("enabled") is False:
            continue
        tolerance = max(int(cfg["tolerance_abs"]), int(Decimal(str(cfg["tolerance_pct"])) * rec.amount_minor / 100))
        record_c = algo.Candidate(
            rec.id,
            rec.amount_minor,
            rec.effective_date,
            rec.counterparty_text or "",
            rec.order_no or rec.reference or "",
        )
        ranked: list[algo.Scored] = []
        for txn, code, cp_name in rows:
            headline = txn.computed.get("headline") or {}
            if TXN_DIRECTION.get(code) != rec.direction or headline.get("commodity") != rec.commodity:
                continue
            days = (txn.effective_date - rec.effective_date).days
            if days < -int(cfg["days_before"]) or days > int(cfg["days_after"]):
                continue
            if abs(int(headline.get("minor", 0)) - rec.amount_minor) > tolerance:
                continue
            if rec.source_id in linked[txn.id] or (rec.id, txn.id) in excluded:
                continue
            txn_c = algo.Candidate(
                txn.id,
                int(headline["minor"]),
                txn.effective_date,
                cp_name or txn.description,
                txn.order_no or "",
                txn.external_ref or "",
            )
            same_party = bool(
                cp_name and rec.counterparty_text and algo.similarity(cp_name, rec.counterparty_text) > 0.8
            )
            ranked.append(algo.score(record_c, txn_c, tolerance=max(tolerance, 1), same_counterparty=same_party))
        ranked.sort(key=lambda s: -s.score)
        decision = (
            algo.decide(ranked)
            if cfg.get("auto", True)
            else ("pending" if ranked and ranked[0].score >= 0.6 else "none")
        )
        if decision == "none":
            continue
        supersede(session, rec.id)
        for i, scored in enumerate(ranked[:3]):
            if scored.score < 0.6:
                break
            status = "auto_accepted" if (i == 0 and decision == "auto_accepted") else "pending"
            session.add(
                MatchSuggestion(
                    id=new_id("msg"),
                    book_id=book_id,
                    kind="record_transaction",
                    record_id=rec.id,
                    transaction_id=scored.id,
                    score=Decimal(str(scored.score)),
                    method=scored.method,
                    components=scored.components,
                    status=status,
                    decided_at=datetime.now(UTC) if status == "auto_accepted" else None,
                )
            )
            if status == "auto_accepted":
                rec.transaction_id = scored.id
                rec.status = "matched"
                break
    session.flush()


# ------------------------------------------------------------------ proposals already in the books

# The amount that identifies a transaction of each type; credit purchases compare face value first, because
# evidence such as a redeem log knows the credits received but not what was paid. Credits themselves (UCR records
# against a booking's credit_quantity) come before even that: ¥100 can buy $103, so face value can't tell.
PRINCIPAL: dict[str, tuple[str, ...]] = {
    "sale": ("gross",),
    "expense": ("amount",),
    "credit_purchase": ("face", "total"),
    "sale_refund": ("amount",),
    "purchase_refund": ("amount",),
    "transfer": ("amount_out",),
}


def _proposed(
    session: Session, rec: SourceRecord, scales: dict[str, int]
) -> tuple[str, str | None, str | None, list[tuple[str, int, str]]] | None:
    """(type, counterparty id, channel id, [(field, minor, commodity)…]) for a record's proposed transaction."""
    from bookkeeper.services import reference

    c = rec.classification or {}
    type_code = c.get("type")
    if type_code not in PRINCIPAL:
        return None
    inputs = c.get("inputs") or {}
    amounts: list[tuple[str, int, str]] = []
    if type_code == "credit_purchase" and rec.commodity == "UCR" and inputs.get("credit_quantity"):
        credits = _credits(inputs["credit_quantity"], scales)
        if credits is not None:
            amounts.append(("credit_quantity", credits, "UCR"))
    for name in PRINCIPAL[type_code]:
        value = inputs.get(name)
        if isinstance(value, dict) and value.get("amount") not in (None, ""):
            commodity = str(value.get("commodity") or rec.commodity)
        elif isinstance(value, str | int | float) and str(value).strip():
            value, commodity = {"amount": value}, rec.commodity
        else:
            continue
        try:
            minor = int(Decimal(str(value["amount"])) * 10 ** scales.get(commodity, 2))
        except ArithmeticError, ValueError:
            continue
        amounts.append((name, minor, commodity))
    if not amounts:
        return None
    cp_id = None
    if c.get("counterparty"):
        try:
            cp_id = reference.get_counterparty(session, rec.book_id, str(c["counterparty"])).id
        except DomainError:
            cp_id = None
    if cp_id is None and (c.get("counterparty") or (rec.counterparty_text or "").strip()):
        return None  # names a party the books don't know: it can't be one of their bookings — a new record
    channel_id = None
    if inputs.get("channel"):
        try:
            channel_id = reference.resolve_dimensions(session, rec.book_id, {"channel": str(inputs["channel"])})[
                "channel"
            ]
        except DomainError:
            channel_id = None
    if cp_id is None and channel_id is None:
        return None  # nothing says whose transaction this is; amount and date alone stay with the scored matcher
    return type_code, cp_id, channel_id, amounts


def _credits(value: Any, scales: dict[str, int]) -> int | None:
    """A credit_quantity ("103") in UCR minor units."""
    try:
        return int(Decimal(str(value)) * 10 ** scales.get("UCR", 2))
    except ArithmeticError, ValueError:
        return None


def match_existing(
    session: Session, ctx: RequestContext, records: Sequence[SourceRecord], explained: Sequence[str] = ()
) -> set[str]:
    """Link records whose proposed transaction is already booked; returns the ids it decided on.

    Same type, same party (counterparty, or channel when the record names none), same day, and the same main
    amount — for one record, or summed over the day's records, since the books keep some purchases as one
    daily total. Credits received are compared with a booking's credit_quantity when it has one. Exact cases
    link at once as evidence. A day that has a booking for the same party but whose amounts don't reconcile gets
    a pending "may already be booked" suggestion, so the record is never booked blindly next to it (commit
    leaves records with a pending suggestion alone)."""
    from bookkeeper.services import reference

    todo = [r for r in records if not r.transaction_id and r.status in ("new", "classified")]
    if not todo:
        return set()
    book_id = todo[0].book_id
    scales = reference.commodity_scales(session)
    proposals = {r.id: p for r in todo if (p := _proposed(session, r, scales))}
    if not proposals:
        return set()
    by_id = {r.id: r for r in todo}
    days = {by_id[i].effective_date for i in proposals}
    rows = session.execute(
        select(Transaction, TransactionType.code)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .where(
            Transaction.book_id == book_id,
            Transaction.status == "posted",
            TransactionType.code.in_({p[0] for p in proposals.values()}),
            Transaction.effective_date >= min(days) - timedelta(days=1),
            Transaction.effective_date <= max(days) + timedelta(days=1),
        )
    ).all()
    if not rows:
        return set()
    excluded = _excluded(session, book_id)
    txns = {t.id: t for t, _c in rows}
    codes = {t.id: c for t, c in rows}

    def principal(txn: Transaction, field: str) -> tuple[int, str] | None:
        value = (txn.inputs or {}).get(field)
        if field == "credit_quantity":
            credits = _credits(value, scales) if value not in (None, "") else None
            return (credits, "UCR") if credits is not None else None
        if isinstance(value, dict) and value.get("minor") is not None:
            return int(value["minor"]), str(value.get("commodity"))
        return None

    def main(
        p: tuple[str, str | None, str | None, list[tuple[str, int, str]]], txn: Transaction
    ) -> tuple[str, int, str] | None:
        """The record's main amount in the field the transaction also has: (field, minor, commodity)."""
        return next(((f, m, c) for f, m, c in p[3] if principal(txn, f) is not None), None)

    # What each booking still leaves open for a source: its main amount less what records of that source already
    # back. A daily total filled by one PDF stays open for the rest of the day's top-ups in the next one.
    linked: dict[tuple[str, str], list[SourceRecord]] = defaultdict(list)
    for link_row, rec in session.execute(
        select(TransactionSource, SourceRecord)
        .join(SourceRecord, SourceRecord.id == TransactionSource.source_record_id)
        .where(
            TransactionSource.transaction_id.in_(list(txns)),
            SourceRecord.source_id.in_({r.source_id for r in todo}),
        )
    ).all():
        linked[(link_row.transaction_id, rec.source_id)].append(rec)
    open_amount: dict[tuple[str, str, str], int] = {}

    def left(txn: Transaction, source_id: str, field: str, commodity: str) -> int:
        key = (txn.id, source_id, field)
        if key not in open_amount:
            found = principal(txn, field)
            total = found[0] if found and found[1] == commodity and txn.id not in explained else 0
            for rec in linked[(txn.id, source_id)]:
                p = _proposed(session, rec, scales)
                share = next((m for f, m, c in p[3] if f == field and c == commodity), None) if p else None
                total = 0 if share is None else total - share  # unknown backing record: treat as fully used
            open_amount[key] = max(0, total)
        return open_amount[key]

    def same_party(p: tuple[str, str | None, str | None, Any], txn: Transaction) -> bool:
        """The counterparty says whose transaction it is; the channel (how it was paid, often only a default on
        the record) decides only when the record names no party at all, like a daily income column."""
        _type, cp_id, channel_id, _amounts = p
        if cp_id:
            return txn.counterparty_id == cp_id
        return bool(channel_id) and (txn.inputs or {}).get("channel_id") == channel_id

    def link(rec: SourceRecord, txn: Transaction, method: str, score: float, status: str) -> None:
        supersede(session, rec.id)
        session.add(
            MatchSuggestion(
                id=new_id("msg"),
                book_id=book_id,
                kind="record_transaction",
                record_id=rec.id,
                transaction_id=txn.id,
                score=Decimal(str(score)),
                method=method,
                components={
                    "days": abs((txn.effective_date - rec.effective_date).days),
                    "date": rec.effective_date.isoformat(),
                    "txn_date": txn.effective_date.isoformat(),
                },
                status=status,
                decided_at=datetime.now(UTC) if status == "auto_accepted" else None,
            )
        )
        if status == "auto_accepted":
            rec.transaction_id = txn.id
            rec.status = "matched"

    def candidates(rec: SourceRecord, window: int) -> list[Transaction]:
        p = proposals[rec.id]
        found = []
        for txn in txns.values():
            amount = main(p, txn)
            if (
                codes[txn.id] == p[0]
                and abs((txn.effective_date - rec.effective_date).days) <= window
                and amount is not None
                and same_party(p, txn)
                and (rec.id, txn.id) not in excluded
                and left(txn, rec.source_id, amount[0], amount[2]) > 0
            ):
                found.append(txn)
        return found

    decided: set[str] = set()
    groups: dict[tuple[str, str | None, str | None, Any], list[SourceRecord]] = defaultdict(list)
    for rec_id, p in proposals.items():
        rec = by_id[rec_id]
        groups[(p[0], p[1], p[2], rec.effective_date)].append(rec)
    # Pass 1, exact: the day's records (or some of them) adding up to what a booking leaves open.
    for group in sorted(groups.values(), key=lambda g: g[0].effective_date):
        group.sort(key=lambda r: (r.occurred_at, r.row_no))
        remaining = list(group)
        bookings = candidates(group[0], 0)
        for txn in sorted(bookings, key=lambda t: t.id):
            amounts: dict[str, tuple[str, int, str]] = {}
            for r in remaining:
                found = main(proposals[r.id], txn) if (r.id, txn.id) not in excluded else None
                if found is not None:
                    amounts[r.id] = found
            if not amounts:
                continue
            field, _minor, commodity = next(iter(amounts.values()))
            pool = [r for r in remaining if r.id in amounts and amounts[r.id][0::2] == (field, commodity)]
            values = [amounts[r.id][1] for r in pool]
            hit = subset_summing(values, left(txn, pool[0].source_id, field, commodity))
            if hit is None:
                continue
            many = len(hit) > 1
            for i in hit:
                link(pool[i], txn, "daily_total" if many else "same_day", 0.97 if many else 0.95, "auto_accepted")
                decided.add(pool[i].id)
                remaining.remove(pool[i])
            open_amount[(txn.id, pool[0].source_id, field)] -= sum(values[i] for i in hit)
    # Pass 2, unsure: a booking for the same party on that day or the next that still has room. The records
    # may be part of it, so they wait for one yes / no per booking instead of being booked next to it.
    for rec_id in proposals:
        rec = by_id[rec_id]
        if rec.id in decided:
            continue
        near = sorted(candidates(rec, 1), key=lambda t: (abs((t.effective_date - rec.effective_date).days), t.id))
        if near:
            link(rec, near[0], "same_day_party", 0.65, "pending")
            decided.add(rec.id)
    session.flush()
    return decided


SUBSET_LIMIT = 20


def subset_summing(values: Sequence[int], target: int, limit: int = SUBSET_LIMIT) -> list[int] | None:
    """Indices of values that add up exactly to target, preferring the subset with the most items (a daily
    total explains as many top-ups as it can); None when no subset does. Beyond ``limit`` values only the whole
    set or a single value are tried, which keeps the search small."""
    if target <= 0 or not values:
        return None
    if len(values) > limit:
        if sum(values) == target:
            return list(range(len(values)))
        return next(([i] for i, v in enumerate(values) if v == target), None)
    best: dict[int, tuple[int, ...]] = {0: ()}
    for i, v in enumerate(values):
        if v <= 0 or v > target:
            continue
        for total, combo in list(best.items()):
            reached = total + v
            if reached <= target and (reached not in best or len(best[reached]) < len(combo) + 1):
                best[reached] = (*combo, i)
    hit = best.get(target)
    return list(hit) if hit else None


# ------------------------------------------------------------------ pairing rules


PAIRING_DEFAULTS: dict[str, Any] = {
    "left_keys": ["counterparty", "extracted.face"],
    "right_keys": ["counterparty", "extracted.face"],
    "window_minutes": {"before": 10, "after": 4320},
    "penalty_minutes": 4320,
    "auto_accept_max_gap_minutes": 30,
    "expand_quantity": True,
}


def pairing_view(rule: PairingRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "code": rule.code,
        "name": rule.name,
        "config": rule.config,
        "is_active": rule.is_active,
        "version": rule.version,
    }


def save_pairing_rule(session: Session, ctx: RequestContext, data: dict[str, Any]) -> PairingRule:
    ctx.require(Scope.RULES_WRITE)
    book_id = ctx.require_book()
    config = PAIRING_DEFAULTS | dict(data.get("config") or {})
    for side in ("left", "right"):
        spec = config.get(side) or {}
        if not spec.get("sources"):
            raise DomainError("VALIDATION_FAILED", f"配对规则需要 {side}.sources（来源代码列表）。")
        config[side] = {"sources": [_source_id(session, book_id, s) for s in spec["sources"]]}
    rule = session.execute(
        select(PairingRule).where(PairingRule.book_id == book_id, PairingRule.code == data["code"])
    ).scalar_one_or_none()
    if rule is None:
        rule = PairingRule(
            id=new_id("prl"), book_id=book_id, code=data["code"], name=data.get("name") or data["code"], config=config
        )
        session.add(rule)
    else:
        rule.config, rule.name = config, data.get("name") or rule.name
        rule.is_active = bool(data.get("is_active", True))
        rule.version += 1
    session.flush()
    audit.record(session, ctx, "pairing_rule.save", "pairing_rule", rule.id, after=pairing_view(rule))
    return rule


def _source_id(session: Session, book_id: str, ref: str) -> str:
    src = session.execute(
        select(ImportSource).where(
            ImportSource.book_id == book_id, (ImportSource.id == ref) | (ImportSource.code == ref)
        )
    ).scalar_one_or_none()
    if src is None:
        raise not_found("导入来源", ref)
    return src.id


def _key(rec: SourceRecord, path: str) -> str:
    if path == "counterparty":
        return str(rec.classification.get("counterparty") or rec.counterparty_text or "").lower()
    if path == "amount":
        return str(rec.amount_minor)
    if path == "commodity":
        return rec.commodity
    if path.startswith("extracted."):
        value = rec.extracted.get(path.removeprefix("extracted."))
        try:
            return format(Decimal(str(value)).normalize(), "f") if value not in (None, "") else ""
        except Exception:
            return str(value)
    if path.startswith("classification."):
        return str(rec.classification.get(path.removeprefix("classification.")) or "")
    return ""


def run_pairing(session: Session, ctx: RequestContext, batch_records: Sequence[SourceRecord]) -> None:
    """For every active pairing rule touching these records' sources, pair left and right records by time."""
    if not batch_records:
        return
    book_id = batch_records[0].book_id
    source_ids = {r.source_id for r in batch_records}
    for rule in session.execute(
        select(PairingRule).where(PairingRule.book_id == book_id, PairingRule.is_active.is_(True))
    ).scalars():
        cfg = PAIRING_DEFAULTS | rule.config
        left_sources, right_sources = set(cfg["left"]["sources"]), set(cfg["right"]["sources"])
        if not source_ids & (left_sources | right_sources):
            continue
        _pair_rule(session, rule, cfg, batch_records, left_sources, right_sources)
    session.flush()


def _pair_rule(
    session: Session,
    rule: PairingRule,
    cfg: dict[str, Any],
    batch_records: Sequence[SourceRecord],
    left_sources: set[str],
    right_sources: set[str],
) -> None:
    window = cfg["window_minutes"]
    before, after = float(window.get("before", 10)), float(window.get("after", 4320))
    span = timedelta(minutes=max(before, after))
    lo = min(r.occurred_at for r in batch_records) - span
    hi = max(r.occurred_at for r in batch_records) + span
    pool = list(
        session.execute(
            select(SourceRecord).where(
                SourceRecord.book_id == rule.book_id,
                SourceRecord.source_id.in_(left_sources | right_sources),
                SourceRecord.status.notin_(("duplicate", "ignored")),
                SourceRecord.occurred_at >= lo,
                SourceRecord.occurred_at <= hi,
            )
        ).scalars()
    )
    estimates = (
        {
            t.id
            for t in session.execute(
                select(Transaction).where(
                    Transaction.id.in_([r.transaction_id for r in pool if r.transaction_id]),
                    Transaction.is_estimate.is_(True),
                    Transaction.status == "posted",
                )
            ).scalars()
        }
        if pool
        else set()
    )
    taken: defaultdict[str, int] = defaultdict(int)
    for r in pool:
        if r.paired_with:
            taken[r.paired_with] += 1
    excluded = _excluded(session, rule.book_id)
    lefts: dict[tuple[str, ...], list[tuple[float, SourceRecord]]] = defaultdict(list)
    rights: dict[tuple[str, ...], list[tuple[float, SourceRecord]]] = defaultdict(list)
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    for r in pool:
        minutes = (r.occurred_at - epoch).total_seconds() / 60
        if r.source_id in left_sources:
            units = int(Decimal(str(r.extracted.get("quantity") or 1))) if cfg.get("expand_quantity") else 1
            free = max(units - taken[r.id], 0)
            key = tuple(_key(r, k) for k in cfg["left_keys"])
            lefts[key].extend((minutes, r) for _ in range(free))
        if r.source_id in right_sources and not r.paired_with:
            if r.transaction_id and r.transaction_id not in estimates:
                continue  # already booked against something real
            key = tuple(_key(r, k) for k in cfg["right_keys"])
            rights[key].append((minutes, r))
    batch_ids = {r.id for r in batch_records}
    for key, right_items in rights.items():
        left_items = sorted(lefts.get(key, []), key=lambda x: (x[0], x[1].id))
        right_items.sort(key=lambda x: (x[0], x[1].id))
        if not left_items:
            continue
        pairs = algo.pair(
            [t for t, _ in left_items],
            [t for t, _ in right_items],
            before=before,
            after=after,
            penalty=float(cfg["penalty_minutes"]),
        )
        for i, j, gap in pairs:
            left, right = left_items[i][1], right_items[j][1]
            if left.id not in batch_ids and right.id not in batch_ids:
                continue
            if (right.id, left.id) in excluded or right.id == left.id:
                continue
            supersede(session, right.id)
            auto = abs(gap) <= float(cfg["auto_accept_max_gap_minutes"])
            session.add(
                MatchSuggestion(
                    id=new_id("msg"),
                    book_id=rule.book_id,
                    kind="record_record",
                    record_id=right.id,
                    other_record_id=left.id,
                    pairing_rule_id=rule.id,
                    score=Decimal(str(round(max(0.0, 1 - abs(gap) / max(after, 1.0)), 4))),
                    method="pairing",
                    components={
                        "gap_minutes": round(gap, 1),
                        "rule": rule.code,
                        "key": list(key),
                        "replaces_estimate": right.transaction_id if right.transaction_id in estimates else None,
                    },
                    status="auto_accepted" if auto else "pending",
                    decided_at=datetime.now(UTC) if auto else None,
                )
            )
            if auto:
                right.paired_with = left.id
                if right.status in ("new", "classified"):
                    right.status = "matched"


def records_in_pairs(session: Session, record_ids: Sequence[str]) -> set[str]:
    """Records on either side of a pending or accepted pairing suggestion."""
    if not record_ids:
        return set()
    rows = session.execute(
        select(MatchSuggestion.record_id, MatchSuggestion.other_record_id).where(
            MatchSuggestion.kind == "record_record",
            MatchSuggestion.status.in_(("pending", "auto_accepted", "accepted")),
            (MatchSuggestion.record_id.in_(record_ids)) | (MatchSuggestion.other_record_id.in_(record_ids)),
        )
    ).all()
    return {i for pair in rows for i in pair if i}


def settle_pairs(session: Session, ctx: RequestContext, record_ids: Sequence[str]) -> int:
    """After commit / acceptance: link paired right records to the left record's transaction, replacing
    estimated postings made earlier for the right record."""
    done = 0
    rights = list(
        session.execute(
            select(SourceRecord).where(
                SourceRecord.paired_with.is_not(None),
                (SourceRecord.id.in_(record_ids)) | (SourceRecord.paired_with.in_(record_ids)),
            )
        ).scalars()
    )
    for right in rights:
        left = session.get(SourceRecord, right.paired_with)
        if left is None or not left.transaction_id or right.transaction_id == left.transaction_id:
            continue
        right_batch = session.get(ImportBatch, right.batch_id)
        if right_batch is None or right_batch.status != "committed":
            continue
        if right.transaction_id:
            old = session.get(Transaction, right.transaction_id)
            if old is not None and old.status == "posted" and old.is_estimate:
                ctx.require(Scope.LEDGER_WRITE)
                left_txn = session.get(Transaction, left.transaction_id)
                transactions.delete(session, ctx, old.id, f"由订单 {left_txn.number if left_txn else left.id} 取代估算")
            link = session.get(TransactionSource, (right.transaction_id, right.id))
            if link is not None:
                session.delete(link)
        if session.get(TransactionSource, (left.transaction_id, right.id)) is None:
            session.add(
                TransactionSource(
                    transaction_id=left.transaction_id,
                    source_record_id=right.id,
                    role="evidence",
                    created_by=ctx.actor.user_id,
                )
            )
        right.transaction_id = left.transaction_id
        right.status = "matched"
        right.version += 1
        done += 1
    session.flush()
    return done


def decide(
    session: Session, ctx: RequestContext, suggestion_id: str, accept: bool, note: str | None = None
) -> MatchSuggestion:
    ctx.require(Scope.IMPORT_WRITE)
    s = session.get(MatchSuggestion, suggestion_id, with_for_update=True)
    if s is None or s.book_id != ctx.require_book():
        raise not_found("匹配建议", suggestion_id)
    if s.status not in ("pending", "auto_accepted") and not (s.status == "accepted" and not accept):
        raise DomainError("INVALID_STATE", f"建议 {s.id} 当前为 {s.status}。")
    rec = session.get(SourceRecord, s.record_id, with_for_update=True)
    assert rec is not None
    now = datetime.now(UTC)
    s.decided_by, s.decided_at = ctx.actor.user_id, now
    if not accept:
        if s.status in ("auto_accepted", "accepted"):
            if s.kind == "record_transaction" and rec.transaction_id == s.transaction_id:
                rec.transaction_id = None
                # a finished import already filed the record as evidence of that transaction: take it back
                link = session.get(TransactionSource, (s.transaction_id, rec.id))
                if link is not None and link.role == "evidence":
                    session.delete(link)
            if s.kind == "record_record" and rec.paired_with == s.other_record_id:
                rec.paired_with = None
            if rec.status == "matched":
                rec.status = (
                    "classified" if not rec.classification.get("missing") and rec.classification.get("type") else "new"
                )
        s.status = "rejected"
        other = s.transaction_id or s.other_record_id
        if (
            other
            and not session.execute(
                select(MatchExclusion.id).where(
                    MatchExclusion.book_id == s.book_id,
                    MatchExclusion.left_id == rec.id,
                    MatchExclusion.right_id == other,
                )
            ).first()
        ):
            session.add(
                MatchExclusion(
                    id=new_id("mex"), book_id=s.book_id, left_id=rec.id, right_id=other, created_by=ctx.actor.user_id
                )
            )
    else:
        for other_s in session.execute(
            select(MatchSuggestion).where(
                MatchSuggestion.record_id == rec.id,
                MatchSuggestion.id != s.id,
                MatchSuggestion.status.in_(("pending", "auto_accepted")),
            )
        ).scalars():
            other_s.status = "superseded"
        s.status = "accepted"
        if s.kind == "record_transaction":
            rec.transaction_id = s.transaction_id
            rec.status = "matched"
            batch = session.get(ImportBatch, rec.batch_id)
            if (
                batch is not None
                and batch.status == "committed"
                and s.transaction_id
                and session.get(TransactionSource, (s.transaction_id, rec.id)) is None
            ):
                session.add(
                    TransactionSource(
                        transaction_id=s.transaction_id,
                        source_record_id=rec.id,
                        role="evidence",
                        created_by=ctx.actor.user_id,
                    )
                )
        else:
            rec.paired_with = s.other_record_id
            if rec.status in ("new", "classified"):
                rec.status = "matched"
            session.flush()
            settle_pairs(session, ctx, [rec.id])
    rec.version += 1
    session.flush()
    audit.record(session, ctx, "match.decide", "match_suggestion", s.id, after=suggestion_view(s) | {"note": note})
    return s


def pending(session: Session, book_id: str, limit: int = 50, batch_id: str | None = None) -> list[MatchSuggestion]:
    stmt = select(MatchSuggestion).where(MatchSuggestion.book_id == book_id, MatchSuggestion.status == "pending")
    if batch_id:
        stmt = stmt.join(SourceRecord, SourceRecord.id == MatchSuggestion.record_id).where(
            SourceRecord.batch_id == batch_id
        )
    return list(session.execute(stmt.order_by(MatchSuggestion.created_at).limit(limit)).scalars())
