"""Undo a change set: every write of one request is reverted by appending, never by deleting.

- transaction created here → deleted; deleted here → restored; restored here → deleted again;
- transaction edited or re-posted here → header, inputs and tags put back, and if its entry changed the
  earlier lines are posted again (copied, not rebuilt, so later fee rule changes do not leak in);
- import batch committed here → reverted;
- fee rule version created → retired, the previous version's end date restored; retired → reactivated;
- AI workspace file written → its earlier text restored, or removed if this change set created it;
- anything else is listed under ``manual`` (not changed automatically).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import AuditEvent, Book, ChangeSet, FeeRuleRow, JournalEntry, SourceRecord, Transaction
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit, imports, ledger, tags, transactions, workspace
from bookkeeper.services.context import RequestContext

HANDLED = {
    "import_batch.commit",
    "import_batch.create",
    "source_record.classify",
    "transaction.create",
    "transaction.update",
    "transaction.delete",
    "transaction.restore",
    "transaction.repost",
    "fee_rule.create",
    "fee_rule.close",
    "fee_rule.retire",
    "agent_file.write",
}


def _events(session: Session, ctx: RequestContext, change_set_id: str) -> tuple[ChangeSet, list[AuditEvent]]:
    change_set = session.get(ChangeSet, change_set_id, with_for_update=True)
    if change_set is None or change_set.book_id != ctx.require_book():
        raise not_found("变更集", change_set_id)
    if change_set.status != "applied":
        raise DomainError(
            "INVALID_STATE",
            f"变更集 {change_set_id} 当前为 {change_set.status}"
            + (f"（已由 {change_set.reverted_by_change_set_id} 撤销）" if change_set.reverted_by_change_set_id else "")
            + "，不能再次撤销。",
        )
    events = list(
        session.execute(
            select(AuditEvent).where(AuditEvent.change_set_id == change_set_id).order_by(AuditEvent.seq)
        ).scalars()
    )
    return change_set, events


def _batch_transactions(session: Session, batch_ids: list[str]) -> set[str]:
    if not batch_ids:
        return set()
    rows = session.execute(
        select(SourceRecord.transaction_id).where(
            SourceRecord.batch_id.in_(batch_ids), SourceRecord.transaction_id.is_not(None)
        )
    ).scalars()
    return {r for r in rows if r}


def undo(session: Session, ctx: RequestContext, change_set_id: str, reason: str | None = None) -> dict[str, Any]:
    reason = (reason or "").strip() or None
    original_set, events = _events(session, ctx, change_set_id)
    book = session.get(Book, ctx.require_book())
    assert book is not None
    touched: dict[str, set[str]] = {}
    order: list[str] = []
    befores: dict[str, dict[str, Any]] = {}
    manual: list[dict[str, Any]] = []
    fee_events: list[AuditEvent] = []
    file_events: list[AuditEvent] = []
    for event in events:
        if event.entity_type == "transaction" and event.entity_id:
            if event.entity_id not in touched:
                touched[event.entity_id] = set()
                order.append(event.entity_id)
            touched[event.entity_id].add(event.action)
            if event.action in ("transaction.update", "transaction.repost") and event.entity_id not in befores:
                befores[event.entity_id] = event.before or {}
        elif event.action.startswith("fee_rule."):
            fee_events.append(event)
        elif event.action == "agent_file.write":
            file_events.append(event)
        elif event.action not in HANDLED:
            manual.append({"action": event.action, "entity_type": event.entity_type, "entity_id": event.entity_id})
    import_batches = [e.entity_id for e in events if e.action == "import_batch.commit" and e.entity_id]
    batch_txns = _batch_transactions(session, import_batches)
    for txn_id in batch_txns:
        touched.pop(txn_id, None)
    order = [t for t in order if t not in batch_txns]
    if touched:
        ctx.require(Scope.LEDGER_WRITE)
    if fee_events:
        ctx.require(Scope.CONFIG_WRITE)
    note = f"撤销 · {reason}" if reason else "撤销"
    ctx.change_set_id = None
    audit.ensure_change_set(session, ctx, "change_set.undo")
    done: list[dict[str, Any]] = []
    for batch_id in import_batches:
        result = imports.revert_batch(session, ctx, batch_id, reason)
        done.append({"import_batch": batch_id, "action": "import_reverted", "counts": result["counts"]})
    for txn_id in reversed(order):
        done.extend(_undo_transaction(session, ctx, txn_id, touched[txn_id], befores.get(txn_id), note))
    for event in reversed(fee_events):
        done.extend(_undo_fee_event(session, ctx, event))
    for event in reversed(file_events):
        assert event.entity_id is not None
        restored = workspace.undo_write(session, event.entity_id, event.before)
        audit.record(session, ctx, "agent_file.restore", "agent_file", event.entity_id, after=restored)
        done.append(restored)
    new_set = session.get(ChangeSet, ctx.change_set_id)
    assert new_set is not None
    new_set.reverts_change_set_id = original_set.id
    new_set.summary = (f"撤销 {original_set.id}" + (f"：{reason}" if reason else ""))[:200]
    original_set.status = "reverted"
    original_set.reverted_by_change_set_id = new_set.id
    audit.record(
        session,
        ctx,
        "change_set.undo",
        "change_set",
        original_set.id,
        after={"reverted_by": new_set.id, "reason": reason, "actions": len(done), "manual": len(manual)},
    )
    return {"change_set_id": original_set.id, "undo_change_set_id": new_set.id, "actions": done, "manual": manual}


def _undo_transaction(
    session: Session,
    ctx: RequestContext,
    txn_id: str,
    actions: set[str],
    before: dict[str, Any] | None,
    note: str,
) -> list[dict[str, Any]]:
    txn = session.get(Transaction, txn_id)
    if txn is None:
        return []
    label = {"id": txn.id, "number": txn.number}
    if "transaction.create" in actions or "transaction.restore" in actions:
        if txn.status == "posted":
            transactions.delete(session, ctx, txn.id, note)
            return [label | {"action": "deleted"}]
        return []
    if "transaction.delete" in actions:
        if txn.status == "reversed":
            transactions.restore(session, ctx, txn.id)
            return [label | {"action": "restored"}]
        return []
    if actions & {"transaction.update", "transaction.repost"} and before and txn.status == "posted":
        _put_back(session, ctx, txn, before, note)
        return [label | {"action": "put_back"}]
    return []


def _put_back(session: Session, ctx: RequestContext, txn: Transaction, before: dict[str, Any], note: str) -> None:
    """Header, inputs and tags as in ``before``; if the entry changed since, its earlier lines again."""
    type_code = before.get("type", "")
    state_before = transactions.state_view(session, txn, type_code)
    for key in ("description", "counterparty_id", "external_ref", "order_no", "notes", "date_precision"):
        if key in before:
            setattr(txn, key, before[key])
    if before.get("effective_date"):
        txn.effective_date = date.fromisoformat(before["effective_date"])
    if "occurred_at" in before:
        transactions.set_occurred_at(
            txn, datetime.fromisoformat(before["occurred_at"]) if before["occurred_at"] else None
        )
    for key, attr in (
        ("inputs", "inputs"),
        ("computed", "computed"),
        ("default_dimensions", "default_dimensions"),
        ("metadata", "metadata_"),
        ("provenance", "provenance"),
    ):
        if key in before:
            setattr(txn, attr, before[key])
    txn.is_estimate = bool(before.get("is_estimate", txn.is_estimate))
    if "tags" in before:
        tags.set_tags(session, ctx, txn, before["tags"] or [])
    earlier_id = before.get("posted_entry_id")
    if earlier_id and earlier_id != txn.posted_entry_id:
        earlier = session.get(JournalEntry, earlier_id)
        assert earlier is not None
        entry = transactions.rebook(
            session,
            ctx,
            txn,
            ledger.load_built_lines(session, earlier.id),
            effective_date=earlier.effective_date,
            journal_code=earlier.journal_code,
            fee_rule_ids=earlier.fee_rule_ids,
            note=note,
        )
        txn.computed = txn.computed | {"entry_number": entry.number}
    txn.version += 1
    session.flush()
    audit.record(
        session,
        ctx,
        "transaction.update",
        "transaction",
        txn.id,
        before=state_before,
        after=transactions.state_view(session, txn, type_code),
    )


def _undo_fee_event(session: Session, ctx: RequestContext, event: AuditEvent) -> list[dict[str, Any]]:
    if event.action == "fee_rule.create" and event.entity_id:
        row = session.get(FeeRuleRow, event.entity_id, with_for_update=True)
        if row is not None and row.status == "active":
            row.status = "retired"
            audit.record(
                session, ctx, "fee_rule.retire", "fee_rule", row.id, after={"code": row.code, "version": row.version}
            )
            return [{"fee_rule": f"{row.code}@{row.version}", "action": "retired"}]
    if event.action == "fee_rule.close" and event.entity_id and event.before is not None:
        row = session.get(FeeRuleRow, event.entity_id, with_for_update=True)
        if row is not None:
            previous_end = event.before.get("valid_to")
            row.valid_to = date.fromisoformat(previous_end) if previous_end else None
            audit.record(session, ctx, "fee_rule.reopen", "fee_rule", row.id, after={"valid_to": previous_end})
            return [{"fee_rule": f"{row.code}@{row.version}", "action": "end_date_restored"}]
    if event.action == "fee_rule.retire":
        code = (event.after or {}).get("code")
        rows = session.execute(
            select(FeeRuleRow).where(
                FeeRuleRow.book_id == ctx.require_book(), FeeRuleRow.code == code, FeeRuleRow.status == "retired"
            )
        ).scalars()
        restored = []
        for row in rows:
            row.status = "active"
            restored.append({"fee_rule": f"{row.code}@{row.version}", "action": "reactivated"})
        if restored:
            audit.record(session, ctx, "fee_rule.reactivate", "fee_rule", event.entity_id, after={"code": code})
        return restored
    return []
