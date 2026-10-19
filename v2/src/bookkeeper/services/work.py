"""Pending work: everything that still needs a decision, each with the tool / endpoint that resolves it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Book,
    CheckResult,
    CheckRun,
    ImportBatch,
    MatchSuggestion,
    SourceRecord,
    Transaction,
    TransactionType,
)
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import accounts
from bookkeeper.services.context import RequestContext
from bookkeeper.services.reports import _activity, _Fmt

KINDS = (
    "unprocessed_records",
    "pending_matches",
    "uncommitted_batches",
    "estimated",
    "suspense",
    "failed_checks",
)
LABELS = {
    "unprocessed_records": "待补全的导入记录",
    "pending_matches": "待确认的匹配",
    "uncommitted_batches": "未完成的导入",
    "estimated": "手续费为估算",
    "suspense": "待核对款项余额",
    "failed_checks": "健康检查未通过",
}


def _estimated(session: Session, book_id: str, limit: int) -> tuple[int, list[dict[str, Any]]]:
    conditions = (Transaction.book_id == book_id, Transaction.status == "posted", Transaction.is_estimate.is_(True))
    count = int(session.execute(select(func.count()).select_from(Transaction).where(*conditions)).scalar_one())
    rows = session.execute(
        select(Transaction, TransactionType.code)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .where(*conditions)
        .order_by(Transaction.effective_date, Transaction.number)
        .limit(limit)
    ).all()
    items = [
        {
            "kind": "estimated",
            "id": txn.id,
            "number": txn.number,
            "type": code,
            "date": txn.effective_date.isoformat(),
            "title": txn.description,
            "amount": txn.computed.get("headline"),
            "suggested": {
                "tool": "update_transaction",
                "hint": "填入实际手续费；或修改手续费规则后按新规则重算",
                "args": {"ref": txn.number},
            },
        }
        for txn, code in rows
    ]
    return count, items


def collect(session: Session, ctx: RequestContext, kinds: list[str] | None = None, limit: int = 20) -> dict[str, Any]:
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    book = session.get(Book, book_id)
    assert book is not None
    wanted = kinds or list(KINDS)
    summary: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []

    def add(kind: str, count: int, found: list[dict[str, Any]], **extra: Any) -> None:
        summary[kind] = {"label": LABELS.get(kind, kind), "count": count} | extra
        items.extend(found)

    if "unprocessed_records" in wanted:
        add("unprocessed_records", *_unprocessed(session, book_id, limit))
    if "pending_matches" in wanted:
        add("pending_matches", *_pending_matches(session, book_id, limit))
    if "uncommitted_batches" in wanted:
        add("uncommitted_batches", *_uncommitted(session, book_id, limit))
    if "estimated" in wanted:
        add("estimated", *_estimated(session, book_id, limit))
    if "suspense" in wanted:
        suspense = accounts.default_for_role(session, book_id, "suspense")
        balance = 0
        if suspense is not None:
            today = datetime.now(UTC).date()
            balance = sum(a.base_closing for a in _activity(session, book_id, None, today, None, {suspense.id}))
        fmt = _Fmt(session, book)
        found = []
        if balance and suspense is not None:
            found.append(
                {
                    "kind": "suspense",
                    "title": f"{suspense.code} {suspense.name} 余额不为 0",
                    "amount": fmt.base_money(balance),
                    "suggested": {
                        "tool": "search_transactions",
                        "hint": "找到这些款项，改成正确的交易类型",
                        "args": {"account": suspense.code},
                    },
                }
            )
        add("suspense", 1 if balance else 0, found, balance=fmt.base_money(balance))
    if "failed_checks" in wanted:
        run = session.execute(
            select(CheckRun).where(CheckRun.book_id == book_id).order_by(CheckRun.started_at.desc()).limit(1)
        ).scalar_one_or_none()
        failed: list[dict[str, Any]] = []
        if run is not None:
            for result in session.execute(
                select(CheckResult).where(CheckResult.run_id == run.id, CheckResult.status == "failed")
            ).scalars():
                failed.append(
                    {
                        "kind": "failed_checks",
                        "id": result.id,
                        "title": f"{result.check_code}：{result.message}",
                        "severity": result.severity,
                        "count": result.count,
                        "suggested": {"tool": "run_checks", "hint": "修正后重新运行检查", "args": {}},
                    }
                )
        add("failed_checks", len(failed), failed[:limit], last_run=run.started_at.isoformat() if run else None)
    return {"summary": summary, "items": items, "total": sum(v["count"] for v in summary.values())}


def _unprocessed(session: Session, book_id: str, limit: int) -> tuple[int, list[dict[str, Any]]]:
    """Records of committed batches that were left unbooked (unclassified or held for a match decision)."""
    base = (
        select(SourceRecord)
        .join(ImportBatch, ImportBatch.id == SourceRecord.batch_id)
        .where(
            SourceRecord.book_id == book_id,
            ImportBatch.status == "committed",
            SourceRecord.status.in_(("new", "classified")),
            SourceRecord.transaction_id.is_(None),
        )
    )
    count = int(session.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    rows = session.execute(base.order_by(SourceRecord.occurred_at).limit(limit)).scalars()
    items = [
        {
            "kind": "unprocessed_records",
            "id": r.id,
            "date": r.effective_date.isoformat(),
            "title": f"{r.counterparty_text or ''} {r.description or ''}".strip() or r.id,
            "missing": r.classification.get("missing"),
            "suggested": {
                "tool": "classify_records",
                "hint": "补全分类后入账，或忽略",
                "args": {"record_ids": [r.id]},
            },
        }
        for r in rows
    ]
    return count, items


def _pending_matches(session: Session, book_id: str, limit: int) -> tuple[int, list[dict[str, Any]]]:
    base = select(MatchSuggestion).where(MatchSuggestion.book_id == book_id, MatchSuggestion.status == "pending")
    count = int(session.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    rows = session.execute(base.order_by(MatchSuggestion.created_at).limit(limit)).scalars()
    items = [
        {
            "kind": "pending_matches",
            "id": s.id,
            "title": f"{s.kind} · 得分 {float(s.score):.2f}",
            "suggested": {"tool": "resolve_match", "hint": "接受或拒绝", "args": {"suggestion_id": s.id}},
        }
        for s in rows
    ]
    return count, items


def _uncommitted(session: Session, book_id: str, limit: int) -> tuple[int, list[dict[str, Any]]]:
    rows = list(
        session.execute(
            select(ImportBatch)
            .where(ImportBatch.book_id == book_id, ImportBatch.status == "parsed")
            .order_by(ImportBatch.created_at)
        ).scalars()
    )
    items = [
        {
            "kind": "uncommitted_batches",
            "id": b.id,
            "title": f"导入批次 {b.id}（{b.summary.get('records', 0)} 条）",
            "suggested": {"tool": "commit_import", "hint": "确认识别结果后完成导入", "args": {"batch_id": b.id}},
        }
        for b in rows[:limit]
    ]
    return len(rows), items
