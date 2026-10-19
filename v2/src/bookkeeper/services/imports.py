"""Import pipeline (docs/06): sources → batches → source records → dedupe → rules → matching → commit.

A batch is staged until committed: nothing touches the ledger before ``commit_batch``. Records
keep their evidence forever; reverting a batch reverses what it booked and marks its records ignored.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Book,
    ImportBatch,
    ImportSource,
    MatchSuggestion,
    Rule,
    SourceRecord,
    Transaction,
    TransactionSource,
)
from bookkeeper.domain import rules as rule_engine
from bookkeeper.domain.errors import DomainError, not_found, version_conflict
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.money import format_amount, from_minor
from bookkeeper.domain.rules import norm
from bookkeeper.domain.scopes import Scope
from bookkeeper.importers import PARSERS, ParseError, ParseResult, RowError
from bookkeeper.importers.base import read_rows
from bookkeeper.services import audit, business, matching, reference, transactions
from bookkeeper.services.context import RequestContext

# A read that has made no progress this long (usually: no worker running) gives up, so the page stops waiting.
READ_TIMEOUT = timedelta(minutes=10)
TIMED_OUT = "识别超时：10 分钟内没有读完（后台任务可能没有在运行）。可以再读一次。"
AI_KIND = "ai_extract"  # files are read by Claude at upload (services/ai_extract.py), then staged as records
KINDS = (*PARSERS, AI_KIND)
MULTI_FILE_KINDS = ("redeem_page", AI_KIND)
AMOUNT_FIELD = {
    "sale": "gross",
    "sale_refund": "amount",
    "credit_purchase": "total",
    "expense": "amount",
    "purchase_refund": "amount",
    "transfer": "amount_out",
}
REQUIRED = {
    "sale": ("gross", "channel"),
    "sale_refund": ("amount",),
    "credit_purchase": ("channel",),
    "expense": ("amount", "category"),
    "purchase_refund": ("amount",),
    "transfer": ("from_account", "to_account", "amount_out"),
}
MAX_RECORDS = 20_000


# ------------------------------------------------------------------ sources


def source_view(src: ImportSource) -> dict[str, Any]:
    return {
        "id": src.id,
        "code": src.code,
        "name": src.name,
        "kind": src.kind,
        "config": src.config,
        "timezone": src.timezone,
        "watermark_at": src.watermark_at.isoformat() if src.watermark_at else None,
        "is_active": src.is_active,
        "version": src.version,
    }


def get_source(session: Session, book_id: str, ref: str) -> ImportSource:
    item = session.execute(
        select(ImportSource).where(
            ImportSource.book_id == book_id, (ImportSource.id == ref) | (ImportSource.code == ref)
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("导入来源", ref)
    return item


def list_sources(session: Session, book_id: str) -> list[ImportSource]:
    return list(
        session.execute(
            select(ImportSource).where(ImportSource.book_id == book_id).order_by(ImportSource.code)
        ).scalars()
    )


def _check_config(kind: str, config: dict[str, Any]) -> None:
    if kind not in KINDS:
        raise DomainError("VALIDATION_FAILED", f"未知来源类型 {kind}；可用 {', '.join(KINDS)}。")
    policy = config.get("unclassified_policy", "leave")
    if policy not in ("leave", "suspense"):
        raise DomainError("VALIDATION_FAILED", "unclassified_policy 只能是 leave 或 suspense。")
    for direction, spec in (config.get("defaults") or {}).items():
        if direction not in ("in", "out", "neutral") or not isinstance(spec, dict):
            raise DomainError("VALIDATION_FAILED", "defaults 的键只能是 in / out / neutral，值为对象。")
        if spec.get("type") and spec["type"] not in AMOUNT_FIELD:
            raise DomainError("VALIDATION_FAILED", f"defaults.{direction}.type 不是业务交易类型。")


def preview(
    kind: str, config: dict[str, Any], content: bytes, filename: str, tz: str = "Asia/Shanghai"
) -> dict[str, Any]:
    """What a source with this kind and config would read from a sample file — nothing is stored. Shows the raw
    top rows too, so columns can be mapped even while the mapping is still incomplete."""
    if kind not in KINDS:
        raise DomainError("VALIDATION_FAILED", f"未知来源类型 {kind}；可用 {', '.join(KINDS)}。")
    if kind == AI_KIND:
        raise DomainError("VALIDATION_FAILED", "AI 识别来源不需要预览：上传后直接看读到的记录。")
    _check_config(kind, config)
    rows: list[list[str]] = []
    if kind not in ("records", "redeem_page"):
        try:
            rows = [[c[:60] for c in r] for r in read_rows(content, filename)[:15]]
        except (ParseError, ValueError, KeyError) as exc:
            return {"rows": [], "records": [], "errors": [], "skipped": 0, "total": 0, "error": str(exc)}
    try:
        parsed = PARSERS[kind].parse(content, filename, config, ZoneInfo(tz))
    except (ParseError, ValueError, KeyError) as exc:
        return {"rows": rows, "records": [], "errors": [], "skipped": 0, "total": 0, "error": str(exc)}
    records = [
        {
            "row_no": r.row_no,
            "occurred_at": r.occurred_at.isoformat(),
            "direction": r.direction,
            "amount": format(r.amount, "f"),
            "commodity": r.commodity,
            "fee": format(r.fee_amount, "f") if r.fee_amount is not None else None,
            "counterparty": r.counterparty_text,
            "description": r.description,
            "order_no": r.order_no,
            "status": r.status_text,
            "extracted": json.loads(json.dumps(dict(r.extracted), default=str)),
        }
        for r in parsed.records[:12]
    ]
    return {
        "rows": rows,
        "records": records,
        "errors": [{"row_no": e.row_no, "message": e.message} for e in parsed.errors[:12]],
        "skipped": len(parsed.skipped),
        "total": len(parsed.records),
        "error": None,
    }


def create_source(session: Session, ctx: RequestContext, data: dict[str, Any]) -> ImportSource:
    ctx.require(Scope.IMPORT_WRITE)
    book_id = ctx.require_book()
    config = dict(data.get("config") or {})
    _check_config(data["kind"], config)
    if session.execute(
        select(ImportSource.id).where(ImportSource.book_id == book_id, ImportSource.code == data["code"])
    ).first():
        raise DomainError("CONFLICT", f"来源代码 {data['code']} 已存在。")
    src = ImportSource(
        id=new_id("src"),
        book_id=book_id,
        code=data["code"],
        name=data.get("name") or data["code"],
        kind=data["kind"],
        config=config,
        timezone=data.get("timezone") or "Asia/Shanghai",
    )
    ZoneInfo(src.timezone)
    session.add(src)
    session.flush()
    audit.record(session, ctx, "import_source.create", "import_source", src.id, after=source_view(src))
    return src


def update_source(
    session: Session, ctx: RequestContext, ref: str, expected_version: int, changes: dict[str, Any]
) -> ImportSource:
    ctx.require(Scope.IMPORT_WRITE)
    src = get_source(session, ctx.require_book(), ref)
    if src.version != expected_version:
        raise version_conflict("导入来源", expected_version, src.version)
    before = source_view(src)
    if "config" in changes:
        _check_config(src.kind, dict(changes["config"] or {}))
        src.config = dict(changes["config"] or {})
    for key in ("name", "timezone", "is_active"):
        if key in changes and changes[key] is not None:
            setattr(src, key, changes[key])
    ZoneInfo(src.timezone)
    src.version += 1
    session.flush()
    audit.record(session, ctx, "import_source.update", "import_source", src.id, before=before, after=source_view(src))
    return src


# ------------------------------------------------------------------ batches


def record_view(rec: SourceRecord, scales: dict[str, int] | None = None) -> dict[str, Any]:
    def money(minor: int | None) -> str | None:
        if minor is None:
            return None
        return format_amount(minor, (scales or {}).get(rec.commodity, 2), None, rec.commodity)

    return {
        "id": rec.id,
        "row_no": rec.row_no,
        "status": rec.status,
        "occurred_at": rec.occurred_at.isoformat(),
        "effective_date": rec.effective_date.isoformat(),
        "direction": rec.direction,
        "amount": {"minor": rec.amount_minor, "commodity": rec.commodity, "display": money(rec.amount_minor)},
        "fee": money(rec.fee_minor),
        "counterparty_text": rec.counterparty_text,
        "description": rec.description,
        "order_no": rec.order_no,
        "external_id": rec.external_id,
        "status_text": rec.status_text,
        "extracted": rec.extracted,
        "classification": rec.classification,
        "duplicate_of": rec.duplicate_of,
        "ignore_reason": rec.ignore_reason,
        "paired_with": rec.paired_with,
        "transaction_id": rec.transaction_id,
        "rule_trace": rec.rule_trace,
        "error": rec.error,
        "version": rec.version,
    }


def match_info(session: Session, records: Sequence[SourceRecord]) -> dict[str, dict[str, Any]]:
    """record id → the booked transaction it was matched to, or the one it may duplicate (pending), with what
    the owner needs to decide: number, date, description, amount."""
    ids = [r.id for r in records if r.status in ("new", "classified", "matched")]
    if not ids:
        return {}
    rank = {"accepted": 0, "auto_accepted": 1, "pending": 2}
    found: dict[str, MatchSuggestion] = {}
    for s in session.execute(
        select(MatchSuggestion).where(
            MatchSuggestion.record_id.in_(ids),
            MatchSuggestion.kind == "record_transaction",
            MatchSuggestion.status.in_(tuple(rank)),
        )
    ).scalars():
        best = found.get(s.record_id)
        if best is None or (rank[s.status], -s.score) < (rank[best.status], -best.score):
            found[s.record_id] = s
    wanted = {s.transaction_id for s in found.values() if s.transaction_id}
    txns = {t.id: t for t in session.execute(select(Transaction).where(Transaction.id.in_(wanted))).scalars()}
    out: dict[str, dict[str, Any]] = {}
    for record_id, s in found.items():
        txn = txns.get(s.transaction_id or "")
        if txn is None:
            continue
        out[record_id] = {
            "suggestion_id": s.id,
            "status": s.status,
            "method": s.method,
            "score": float(s.score),
            "transaction": {
                "id": txn.id,
                "number": txn.number,
                "effective_date": txn.effective_date.isoformat(),
                "description": txn.description,
                "amount": txn.computed.get("headline"),
            },
        }
    return out


def fee_info(session: Session, records: Sequence[SourceRecord]) -> dict[str, dict[str, Any]]:
    """record id → where its fee will come from when booked: the rule in force on the record's date (by type,
    channel, counterparty), the fee the statement gives, or none (fee 0). Changing a rule changes this at once;
    booked transactions are recalculated with repost."""
    from bookkeeper.services import fees

    out: dict[str, dict[str, Any]] = {}
    rules: list[Any] | None = None
    channels: dict[str, str | None] = {}
    parties: dict[str, str | None] = {}
    for rec in records:
        c = rec.classification or {}
        type_code = c.get("type")
        if rec.status not in ("new", "classified") or type_code not in fees.FEE_TYPES:
            continue
        inputs = c.get("inputs") or {}
        if fees.basis(type_code, inputs, None) == "actual":
            out[rec.id] = {"basis": "actual", "rule": None}
            continue
        channel = str(inputs.get("channel") or "")
        if channel and channel not in channels:
            try:
                channels[channel] = reference.resolve_dimensions(session, rec.book_id, {"channel": channel})["channel"]
            except DomainError:
                channels[channel] = None
        party = str(c.get("counterparty") or "")
        if party and party not in parties:
            try:
                parties[party] = reference.get_counterparty(session, rec.book_id, party).id
            except DomainError:
                parties[party] = None
        main = next(
            (v for k in ("gross", "face", "amount", "total", "amount_out") if isinstance(v := inputs.get(k), dict)), {}
        )
        if rules is None:
            rules = fees.active_rules(session, rec.book_id)
        row = fees.proposed_rule(
            session,
            rec.book_id,
            type_code,
            channels.get(channel),
            parties.get(party),
            rec.effective_date,
            str(main.get("commodity") or rec.commodity),
            rules,
        )
        out[rec.id] = {"basis": "rule" if row else "none", "rule": fees.rule_brief(row)}
    return out


def batch_view(batch: ImportBatch, src: ImportSource | None = None) -> dict[str, Any]:
    return {
        "id": batch.id,
        "source": {"id": src.id, "code": src.code, "name": src.name, "kind": src.kind} if src else batch.source_id,
        "parser": f"{batch.parser}@{batch.parser_version}",
        "status": batch.status,
        "file_id": batch.file_id,
        "summary": batch.summary,
        "note": batch.note,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "committed_at": batch.committed_at.isoformat() if batch.committed_at else None,
        "reverted_at": batch.reverted_at.isoformat() if batch.reverted_at else None,
        "commit_change_set_id": batch.commit_change_set_id,
    }


def fingerprint(source_id: str, rec: Any, occurrence: int) -> str:
    parts = [
        source_id,
        rec.occurred_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        rec.direction,
        str(rec.amount_minor),
        rec.commodity,
        norm(rec.counterparty_text),
        norm(rec.description),
        norm(rec.order_no),
        f"#{occurrence}",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def create_batch(
    session: Session,
    ctx: RequestContext,
    *,
    source_ref: str,
    content: bytes | None = None,
    filename: str = "records.json",
    file_id: str | None = None,
    records: list[dict[str, Any]] | None = None,
    note: str | None = None,
    more_files: Sequence[tuple[bytes, str]] = (),
) -> ImportBatch:
    """Parse, normalise, dedupe, classify and match — staged; commit with ``commit_batch``.

    ``more_files`` are further files of the same source read into the same batch (several PDFs of one site).
    An AI 识别 source reads its files on the worker instead: see ``start_extraction``."""
    ctx.require(Scope.IMPORT_WRITE)
    book_id = ctx.require_book()
    book = session.get(Book, book_id)
    assert book is not None
    src = get_source(session, book_id, source_ref)
    if not src.is_active:
        raise DomainError("INVALID_STATE", f"来源 {src.code} 已停用。")
    if records is not None:
        parser = PARSERS["records"]
        content = json.dumps(records, ensure_ascii=False, default=str).encode()
        filename = "records.json"
    elif src.kind == AI_KIND:
        raise DomainError(
            "VALIDATION_FAILED", "AI 识别来源的文件要从上传接口进来（由 AI 在后台读取）；也可以直接提交 records。"
        )
    else:
        parser = PARSERS[src.kind]
        if content is None:
            raise DomainError("VALIDATION_FAILED", "请提供文件（file_id / 上传内容）或 records。")
    tz = ZoneInfo(src.timezone)
    config = src.config
    if src.kind == "redeem_page":  # lets a file name cut short still name a known site (importers/redeem.py)
        config = {**config, "known_hosts": reference.site_hosts(session, book_id)}
    try:
        parsed = parser.parse(content, filename, config, tz)
        for more, name in more_files:
            parsed = _merge(parsed, parser.parse(more, name, config, tz))
    except (ParseError, ValueError, KeyError) as exc:
        raise DomainError("INPUT_INVALID", f"文件解析失败（{parser.code}）：{exc}") from exc
    if len(parsed.records) > MAX_RECORDS:
        raise DomainError("VALIDATION_FAILED", f"单批最多 {MAX_RECORDS} 条记录，请拆分。")
    batch = ImportBatch(
        id=new_id("imb"),
        book_id=book_id,
        source_id=src.id,
        file_id=file_id,
        parser=parser.code,
        parser_version=parser.version,
        note=note,
        created_by=ctx.actor.user_id,
    )
    session.add(batch)
    session.flush()
    _stage(session, ctx, book, src, batch, parsed)
    audit.record(session, ctx, "import_batch.create", "import_batch", batch.id, after=batch_view(batch, src))
    return batch


def _stage(
    session: Session,
    ctx: RequestContext,
    book: Book,
    src: ImportSource,
    batch: ImportBatch,
    parsed: ParseResult,
    extra: dict[str, Any] | None = None,
) -> None:
    """Records into the batch: dedupe, classify, pair, match, summarise."""
    stored = _store_records(session, book, src, batch, parsed)
    classify_batch(session, ctx, batch, stored, src)
    matching.run_pairing(session, ctx, stored)  # pairing first: a paired record is evidence, not a new booking
    _match(session, ctx, stored)
    summary = summarise(session, batch, parsed, src) | (extra or {})
    summary["checks"] = summary["checks"] + list((extra or {}).get("extraction", {}).get("checks") or [])
    batch.summary = summary
    session.flush()


# ------------------------------------------------------------------ AI 识别 (read on the worker)


def existing_upload(session: Session, src: ImportSource, digest: str) -> ImportBatch | None:
    """The batch an identical upload to this source already made (not set aside): retrying an upload, or sending
    the same screenshots twice, gives that batch back instead of a second paid read."""
    return session.execute(
        select(ImportBatch)
        .where(
            ImportBatch.source_id == src.id,
            ImportBatch.status != "reverted",
            ImportBatch.summary["upload_sha256"].astext == digest,
        )
        .order_by(ImportBatch.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def ai_files_today(session: Session, book: Book) -> int:
    """Files sent to the AI today (the book's own day), for the daily cap."""
    start = datetime.now(ZoneInfo(book.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = session.execute(
        select(ImportBatch.summary).where(
            ImportBatch.book_id == book.id, ImportBatch.parser == AI_KIND, ImportBatch.created_at >= start
        )
    ).scalars()
    return sum(len((summary or {}).get("files") or []) for summary in rows)


def start_extraction(
    session: Session,
    ctx: RequestContext,
    *,
    source_ref: str,
    file_ids: Sequence[str],
    digest: str,
    note: str | None = None,
    daily_limit: int = 0,
) -> ImportBatch:
    """An AI 识别 upload: the batch shows 识别中 while the worker reads the files (``finish_extraction``)."""

    ctx.require(Scope.IMPORT_WRITE)
    book_id = ctx.require_book()
    book = session.get(Book, book_id)
    assert book is not None
    src = get_source(session, book_id, source_ref)
    if not src.is_active:
        raise DomainError("INVALID_STATE", f"来源 {src.code} 已停用。")
    if daily_limit and ai_files_today(session, book) + len(file_ids) > daily_limit:
        raise DomainError(
            "RATE_LIMITED", f"今天的 AI 识别已到上限（每天 {daily_limit} 个文件），明天再试或调高 BK_AI_DAILY_FILES。"
        )
    batch = ImportBatch(
        id=new_id("imb"),
        book_id=book_id,
        source_id=src.id,
        file_id=file_ids[0],
        parser=AI_KIND,
        parser_version="pending",
        status="extracting",
        note=note,
        created_by=ctx.actor.user_id,
        summary={"files": list(file_ids), "upload_sha256": digest, "records": 0} | _attempt(),
    )
    session.add(batch)
    session.flush()
    _enqueue_read(session, batch)
    audit.record(session, ctx, "import_batch.extract", "import_batch", batch.id, after=batch_view(batch, src))
    return batch


def _attempt() -> dict[str, str]:
    """Each read of a batch (the first, every retry) gets its own token and clock."""
    return {"attempt": new_id("att"), "reading_since": datetime.now(UTC).isoformat()}


def _enqueue_read(session: Session, batch: ImportBatch) -> None:
    from bookkeeper.jobs import queue

    payload = {"batch_id": batch.id, "attempt": batch.summary["attempt"]}
    queue.enqueue(session, "imports.ai_extract", payload, book_id=batch.book_id, max_attempts=1)


def wants_read(batch: ImportBatch | None, attempt: str | None, *, landing: bool = False) -> bool:
    """Whether a read of this attempt is still wanted: the batch is 识别中, or (for a read that already ran) it timed
    out meanwhile — a slow read still lands rather than being thrown away. A retry starts a new attempt, so a
    stale job never reads twice."""
    if batch is None or (attempt is not None and batch.summary.get("attempt") not in (None, attempt)):
        return False
    return batch.status == "extracting" or (
        landing and batch.status == "failed" and bool(batch.summary.get("timed_out"))
    )


def expire_stalled(session: Session, book_id: str, batch_id: str | None = None) -> None:
    """识别中 with no result after READ_TIMEOUT becomes 识别失败 (识别超时), so the page stops polling and the owner
    can retry; checked whenever batches are read, which works even when no worker is running."""
    stmt = select(ImportBatch).where(ImportBatch.book_id == book_id, ImportBatch.status == "extracting")
    if batch_id is not None:
        stmt = stmt.where(ImportBatch.id == batch_id)
    cutoff = datetime.now(UTC) - READ_TIMEOUT
    for batch in session.execute(stmt.with_for_update(skip_locked=True)).scalars():
        since = batch.summary.get("reading_since")
        if (datetime.fromisoformat(since) if since else batch.created_at) < cutoff:
            batch.status = "failed"
            batch.summary = {**batch.summary, "error": TIMED_OUT, "timed_out": True}


def finish_extraction(
    session: Session, ctx: RequestContext, batch_id: str, extracted: Any, attempt: str | None = None
) -> ImportBatch | None:
    """The worker's read arrives: stage the records like any import (the batch becomes 待完成)."""
    batch = session.get(ImportBatch, batch_id, with_for_update=True)
    if batch is None or not wants_read(batch, attempt, landing=True):
        return None
    src = session.get(ImportSource, batch.source_id)
    book = session.get(Book, batch.book_id)
    assert src is not None
    assert book is not None
    content = json.dumps(extracted.records, ensure_ascii=False, default=str).encode()
    parsed = PARSERS["records"].parse(content, "records.json", src.config, ZoneInfo(src.timezone))
    batch.status = "parsed"
    batch.parser_version = extracted.model
    extraction = {
        "model": extracted.model,
        "files": batch.summary.get("files") or [],
        "usage": extracted.usage,
        "unreadable": extracted.unreadable[:50],
        "totals": extracted.totals[:50],
        "checks": extracted.checks[:50],
    }
    _stage(
        session,
        ctx,
        book,
        src,
        batch,
        parsed,
        {"upload_sha256": batch.summary.get("upload_sha256"), "files": extraction["files"], "extraction": extraction},
    )
    audit.record(session, ctx, "import_batch.extracted", "import_batch", batch.id, after=batch_view(batch, src))
    return batch


def fail_extraction(session: Session, batch_id: str, message: str, attempt: str | None = None) -> None:
    batch = session.get(ImportBatch, batch_id, with_for_update=True)
    if batch is not None and wants_read(batch, attempt, landing=True):
        batch.status = "failed"
        batch.summary = {k: v for k, v in batch.summary.items() if k != "timed_out"} | {"error": message}


def retry_extraction(session: Session, ctx: RequestContext, batch_ref: str) -> ImportBatch:
    """Read a failed AI batch again (same files)."""
    ctx.require(Scope.IMPORT_WRITE)
    batch = get_batch(session, ctx, batch_ref, lock=True)
    if batch.status != "failed":
        raise DomainError("INVALID_STATE", f"批次 {batch.id} 当前为 {batch.status}，只有识别失败的批次可以重试。")
    batch.status = "extracting"
    batch.summary = {k: v for k, v in batch.summary.items() if k not in ("error", "timed_out")} | _attempt()
    _enqueue_read(session, batch)
    session.flush()
    audit.record(session, ctx, "import_batch.extract", "import_batch", batch.id, after={"retry": True})
    return batch


def _merge(first: ParseResult, more: ParseResult) -> ParseResult:
    """One batch from several files: rows numbered on from the previous file."""
    offset = max([r.row_no for r in first.records] + [e.row_no for e in first.errors + first.skipped] + [0])
    first.records += [dataclasses.replace(r, row_no=r.row_no + offset) for r in more.records]
    first.errors += [dataclasses.replace(e, row_no=e.row_no + offset) for e in more.errors]
    first.skipped += [dataclasses.replace(e, row_no=e.row_no + offset) for e in more.skipped]
    return first


def _store_records(
    session: Session, book: Book, src: ImportSource, batch: ImportBatch, parsed: ParseResult
) -> list[SourceRecord]:
    scales = reference.active_scales(session)
    tz = ZoneInfo(book.timezone)
    now = datetime.now(UTC)
    seen: Counter[str] = Counter()
    stored: list[SourceRecord] = []
    for rec in parsed.records:
        if rec.commodity not in scales:
            parsed.errors.append(RowError(rec.row_no, reference.unknown_commodity(rec.commodity), dict(rec.raw)))
            continue
        scale = scales[rec.commodity]
        try:
            amount = _minor(rec.amount, scale)
            fee = _minor(rec.fee_amount, scale) if rec.fee_amount is not None else None
            balance = _minor(rec.balance_after, scale) if rec.balance_after is not None else None
        except ValueError as exc:
            parsed.errors.append(RowError(rec.row_no, str(exc), dict(rec.raw)))
            continue
        if rec.occurred_at > now + timedelta(days=1):
            parsed.errors.append(RowError(rec.row_no, f"发生时间 {rec.occurred_at} 晚于当前时间", dict(rec.raw)))
            continue
        row = SourceRecord(
            id=new_id("srec"),
            book_id=book.id,
            source_id=src.id,
            batch_id=batch.id,
            row_no=rec.row_no,
            external_id=(rec.external_id or "").strip() or None,
            fingerprint="",
            occurred_at=rec.occurred_at,
            effective_date=rec.occurred_at.astimezone(tz).date(),
            direction=rec.direction,
            amount_minor=amount,
            commodity=rec.commodity,
            fee_minor=fee,
            balance_after_minor=balance,
            counterparty_text=rec.counterparty_text,
            description=rec.description,
            order_no=rec.order_no,
            reference=rec.reference,
            status_text=rec.status_text,
            extracted=json.loads(json.dumps(dict(rec.extracted), default=str)),
            raw=json.loads(json.dumps(dict(rec.raw), default=str)),
        )
        key = fingerprint(src.id, row, 0)
        seen[key] += 1
        row.fingerprint = fingerprint(src.id, row, seen[key])
        _dedupe(session, src, row)
        session.add(row)
        session.flush()
        stored.append(row)
    return stored


def _match(session: Session, ctx: RequestContext, records: Sequence[SourceRecord]) -> None:
    """Pairing aside: is the proposed transaction already booked (exactly, or as a daily total)? Then the scored
    matcher for whatever is still open."""
    paired = matching.records_in_pairs(session, [r.id for r in records])
    open_ = [r for r in records if r.status in ("new", "classified") and r.id not in paired and not r.transaction_id]
    lefts = [session.get(SourceRecord, r.paired_with) for r in records if r.paired_with]
    explained = [left.transaction_id for left in lefts if left is not None and left.transaction_id]
    decided = matching.match_existing(session, ctx, open_, explained)
    matching.match_records(session, ctx, [r for r in open_ if r.id not in decided])


def _rematch(session: Session, ctx: RequestContext, records: Sequence[SourceRecord]) -> None:
    """The classification changed, so the match may have too. Earlier "not the same" answers stay excluded."""
    open_ = [r for r in records if r.status in ("new", "classified") and not r.transaction_id]
    if not open_:
        return
    for s in session.execute(
        select(MatchSuggestion).where(
            MatchSuggestion.record_id.in_([r.id for r in open_]),
            MatchSuggestion.kind == "record_transaction",
            MatchSuggestion.status == "pending",
        )
    ).scalars():
        s.status = "superseded"
    session.flush()
    _match(session, ctx, open_)


def live_record() -> Any:
    """Records that still hold their identity (not duplicates, not from reverted batches)."""
    return (SourceRecord.status != "duplicate") & SourceRecord.ignore_reason.is_distinct_from("batch_reverted")


def _minor(value: Decimal, scale: int) -> int:
    quantum = Decimal(1).scaleb(-scale)
    if value != value.quantize(quantum):
        raise ValueError(f"金额 {value} 的小数位超过该币种精度（{scale} 位）")
    return int(value.scaleb(scale))


def _dedupe(session: Session, src: ImportSource, row: SourceRecord) -> None:
    """Same source, same external id or same fingerprint → duplicate (records of reverted batches excepted)."""
    same = SourceRecord.fingerprint == row.fingerprint
    if row.external_id:
        same = same | (SourceRecord.external_id == row.external_id)
    existing = session.execute(
        select(SourceRecord.id).where(SourceRecord.source_id == src.id, live_record(), same).limit(1)
    ).scalar_one_or_none()
    if existing:
        row.status = "duplicate"
        row.duplicate_of = existing


# ------------------------------------------------------------------ classification


def facts_for(session: Session, src: ImportSource, rec: SourceRecord) -> dict[str, Any]:
    scales = reference.commodity_scales(session)
    scale = scales.get(rec.commodity, 2)
    local = rec.occurred_at.astimezone(ZoneInfo(src.timezone))
    candidates: list[str] = []
    resolved: str | None = None
    if rec.counterparty_text:
        found = reference.resolve_counterparty_text(session, src.book_id, rec.counterparty_text)
        candidates = [c["name"] for c in found]  # names: rules and pairing keys compare by name
        top = found[0] if found else None
        if top and top.get("score", 0) >= 0.9 and (len(found) == 1 or found[1].get("score", 0) < top["score"]):
            resolved = top["name"]
    return {
        "source": src.code,
        "source_kind": src.kind,
        "direction": rec.direction,
        "amount": from_minor(rec.amount_minor, scale),
        "commodity": rec.commodity,
        "fee_amount": from_minor(rec.fee_minor, scale) if rec.fee_minor is not None else None,
        "occurred_at": local.isoformat(),
        "effective_date": rec.effective_date.isoformat(),
        "time_of_day": local.strftime("%H:%M"),
        "weekday": local.isoweekday(),
        "counterparty_text": rec.counterparty_text,
        "counterparty": resolved,
        "counterparty_candidates": candidates,
        "description": rec.description,
        "order_no": rec.order_no,
        "reference": rec.reference,
        "status_text": rec.status_text,
        "extracted": rec.extracted,
        "batch": rec.batch_id,
    }


def _money(value: Decimal, commodity: str) -> dict[str, str]:
    return {"amount": format(value, "f"), "commodity": commodity}


def default_classification(src: ImportSource, facts: dict[str, Any]) -> dict[str, Any]:
    """Source defaults for the record's direction, with amounts mapped onto the type's inputs."""
    if (facts.get("extracted") or {}).get("fully_refunded"):
        return {"ignore": "fully_refunded"}
    spec = dict((src.config.get("defaults") or {}).get(facts["direction"]) or {})
    if not spec:
        return {"ignore": "neutral"} if facts["direction"] == "neutral" else {}
    if spec.get("ignore"):
        return {"ignore": spec["ignore"]}
    c: dict[str, Any] = {
        "type": spec.get("type"),
        "counterparty": spec.get("counterparty") or facts.get("counterparty"),
        "inputs": {k: v for k, v in spec.items() if k not in ("type", "counterparty", "ignore")},
    }
    return fill_amounts(c, facts, src)


def fill_amounts(c: dict[str, Any], facts: dict[str, Any], src: ImportSource) -> dict[str, Any]:
    """Put the record amount (and fee, face value, credits) into the type's input fields if not set."""
    type_code = c.get("type")
    if not type_code or type_code not in AMOUNT_FIELD:
        return c
    inputs = c.setdefault("inputs", {})
    amount, commodity, extracted = facts["amount"], facts["commodity"], facts.get("extracted") or {}
    credit_rate = Decimal(str(src.config.get("credit_rate", "1")))
    base = src.config.get("base_commodity", "CNY")
    if type_code == "credit_purchase":
        if commodity == "UCR":  # credits received without a payment record: face = credits × rate
            inputs.setdefault("face", _money((amount * credit_rate).quantize(Decimal("0.01")), base))
            inputs.setdefault("credit_quantity", format(amount, "f"))
        else:
            if extracted.get("face") and "face" not in inputs:
                quantity = Decimal(str(extracted.get("quantity") or 1))
                inputs["face"] = _money(Decimal(str(extracted["face"])) * quantity, commodity)
                inputs.setdefault(
                    "credit_quantity",
                    format(Decimal(str(extracted.get("credits") or extracted["face"])) * quantity, "f"),
                )
            inputs.setdefault("total", _money(amount, commodity))
    else:
        inputs.setdefault(AMOUNT_FIELD[type_code], _money(amount, commodity))
        if facts.get("fee_amount") and type_code in ("sale", "expense"):
            inputs.setdefault("fee", _money(facts["fee_amount"], commodity))
    return c


def missing_fields(c: dict[str, Any]) -> list[str]:
    type_code = c.get("type")
    if not type_code:
        return ["type"]
    inputs = c.get("inputs") or {}
    missing = [f"inputs.{f}" for f in REQUIRED.get(type_code, ()) if not inputs.get(f)]
    if type_code == "credit_purchase":
        if not (inputs.get("face") or inputs.get("total")):
            missing.append("inputs.face")
        if not c.get("counterparty"):
            missing.append("counterparty")
    if type_code in ("sale_refund", "purchase_refund") and not (
        inputs.get("original") or inputs.get("channel") or inputs.get("category")
    ):
        missing.append("inputs.original")
    return missing


def active_rules(session: Session, book_id: str) -> list[rule_engine.RuleDef]:
    rows = session.execute(select(Rule).where(Rule.book_id == book_id, Rule.is_active.is_(True))).scalars()
    return [
        rule_engine.RuleDef(r.id, r.code, r.version, r.stage, r.priority, r.condition, r.actions, r.stop_processing)
        for r in rows
    ]


DIRECTION_TYPES = {"out": ("credit_purchase", "expense", "sale_refund"), "in": ("sale", "purchase_refund")}


def _counterparty_defaults(session: Session, book_id: str, facts: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    """Overlay the counterparty's default type and channel on the source defaults (rules still win).

    A default type is used only when it fits the money direction (a purchase default never turns
    incoming money into a purchase)."""
    name = c.get("counterparty") or facts.get("counterparty")
    if not name:
        return c
    try:
        cp = reference.get_counterparty(session, book_id, name)
    except DomainError:
        return c
    defaults = reference.counterparty_defaults(session, cp)
    out = dict(c)
    inputs = dict(out.get("inputs") or {})
    if defaults["type"] in DIRECTION_TYPES.get(facts["direction"], ()) and defaults["type"] != out.get("type"):
        out["type"] = defaults["type"]
        out["counterparty"] = cp.name
        inputs = {k: v for k, v in inputs.items() if k == "channel"}  # other source inputs were for another type
    if defaults["channel"] and out.get("type") in business.CHANNEL_TYPES and "channel" not in inputs:
        inputs["channel"] = defaults["channel"]["code"]
    out["inputs"] = inputs
    return out


def classify_record(
    session: Session,
    src: ImportSource,
    rec: SourceRecord,
    rules: Sequence[rule_engine.RuleDef],
    hits: Counter[str] | None = None,
) -> None:
    """(Re)compute the proposed transaction from source defaults and rules, honouring locked fields."""
    if rec.status in ("duplicate", "booked") or rec.transaction_id:
        return
    facts = facts_for(session, src, rec)
    locked = list(rec.locked_fields)
    base = default_classification(src, facts)
    kept = {k: v for k, v in rec.classification.items() if k in locked or f"inputs.{k}" in locked}
    if rec.classification.get("inputs"):
        kept_inputs = {k: v for k, v in rec.classification["inputs"].items() if f"inputs.{k}" in locked}
        if kept_inputs:
            kept["inputs"] = kept_inputs
    if base.get("ignore") and not rules:
        rec.status, rec.ignore_reason, rec.classification = "ignored", str(base["ignore"]), {}
        return
    start = _counterparty_defaults(session, src.book_id, facts, {k: v for k, v in base.items() if k != "ignore"})
    outcome = rule_engine.apply(rules, facts, start, locked)
    c = outcome.classification
    for key, value in kept.items():
        if key == "inputs":
            c.setdefault("inputs", {}).update(value)
        else:
            c[key] = value
    c = fill_amounts(c, facts, src)
    rec.rule_trace = outcome.trace
    if hits is not None:
        hits.update(outcome.matched_rules)
    if outcome.ignored or (base.get("ignore") and not c.get("type")):
        rec.status, rec.ignore_reason = "ignored", outcome.ignored or str(base["ignore"])
        rec.classification = {}
        return
    c["missing"] = missing_fields(c)
    rec.classification = json.loads(json.dumps(c, default=str))
    if rec.status in ("new", "classified", "ignored"):
        rec.status = "classified" if not c["missing"] else "new"
        rec.ignore_reason = None


def classify_batch(
    session: Session, ctx: RequestContext, batch: ImportBatch, records: Sequence[SourceRecord], src: ImportSource
) -> None:
    rules = active_rules(session, batch.book_id)
    hits: Counter[str] = Counter()
    for rec in records:
        classify_record(session, src, rec, rules, hits)
    _count_hits(session, hits)


def _count_hits(session: Session, hits: Counter[str]) -> None:
    now = datetime.now(UTC)
    for rule_id, count in hits.items():
        rule = session.get(Rule, rule_id)
        if rule is not None:
            rule.hit_count += count
            rule.last_hit_at = now


def summarise(session: Session, batch: ImportBatch, parsed: ParseResult, src: ImportSource) -> dict[str, Any]:
    rows = list(session.execute(select(SourceRecord).where(SourceRecord.batch_id == batch.id)).scalars())
    by_status = Counter(r.status for r in rows)
    checks: list[dict[str, Any]] = []
    declared = parsed.summary.declared
    for direction in ("in", "out"):
        if f"{direction}_count" in declared:
            count = sum(1 for r in parsed.records if r.direction == direction)
            ok = count == int(declared[f"{direction}_count"])
            checks.append(
                {
                    "code": "totals_match",
                    "severity": "warning",
                    "ok": ok,
                    "message": f"{direction} 笔数：文件声明 {declared[f'{direction}_count']}，入账候选 {count}",
                }
            )
    balances = [r for r in sorted(rows, key=lambda r: (r.occurred_at, r.row_no)) if r.balance_after_minor is not None]
    breaks = 0
    for prev, cur in itertools.pairwise(balances):
        delta = cur.amount_minor if cur.direction == "in" else -cur.amount_minor
        if (
            cur.direction != "neutral"
            and (prev.balance_after_minor or 0) + delta - (cur.fee_minor or 0) != cur.balance_after_minor
        ):
            breaks += 1
    if balances:
        checks.append(
            {
                "code": "balance_continuity",
                "severity": "error",
                "ok": breaks == 0,
                "message": f"余额连续性：{breaks} 处不连续" if breaks else "余额连续",
            }
        )
    checks.append(
        {
            "code": "row_errors",
            "severity": "error",
            "ok": not parsed.errors,
            "message": f"{len(parsed.errors)} 行无法解析" if parsed.errors else "无解析错误",
        }
    )
    if src.watermark_at and rows:
        earliest = min(r.occurred_at for r in rows)
        gap = (earliest - src.watermark_at).days
        checks.append(
            {
                "code": "period_gap",
                "severity": "warning",
                "ok": gap <= 1,
                "message": f"与上次导入之间相隔 {gap} 天" if gap > 1 else "与上次导入衔接",
            }
        )
    if rows and by_status.get("duplicate", 0) == len(rows):
        checks.append({"code": "all_duplicates", "severity": "info", "ok": False, "message": "全部为重复记录"})
    pending = 0
    if rows:
        pending = session.execute(
            select(func.count())
            .select_from(MatchSuggestion)
            .where(MatchSuggestion.record_id.in_([r.id for r in rows]), MatchSuggestion.status == "pending")
        ).scalar_one()
    return {
        "records": len(rows),
        "by_status": dict(by_status),
        "skipped": len(parsed.skipped),
        "row_errors": [{"row_no": e.row_no, "message": e.message} for e in parsed.errors[:200]],
        "skipped_rows": [{"row_no": e.row_no, "message": e.message} for e in parsed.skipped[:200]],
        "pending_suggestions": int(pending),
        "checks": checks,
        "blocking": [c["code"] for c in checks if c["severity"] == "error" and not c["ok"]],
        "period": [
            min(r.effective_date for r in rows).isoformat() if rows else None,
            max(r.effective_date for r in rows).isoformat() if rows else None,
        ],
    }


def get_batch(session: Session, ctx: RequestContext, ref: str, *, lock: bool = False) -> ImportBatch:
    ctx.require(Scope.LEDGER_READ)
    expire_stalled(session, ctx.require_book(), ref)
    batch = session.get(ImportBatch, ref, with_for_update=lock)
    if batch is None or batch.book_id != ctx.require_book():
        raise not_found("导入批次", ref)
    return batch


def batch_records(
    session: Session,
    batch_id: str | None,
    *,
    book_id: str,
    status: str | None = None,
    source: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    text: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SourceRecord]:
    stmt = select(SourceRecord).where(SourceRecord.book_id == book_id)
    if batch_id:
        stmt = stmt.where(SourceRecord.batch_id == batch_id)
    if status:
        stmt = stmt.where(SourceRecord.status.in_(status.split(",")))
    if source:
        stmt = stmt.where(SourceRecord.source_id == source)
    if date_from:
        stmt = stmt.where(SourceRecord.effective_date >= date_from)
    if date_to:
        stmt = stmt.where(SourceRecord.effective_date <= date_to)
    if text:
        like = f"%{text}%"
        stmt = stmt.where(
            SourceRecord.description.ilike(like)
            | SourceRecord.counterparty_text.ilike(like)
            | SourceRecord.order_no.ilike(like)
        )
    return list(
        session.execute(
            stmt.order_by(SourceRecord.occurred_at, SourceRecord.row_no).limit(limit).offset(offset)
        ).scalars()
    )


# ------------------------------------------------------------------ manual decisions on records


def _record(session: Session, ctx: RequestContext, record_id: str) -> SourceRecord:
    rec = session.get(SourceRecord, record_id, with_for_update=True)
    if rec is None or rec.book_id != ctx.require_book():
        raise not_found("来源记录", record_id)
    return rec


def set_classification(session: Session, ctx: RequestContext, record_id: str, changes: dict[str, Any]) -> SourceRecord:
    """Hand classification: the given fields are locked against rules; the rest is recomputed."""
    ctx.require(Scope.IMPORT_WRITE)
    rec = _record(session, ctx, record_id)
    if rec.status in ("booked", "duplicate") or rec.transaction_id:
        raise DomainError(
            "INVALID_STATE", f"记录 {rec.id} 已{('入账' if rec.status == 'booked' else '标记为重复')}，不能再分类。"
        )
    src = session.get(ImportSource, rec.source_id)
    assert src is not None
    c = dict(rec.classification)
    locked = set(rec.locked_fields)
    for key in ("type", "counterparty", "description"):
        if key in changes:
            c[key] = changes[key]
            locked.add(key)
    if "inputs" in changes:
        inputs = dict(c.get("inputs") or {})
        for k, v in (changes["inputs"] or {}).items():
            if v is None:
                inputs.pop(k, None)
            else:
                inputs[k] = v
            locked.add(f"inputs.{k}")
        c["inputs"] = inputs
    if c.get("counterparty"):
        try:
            c["counterparty"] = reference.get_counterparty(session, rec.book_id, c["counterparty"]).name
        except DomainError as exc:
            raise DomainError(
                "NOT_FOUND",
                exc.detail,
                candidates=reference.resolve_counterparty_text(session, rec.book_id, c["counterparty"])[:5],
            ) from exc
    rec.classification = c
    rec.locked_fields = sorted(locked)
    if rec.status == "ignored":
        rec.status = "new"
    classify_record(session, src, rec, active_rules(session, rec.book_id))
    rec.version += 1
    session.flush()
    audit.record(
        session, ctx, "source_record.classify", "source_record", rec.id, after={"classification": rec.classification}
    )
    _rematch(session, ctx, [rec])
    _book_left_behind(session, ctx, rec)
    return rec


def _book_left_behind(session: Session, ctx: RequestContext, rec: SourceRecord) -> None:
    """A record a finished import left behind is booked as soon as it is complete: writes take effect at once.

    Without ``ledger:write`` it stays classified for someone who has it; a booking error is kept on the record.
    """
    if rec.status not in ("classified", "matched") or not ctx.has(Scope.LEDGER_WRITE):
        return
    if rec.status == "classified" and rec.transaction_id:
        return
    batch = session.get(ImportBatch, rec.batch_id)
    if batch is None or batch.status != "committed":
        return
    src = session.get(ImportSource, batch.source_id)
    assert src is not None
    savepoint = session.begin_nested()
    try:
        _commit_record(session, ctx, src, rec)
        savepoint.commit()
    except DomainError as exc:
        savepoint.rollback()
        session.refresh(rec)
        rec.error = {"code": exc.code, "detail": exc.detail, "errors": [e.__dict__ for e in exc.errors]}
    session.flush()


def decide_match(
    session: Session, ctx: RequestContext, suggestion_id: str, accept: bool, note: str | None = None
) -> MatchSuggestion:
    """Answer "is this the transaction already booked?". Yes: the record becomes its evidence. No: every pending
    guess for the record is set aside for good, and a record a finished import left behind is booked now."""
    s = matching.decide(session, ctx, suggestion_id, accept, note)
    rec = session.get(SourceRecord, s.record_id)
    if rec is None or s.kind != "record_transaction":
        return s
    if not accept:
        for other in session.execute(
            select(MatchSuggestion.id).where(
                MatchSuggestion.record_id == rec.id,
                MatchSuggestion.kind == "record_transaction",
                MatchSuggestion.status == "pending",
            )
        ).scalars():
            matching.decide(session, ctx, other, False, note)
    _book_left_behind(session, ctx, rec)
    return s


def decide_batch_matches(
    session: Session, ctx: RequestContext, batch_ref: str, same: bool, record_ids: Sequence[str] | None = None
) -> dict[str, int]:
    """Answer every open "may already be booked" question of a batch at once (or of the given records): each
    record takes its best guess as yes, or all its guesses as no."""
    batch = get_batch(session, ctx, batch_ref)
    stmt = (
        select(MatchSuggestion)
        .join(SourceRecord, SourceRecord.id == MatchSuggestion.record_id)
        .where(
            SourceRecord.batch_id == batch.id,
            MatchSuggestion.kind == "record_transaction",
            MatchSuggestion.status == "pending",
        )
        .order_by(MatchSuggestion.record_id, MatchSuggestion.score.desc())
    )
    if record_ids:
        stmt = stmt.where(SourceRecord.id.in_(record_ids))
    best: dict[str, str] = {}
    for s in session.execute(stmt).scalars():
        best.setdefault(s.record_id, s.id)
    for suggestion_id in best.values():
        decide_match(session, ctx, suggestion_id, same)
    return {"decided": len(best)}


def open_counts(session: Session, batch_ids: Sequence[str]) -> dict[str, int]:
    """Records per batch not yet in the books: still missing a field, or ready and waiting for the import to finish
    (ignored, duplicate and booked records do not count; a reverted batch releases its records as ignored)."""
    if not batch_ids:
        return {}
    rows = session.execute(
        select(SourceRecord.batch_id, func.count())
        .where(
            SourceRecord.batch_id.in_(batch_ids),
            SourceRecord.transaction_id.is_(None),
            SourceRecord.status.in_(("new", "classified")),
        )
        .group_by(SourceRecord.batch_id)
    ).all()
    return {batch_id: n for batch_id, n in rows}


def ignore_records(session: Session, ctx: RequestContext, record_ids: Sequence[str], reason: str) -> list[SourceRecord]:
    ctx.require(Scope.IMPORT_WRITE)
    done = []
    for record_id in record_ids:
        rec = _record(session, ctx, record_id)
        if rec.status == "booked":
            raise DomainError("INVALID_STATE", f"记录 {rec.id} 已入账；如不需要，删除对应交易。")
        rec.status, rec.ignore_reason = "ignored", reason
        rec.version += 1
        done.append(rec)
    session.flush()
    audit.record(
        session, ctx, "source_record.ignore", "source_record", None, after={"ids": list(record_ids), "reason": reason}
    )
    return done


def link_record(session: Session, ctx: RequestContext, record_id: str, transaction_ref: str) -> SourceRecord:
    """Manual match: this record is evidence of an existing transaction."""
    ctx.require(Scope.IMPORT_WRITE)
    rec = _record(session, ctx, record_id)
    txn, _code = transactions.load(session, ctx, transaction_ref)
    if txn.status != "posted":
        raise DomainError("INVALID_STATE", f"交易 {txn.number} 已删除，不能关联。")
    rec.transaction_id = txn.id
    rec.status = "matched"
    rec.version += 1
    matching.supersede(session, rec.id)
    batch = session.get(ImportBatch, rec.batch_id)
    if batch is not None and batch.status == "committed":
        _link(session, ctx, txn.id, rec.id, "evidence")
    session.flush()
    audit.record(session, ctx, "source_record.link", "source_record", rec.id, after={"transaction_id": txn.id})
    return rec


def _link(session: Session, ctx: RequestContext, txn_id: str, record_id: str, role: str) -> None:
    if session.get(TransactionSource, (txn_id, record_id)) is None:
        session.add(
            TransactionSource(
                transaction_id=txn_id, source_record_id=record_id, role=role, created_by=ctx.actor.user_id
            )
        )


def reclassify(
    session: Session, ctx: RequestContext, record_ids: Sequence[str] | None = None, batch_id: str | None = None
) -> int:
    """Re-run defaults and rules on unbooked records (after editing rules or source defaults)."""
    ctx.require(Scope.IMPORT_WRITE)
    book_id = ctx.require_book()
    stmt = select(SourceRecord).where(
        SourceRecord.book_id == book_id,
        SourceRecord.status.in_(("new", "classified", "ignored")),
        SourceRecord.transaction_id.is_(None),
    )
    if record_ids:
        stmt = stmt.where(SourceRecord.id.in_(record_ids))
    if batch_id:
        stmt = stmt.where(SourceRecord.batch_id == batch_id)
    rows = list(session.execute(stmt).scalars())
    rules = active_rules(session, book_id)
    sources: dict[str, ImportSource] = {}
    hits: Counter[str] = Counter()
    for rec in rows:
        if rec.status == "ignored" and rec.ignore_reason in ("batch_reverted", "manual"):
            continue
        src = sources.get(rec.source_id) or session.get(ImportSource, rec.source_id)
        assert src is not None
        sources[rec.source_id] = src
        classify_record(session, src, rec, rules, hits)
    _count_hits(session, hits)
    session.flush()
    _rematch(session, ctx, rows)
    for rec in rows:
        _book_left_behind(session, ctx, rec)
    return len(rows)


# ------------------------------------------------------------------ commit / revert


def _external_ref(src: ImportSource, rec: SourceRecord) -> str:
    return f"{src.code}:{rec.external_id or rec.fingerprint[:20]}"


def commit_batch(
    session: Session,
    ctx: RequestContext,
    batch_ref: str,
    *,
    accept_row_errors: bool = False,
    exclude: Sequence[str] = (),
) -> dict[str, Any]:
    """Book the batch: create transactions for classified records, link matched / paired evidence,
    apply the unclassified policy. Each record is committed on its own savepoint; failures are reported."""
    ctx.require(Scope.IMPORT_WRITE)
    batch = get_batch(session, ctx, batch_ref, lock=True)
    if batch.status != "parsed":
        raise DomainError("INVALID_STATE", f"批次 {batch.id} 当前为 {batch.status}，只能提交待提交的批次。")
    src = session.get(ImportSource, batch.source_id)
    assert src is not None
    blocking = [b for b in batch.summary.get("blocking", []) if not (b == "row_errors" and accept_row_errors)]
    if blocking:
        raise DomainError(
            "VALIDATION_FAILED",
            f"安全校验未通过：{', '.join(blocking)}。修正文件后重新导入"
            + ("；若只是个别行无法解析，可设置 accept_row_errors=true 跳过这些行" if "row_errors" in blocking else "")
            + "。",
            extra={"checks": batch.summary.get("checks")},
        )
    ctx.require(Scope.LEDGER_WRITE)
    records = batch_records(session, batch.id, book_id=batch.book_id, limit=MAX_RECORDS)
    counts: Counter[str] = Counter()
    failures: list[dict[str, Any]] = []
    order = sorted(records, key=lambda r: (r.paired_with is not None, r.occurred_at, r.row_no))
    for rec in order:
        if rec.id in exclude:
            counts["excluded"] += 1
            continue
        if rec.status in ("duplicate", "ignored"):
            counts[rec.status] += 1
            continue
        savepoint = session.begin_nested()
        try:
            outcome = _commit_record(session, ctx, src, rec)
            savepoint.commit()
            counts[outcome] += 1
        except DomainError as exc:
            savepoint.rollback()
            session.refresh(rec)
            rec.error = {"code": exc.code, "detail": exc.detail, "errors": [e.__dict__ for e in exc.errors]}
            failures.append({"record_id": rec.id, "row_no": rec.row_no, "code": exc.code, "detail": exc.detail})
            counts["failed"] += 1
    batch.status = "committed"
    batch.committed_at = datetime.now(UTC)
    session.flush()
    counts["settled_pairs"] = matching.settle_pairs(session, ctx, [r.id for r in records])
    audit.ensure_change_set(session, ctx, "import_batch.commit")
    batch.commit_change_set_id = ctx.change_set_id
    latest = max((r.occurred_at for r in records), default=None)
    if latest and (src.watermark_at is None or latest > src.watermark_at):
        src.watermark_at = latest
    result = {"batch_id": batch.id, "counts": dict(counts), "failures": failures}
    batch.summary = {**batch.summary, "commit": result}
    session.flush()
    audit.record(session, ctx, "import_batch.commit", "import_batch", batch.id, after=result)
    return result


def _commit_record(session: Session, ctx: RequestContext, src: ImportSource, rec: SourceRecord) -> str:
    rec.error = None
    if rec.paired_with:
        left = session.get(SourceRecord, rec.paired_with)
        if left is not None and left.transaction_id:
            _link(session, ctx, left.transaction_id, rec.id, "evidence")
            rec.transaction_id = left.transaction_id
            rec.status = "matched"
            return "paired"
    if rec.transaction_id:
        txn = session.get(Transaction, rec.transaction_id)
        if txn is not None and txn.status == "posted":
            _link(session, ctx, txn.id, rec.id, "evidence")
            rec.status = "matched"
            return "linked"
        rec.transaction_id = None
    if session.execute(
        select(MatchSuggestion.id)
        .where(MatchSuggestion.record_id == rec.id, MatchSuggestion.status == "pending")
        .limit(1)
    ).first():
        return "pending_match"  # never book something that may already exist; decide the suggestion first
    if rec.status == "classified":
        c = rec.classification
        data: dict[str, Any] = {
            "type": c["type"],
            "effective_date": rec.effective_date,
            "occurred_at": rec.occurred_at,
            "date_precision": "timestamp",
            "inputs": c.get("inputs") or {},
            "counterparty": c.get("counterparty"),
            "external_ref": _external_ref(src, rec),
            "order_no": rec.order_no,
            "metadata": {"source_record_id": rec.id, "source": src.code},
        }
        if c.get("description"):
            data["description"] = c["description"]
        if c.get("tags"):
            data["tags"] = c["tags"]
        txn, _entry, _plan = transactions.create(session, ctx, data)
        _link(session, ctx, txn.id, rec.id, "primary")
        rec.transaction_id = txn.id
        rec.status = "booked"
        return "booked"
    if src.config.get("unclassified_policy") == "suspense" and rec.direction in ("in", "out"):
        txn = _book_suspense(session, ctx, src, rec)
        _link(session, ctx, txn.id, rec.id, "primary")
        rec.transaction_id = txn.id
        rec.status = "booked"
        return "suspense"
    return "left_unbooked"


def _book_suspense(session: Session, ctx: RequestContext, src: ImportSource, rec: SourceRecord) -> Transaction:
    """Unclassified money movement: funds ↔ 待核对款项 (1999); edit it into the right type later."""
    from bookkeeper.services import accounts

    funds = accounts.default_for_role(session, rec.book_id, "funds")
    suspense = accounts.default_for_role(session, rec.book_id, "suspense")
    if funds is None or suspense is None:
        raise DomainError("ACCOUNT_NOT_POSTABLE", "账套缺少资金账户或待核对款项科目。")
    amount = format(from_minor(rec.amount_minor, reference.commodity_scales(session)[rec.commodity]), "f")
    funds_side = "debit" if rec.direction == "in" else "credit"
    other_side = "credit" if funds_side == "debit" else "debit"
    party = rec.counterparty_text or src.name
    txn, _entry, _plan = transactions.create(
        session,
        ctx,
        {
            "type": "manual_journal",
            "effective_date": rec.effective_date,
            "description": f"待核对 · {party} · {rec.description or src.name}"[:200],
            "lines": [
                transactions.LineSpec(funds.code, funds_side, amount, rec.commodity),
                transactions.LineSpec(suspense.code, other_side, amount, rec.commodity),
            ],
            "external_ref": _external_ref(src, rec),
            "metadata": {"source_record_id": rec.id, "source": src.code, "suspense": True},
        },
    )
    return txn


def revert_batch(session: Session, ctx: RequestContext, batch_ref: str, reason: str | None = None) -> dict[str, Any]:
    """Undo a committed batch by appending: delete what it booked, unlink evidence, set its records aside."""
    ctx.require(Scope.IMPORT_WRITE)
    batch = get_batch(session, ctx, batch_ref, lock=True)
    if batch.status == "failed":  # an AI read that failed: nothing was booked, just set it aside
        batch.status = "reverted"
        batch.reverted_at = datetime.now(UTC)
        session.flush()
        audit.record(session, ctx, "import_batch.revert", "import_batch", batch.id, after={"failed_read": True})
        return {"batch_id": batch.id, "counts": {}}
    if batch.status != "committed":
        raise DomainError("INVALID_STATE", f"批次 {batch.id} 当前为 {batch.status}，只能撤销已提交的批次。")
    counts: Counter[str] = Counter()
    records = batch_records(session, batch.id, book_id=batch.book_id, limit=MAX_RECORDS)
    reason = (reason or "").strip() or None
    note = "撤销导入批次" + (f" · {reason}" if reason else "")
    for rec in records:
        if rec.status == "booked" and rec.transaction_id:
            txn = session.get(Transaction, rec.transaction_id)
            if txn is not None and txn.status == "posted":
                ctx.require(Scope.LEDGER_WRITE)
                transactions.delete(session, ctx, txn.id, note)
                counts["deleted"] += 1
            if txn is not None and txn.external_ref:  # free the reference so the records can be imported again
                txn.metadata_ = {**txn.metadata_, "released_external_ref": txn.external_ref}
                txn.external_ref = None
        if rec.transaction_id:
            link = session.get(TransactionSource, (rec.transaction_id, rec.id))
            if link is not None:
                session.delete(link)
                counts["unlinked"] += 1
        if rec.status != "duplicate":
            rec.status, rec.ignore_reason, rec.transaction_id = "ignored", "batch_reverted", None
            rec.version += 1
    batch.status = "reverted"
    batch.reverted_at = datetime.now(UTC)
    session.flush()
    result = {"batch_id": batch.id, "counts": dict(counts)}
    audit.record(session, ctx, "import_batch.revert", "import_batch", batch.id, after=result | {"reason": reason})
    return result


def evidence_for(session: Session, txn_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(TransactionSource, SourceRecord, ImportSource)
        .join(SourceRecord, SourceRecord.id == TransactionSource.source_record_id)
        .join(ImportSource, ImportSource.id == SourceRecord.source_id)
        .where(TransactionSource.transaction_id == txn_id)
    ).all()
    scales = reference.commodity_scales(session)
    return [{"role": link.role, "source": src.code, "record": record_view(rec, scales)} for link, rec, src in rows]
