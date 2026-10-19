"""Audit events, chain verification, change sets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from bookkeeper.api.deps import AuthDep, DbDep, run_read
from bookkeeper.api.envelope import envelope
from bookkeeper.api.pagination import decode_cursor, encode_cursor
from bookkeeper.db.models import AuditEvent, ChangeSet
from bookkeeper.domain.errors import not_found
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit as service

router = APIRouter(prefix="/books/{book_id}", tags=["audit"])


def event_view(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "seq": event.seq,
        "occurred_at": event.occurred_at.isoformat(),
        "actor_type": event.actor_type,
        "user_id": event.user_id,
        "token_id": event.token_id,
        "mcp_client": event.mcp_client,
        "channel": event.channel,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "request_id": event.request_id,
        "change_set_id": event.change_set_id,
        "before": event.before,
        "after": event.after,
        "diff": event.diff,
        "hash": bytes(event.hash).hex(),
    }


def change_set_view(item: ChangeSet) -> dict[str, Any]:
    return {
        "id": item.id,
        "operation": item.operation,
        "actor_type": item.actor_type,
        "user_id": item.user_id,
        "token_id": item.token_id,
        "channel": item.channel,
        "mcp_client": item.mcp_client,
        "request_id": item.request_id,
        "entity_counts": item.entity_counts,
        "status": item.status,
        "created_at": item.created_at.isoformat(),
    }


@router.get("/audit-events")
def list_events(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    channel: str | None = None,
    change_set_id: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    position = decode_cursor(cursor)
    query = select(AuditEvent).where(AuditEvent.scope == book_id)
    for column, value in (
        (AuditEvent.entity_type, entity_type),
        (AuditEvent.entity_id, entity_id),
        (AuditEvent.action, action),
        (AuditEvent.channel, channel),
        (AuditEvent.change_set_id, change_set_id),
    ):
        if value is not None:
            query = query.where(column == value)
    if position:
        query = query.where(AuditEvent.seq < int(position["seq"]))
    query = query.order_by(AuditEvent.seq.desc()).limit(limit + 1)
    page: dict[str, Any] = {}

    def load() -> list[dict[str, Any]]:
        rows = list(db.execute(query).scalars())
        has_more = len(rows) > limit
        rows = rows[:limit]
        page["has_more"] = has_more
        page["next_cursor"] = encode_cursor({"seq": rows[-1].seq}) if has_more else None
        return [event_view(e) for e in rows]

    with db.begin():
        data = load()
    return envelope(data, auth.ctx, meta=page)


@router.get("/audit-events/verify")
def verify(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: service.verify_chain(db, book_id).__dict__, auth.ctx)


@router.get("/change-sets")
def list_change_sets(
    book_id: str, auth: AuthDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    query = select(ChangeSet).where(ChangeSet.book_id == book_id).order_by(ChangeSet.created_at.desc()).limit(limit)
    return run_read(db, lambda: [change_set_view(c) for c in db.execute(query).scalars()], auth.ctx)


@router.get("/change-sets/{change_set_id}")
def get_change_set(book_id: str, change_set_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> dict[str, Any]:
        item = db.get(ChangeSet, change_set_id)
        if item is None or item.book_id != book_id:
            raise not_found("变更集", change_set_id)
        events = db.execute(
            select(AuditEvent).where(AuditEvent.change_set_id == change_set_id).order_by(AuditEvent.seq)
        ).scalars()
        return change_set_view(item) | {"events": [event_view(e) for e in events]}

    return run_read(db, load, auth.ctx)
