"""Audit events with a per-scope hash chain (docs/05-posting-engine.md §9.2)."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import AuditEvent, AuditHead, ChangeSet
from bookkeeper.domain.canonical import chain_hash, genesis_hash
from bookkeeper.domain.ids import new_id
from bookkeeper.services.context import RequestContext

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "token",
        "token_hash",
        "csrf_secret",
        "secret",
        "secret_enc",
        "totp_secret_enc",
        "identifier",
        "code_plain",
    }
)
REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if k in SENSITIVE_KEYS else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any] | None:
    if before is None or after is None:
        return None
    keys = set(before) | set(after)
    changed = {k: [before.get(k), after.get(k)] for k in sorted(keys) if before.get(k) != after.get(k)}
    return changed or None


def _normalise_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return ipaddress.ip_address(ip).compressed
    except ValueError:
        return None


def hash_payload(event: Any) -> dict[str, Any]:
    """Every persisted column except prev_hash/hash, in JSON-safe form."""
    return {
        "id": event.id,
        "scope": event.scope,
        "book_id": event.book_id,
        "seq": event.seq,
        "occurred_at": event.occurred_at,
        "actor_type": event.actor_type,
        "user_id": event.user_id,
        "token_id": event.token_id,
        "mcp_client": event.mcp_client,
        "channel": event.channel,
        "action": event.action,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "request_id": event.request_id,
        "idempotency_key": event.idempotency_key,
        "change_set_id": event.change_set_id,
        "before": event.before,
        "after": event.after,
        "diff": event.diff,
        "ip": str(event.ip) if event.ip is not None else None,
        "user_agent": event.user_agent,
    }


def _lock_head(session: Session, scope: str) -> AuditHead:
    session.execute(
        insert(AuditHead)
        .values(scope=scope, last_seq=0, last_hash=genesis_hash("audit", scope))
        .on_conflict_do_nothing(index_elements=["scope"])
    )
    return session.execute(select(AuditHead).where(AuditHead.scope == scope).with_for_update()).scalar_one()


def ensure_change_set(session: Session, ctx: RequestContext, operation: str) -> str:
    """Create the request's change set on first write; returns its id."""
    if ctx.change_set_id is None:
        change_set = ChangeSet(
            id=new_id("chs"),
            book_id=ctx.book_id,
            operation=operation,
            actor_type=ctx.actor.type,
            user_id=ctx.actor.user_id,
            token_id=ctx.actor.token_id,
            channel=ctx.channel,
            mcp_client=ctx.actor.mcp_client,
            request_id=ctx.request_id,
            entity_counts={},
        )
        session.add(change_set)
        session.flush()
        ctx.change_set_id = change_set.id
    return ctx.change_set_id


def record(
    session: Session,
    ctx: RequestContext,
    action: str,
    entity_type: str,
    entity_id: str | None,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    scope: str | None = None,
    in_change_set: bool = True,
) -> AuditEvent:
    """Append one audit event to the chain of ``scope`` (default: the request's book or global)."""
    chain_scope = scope or ctx.scope
    change_set_id = ensure_change_set(session, ctx, action) if in_change_set else None
    if change_set_id is not None:
        change_set = session.get(ChangeSet, change_set_id)
        if change_set is not None:
            counts = dict(change_set.entity_counts)
            counts[entity_type] = counts.get(entity_type, 0) + 1
            change_set.entity_counts = counts
    head = _lock_head(session, chain_scope)
    red_before, red_after = redact(before), redact(after)
    event = AuditEvent(
        id=new_id("aud"),
        scope=chain_scope,
        book_id=None if chain_scope == "global" else chain_scope,
        seq=head.last_seq + 1,
        occurred_at=datetime.now(UTC),
        actor_type=ctx.actor.type,
        user_id=ctx.actor.user_id,
        token_id=ctx.actor.token_id,
        mcp_client=ctx.actor.mcp_client,
        channel=ctx.channel,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=ctx.request_id,
        idempotency_key=ctx.idempotency_key,
        change_set_id=change_set_id,
        before=red_before,
        after=red_after,
        diff=diff(red_before, red_after),
        ip=_normalise_ip(ctx.ip),
        user_agent=(ctx.user_agent or None) and ctx.user_agent[:500],
        prev_hash=head.last_hash,
    )
    event.hash = chain_hash(head.last_hash, hash_payload(event))
    head.last_seq = event.seq
    head.last_hash = event.hash
    head.updated_at = event.occurred_at
    session.add(event)
    session.flush()
    return event


@dataclass(frozen=True)
class ChainVerification:
    scope: str
    ok: bool
    events: int
    first_bad_seq: int | None = None
    reason: str | None = None


def verify_chain(session: Session, scope: str, batch_size: int = 1000) -> ChainVerification:
    """Recompute the whole chain for ``scope``; report the first inconsistent seq."""
    prev = genesis_hash("audit", scope)
    expected_seq = 1
    count = 0
    last_seq = 0
    while True:
        table = AuditEvent.__table__
        rows = session.execute(
            select(table).where(table.c.scope == scope, table.c.seq > last_seq).order_by(table.c.seq).limit(batch_size)
        ).all()
        if not rows:
            break
        for event in rows:
            if event.seq != expected_seq:
                return ChainVerification(scope, False, count, expected_seq, "sequence gap")
            if bytes(event.prev_hash) != prev:
                return ChainVerification(scope, False, count, event.seq, "prev_hash mismatch")
            if chain_hash(prev, hash_payload(event)) != bytes(event.hash):
                return ChainVerification(scope, False, count, event.seq, "hash mismatch")
            prev = bytes(event.hash)
            expected_seq += 1
            count += 1
            last_seq = event.seq
    head = session.get(AuditHead, scope)
    if head is not None and (head.last_seq != count or bytes(head.last_hash) != prev):
        return ChainVerification(scope, False, count, count + 1, "head mismatch")
    return ChainVerification(scope, True, count)
