"""Idempotency keys stored in the same transaction as the write (docs/08-rest-api.md §4.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import IdempotencyKey
from bookkeeper.db.session import rowcount
from bookkeeper.domain.canonical import canonical_json, sha256_hex
from bookkeeper.domain.errors import DomainError
from bookkeeper.services.context import RequestContext

KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


def request_hash(method: str, path: str, body: Any) -> str:
    return sha256_hex(f"{method.upper()} {path}\n{canonical_json(body)}")


@dataclass(frozen=True)
class Replay:
    status: int
    body: Any


@dataclass(frozen=True)
class Claim:
    """Primary key of a claimed idempotency row; captured before the write runs."""

    scope: str
    actor_key: str
    key: str


def validate_key(key: str | None) -> str:
    if key is None or key == "":
        raise DomainError(
            "IDEMPOTENCY_KEY_REQUIRED",
            "写请求必须提供 Idempotency-Key 请求头（1–128 个字符）。",
        )
    if not KEY_RE.match(key):
        raise DomainError(
            "VALIDATION_FAILED",
            "Idempotency-Key 只能包含字母、数字与 _ . : -，长度 1–128。",
        )
    return key


def begin(
    session: Session,
    ctx: RequestContext,
    operation: str,
    req_hash: str,
    retention_days: int,
) -> Claim | Replay:
    """Claim the key, or return a Replay when the same request already completed."""
    key = validate_key(ctx.idempotency_key)
    now = datetime.now(UTC)
    values = {
        "scope": ctx.scope,
        "actor_key": ctx.actor.key,
        "key": key,
        "operation": operation,
        "request_hash": req_hash,
        "status": "in_progress",
        "expires_at": now + timedelta(days=retention_days),
    }
    pk = {"scope": ctx.scope, "actor_key": ctx.actor.key, "key": key}
    for _ in range(2):
        claimed = session.execute(
            insert(IdempotencyKey)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["scope", "actor_key", "key"])
            .returning(IdempotencyKey.key)
        ).first()
        if claimed is not None:
            return Claim(ctx.scope, ctx.actor.key, key)
        existing = session.execute(select(IdempotencyKey).filter_by(**pk).with_for_update()).scalar_one_or_none()
        if existing is None:
            continue
        if existing.expires_at < now:
            session.execute(delete(IdempotencyKey).filter_by(**pk))
            continue
        if existing.request_hash != req_hash or existing.operation != operation:
            raise DomainError(
                "IDEMPOTENCY_MISMATCH",
                "该 Idempotency-Key 已用于内容不同的请求。请为新请求使用新的键。",
            )
        if existing.status != "completed":
            raise DomainError("IDEMPOTENCY_IN_PROGRESS", "相同请求仍在处理，请稍后重试。")
        return Replay(existing.response_status or 200, existing.response_body)
    raise DomainError("IDEMPOTENCY_IN_PROGRESS", "相同请求仍在处理，请稍后重试。")


def complete(session: Session, claim: Claim, status: int, body: Any) -> None:
    row = session.execute(
        select(IdempotencyKey).filter_by(scope=claim.scope, actor_key=claim.actor_key, key=claim.key)
    ).scalar_one()
    row.status = "completed"
    row.response_status = status
    row.response_body = body


def purge_expired(session: Session) -> int:
    result = session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < datetime.now(UTC)))
    return rowcount(result)
