"""Tags: free-form labels on transactions (campaigns, projects, follow-ups), docs/04 §8."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from bookkeeper.db.models import Tag, Transaction, TransactionTag
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services.context import RequestContext

MAX_TAGS = 20
MAX_LENGTH = 30
_SPACES = re.compile(r"\s+")


def normalise(names: Sequence[str]) -> list[str]:
    """Trimmed, inner whitespace collapsed, de-duplicated (first spelling wins), order kept."""
    out: list[str] = []
    for raw in names:
        name = _SPACES.sub(" ", str(raw)).strip()
        if not name:
            continue
        if len(name) > MAX_LENGTH:
            raise DomainError("VALIDATION_FAILED", f"标签“{name[:10]}…”超过 {MAX_LENGTH} 个字符。")
        if name not in out:
            out.append(name)
    if len(out) > MAX_TAGS:
        raise DomainError("VALIDATION_FAILED", f"每笔交易最多 {MAX_TAGS} 个标签。")
    return out


def _ensure(session: Session, book_id: str, names: list[str]) -> dict[str, str]:
    if not names:
        return {}
    session.execute(
        insert(Tag)
        .values([{"id": new_id("tag"), "book_id": book_id, "name": n} for n in names])
        .on_conflict_do_nothing(index_elements=["book_id", "name"])
    )
    return dict(session.execute(select(Tag.name, Tag.id).where(Tag.book_id == book_id, Tag.name.in_(names))).all())


def set_tags(session: Session, ctx: RequestContext, txn: Transaction, names: Sequence[str]) -> list[str]:
    """Replace the transaction's tags; returns the new list."""
    wanted = normalise(names)
    ids = _ensure(session, txn.book_id, wanted)
    session.execute(delete(TransactionTag).where(TransactionTag.transaction_id == txn.id))
    if wanted:
        session.execute(
            insert(TransactionTag).values(
                [{"transaction_id": txn.id, "tag_id": ids[n], "created_by": ctx.actor.user_id} for n in wanted]
            )
        )
    return wanted


def tags_for(session: Session, transaction_ids: Sequence[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    if not transaction_ids:
        return out
    rows = session.execute(
        select(TransactionTag.transaction_id, Tag.name)
        .join(Tag, Tag.id == TransactionTag.tag_id)
        .where(TransactionTag.transaction_id.in_(transaction_ids))
        .order_by(TransactionTag.created_at, Tag.name)
    ).all()
    for txn_id, name in rows:
        out[txn_id].append(name)
    return out


def tagged(names: Sequence[str]) -> Any:
    """SQL condition: the transaction carries any of these tags (by name)."""
    return (
        select(TransactionTag.transaction_id)
        .join(Tag, Tag.id == TransactionTag.tag_id)
        .where(Tag.name.in_(normalise(names)))
    )


def list_tags(session: Session, ctx: RequestContext) -> list[dict[str, Any]]:
    ctx.require(Scope.LEDGER_READ)
    rows = session.execute(
        select(Tag.name, func.count(TransactionTag.transaction_id), func.max(TransactionTag.created_at))
        .outerjoin(TransactionTag, TransactionTag.tag_id == Tag.id)
        .where(Tag.book_id == ctx.require_book())
        .group_by(Tag.name)
        .order_by(func.count(TransactionTag.transaction_id).desc(), Tag.name)
    ).all()
    return [
        {"name": name, "transactions": int(count), "last_used_at": last.isoformat() if last else None}
        for name, count, last in rows
    ]
