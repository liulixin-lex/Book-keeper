import hashlib
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import IdempotencyRecord, User


def request_digest(payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def replay_if_exists(
    session: Session,
    user: User,
    operation: str,
    key: str | None,
    digest: str,
) -> dict[str, Any] | None:
    if not key:
        return None
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.workspace_id == user.workspace_id,
            IdempotencyRecord.actor_id == user.id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if existing is None:
        return None
    if existing.request_hash != digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="同一 Idempotency-Key 不能用于不同请求",
        )
    return existing.response_json


def store_result(
    session: Session,
    user: User,
    operation: str,
    key: str | None,
    digest: str,
    response: dict[str, Any],
    status_code: int,
) -> None:
    if not key:
        return
    session.add(
        IdempotencyRecord(
            workspace_id=user.workspace_id,
            actor_id=user.id,
            operation=operation,
            idempotency_key=key,
            request_hash=digest,
            response_json=response,
            status_code=status_code,
        )
    )


def commit_result(
    session: Session,
    user: User,
    operation: str,
    key: str | None,
    digest: str,
    response: dict[str, Any],
    status_code: int,
) -> dict[str, Any] | None:
    """Commit business data and its idempotency result as one transaction."""
    try:
        store_result(session, user, operation, key, digest, response, status_code)
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = replay_if_exists(session, user, operation, key, digest)
        if replay is not None:
            return replay
        raise
    except Exception:
        session.rollback()
        raise
    return None
