"""识别规则手册 (设置 → AI 规则): the generic rules AI 识别 and its classification suggestions follow.

Versioned data: every save is a new version, an old one can be restored, and the text holds no site list, fee rate
or ignore list — those are the book's own data (counterparties, channels, aliases, fee rules, rules, categories)
and are added to each request at run time. Until the book saves its own, ``DEFAULT`` (ai/handbook.md,
distilled from docs/14) applies. The threshold says how sure an AI classification must be to go straight to
完成导入; below it the record waits in 待确认.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import AiHandbook
from bookkeeper.domain.errors import DomainError, version_conflict
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext

MAX_CHARS = 20_000
DEFAULT_THRESHOLD = Decimal("0.85")

DEFAULT = (Path(__file__).parent.parent / "ai" / "handbook.md").read_text(encoding="utf-8")


def view(item: AiHandbook | None) -> dict[str, Any]:
    if item is None:
        return {"version": 0, "content": DEFAULT, "threshold": float(DEFAULT_THRESHOLD), "is_default": True}
    return {
        "version": item.version,
        "content": item.content,
        "threshold": float(item.threshold),
        "note": item.note,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "is_default": False,
    }


def current(session: Session, book_id: str) -> AiHandbook | None:
    return session.execute(
        select(AiHandbook).where(AiHandbook.book_id == book_id).order_by(AiHandbook.version.desc()).limit(1)
    ).scalar_one_or_none()


def text_and_threshold(session: Session, book_id: str) -> tuple[str, Decimal, int]:
    item = current(session, book_id)
    return (item.content, item.threshold, item.version) if item else (DEFAULT, DEFAULT_THRESHOLD, 0)


def history(session: Session, book_id: str, limit: int = 30) -> list[AiHandbook]:
    return list(
        session.execute(
            select(AiHandbook).where(AiHandbook.book_id == book_id).order_by(AiHandbook.version.desc()).limit(limit)
        ).scalars()
    )


def save(
    session: Session,
    ctx: RequestContext,
    *,
    content: str,
    threshold: float | None,
    expected_version: int,
    note: str | None = None,
) -> AiHandbook:
    """A new version (the current one stays in the history). ``expected_version`` 0 = replacing the default."""
    ctx.require(Scope.RULES_WRITE)
    book_id = ctx.require_book()
    text = content.strip()
    if not text or len(text) > MAX_CHARS:
        raise DomainError("VALIDATION_FAILED", f"手册写 1–{MAX_CHARS} 个字。")
    latest = session.execute(
        select(func.coalesce(func.max(AiHandbook.version), 0)).where(AiHandbook.book_id == book_id)
    ).scalar_one()
    if expected_version != latest:
        raise version_conflict("识别规则手册", expected_version, latest)
    prior = current(session, book_id)
    level = Decimal(str(threshold)) if threshold is not None else (prior.threshold if prior else DEFAULT_THRESHOLD)
    if not Decimal("0.5") <= level <= Decimal("1"):
        raise DomainError("VALIDATION_FAILED", "把握程度门槛在 0.5–1 之间。")
    item = AiHandbook(
        id=new_id("hbk"),
        book_id=book_id,
        version=latest + 1,
        content=text,
        threshold=level.quantize(Decimal("0.01")),
        note=(note or "").strip()[:200] or None,
        created_by=ctx.actor.user_id,
    )
    session.add(item)
    session.flush()
    audit.ensure_change_set(session, ctx, "handbook.save")
    audit.record(
        session,
        ctx,
        "ai_handbook.save",
        "ai_handbook",
        item.id,
        before={"version": prior.version, "threshold": float(prior.threshold)} if prior else None,
        after={"version": item.version, "threshold": float(item.threshold), "chars": len(text), "note": item.note},
    )
    return item


def restore(session: Session, ctx: RequestContext, version: int, expected_version: int) -> AiHandbook:
    """Bring an older version back as the newest one."""
    book_id = ctx.require_book()
    old = session.execute(
        select(AiHandbook).where(AiHandbook.book_id == book_id, AiHandbook.version == version)
    ).scalar_one_or_none()
    if old is None:
        raise DomainError("NOT_FOUND", f"手册没有版本 {version}。")
    return save(
        session,
        ctx,
        content=old.content,
        threshold=float(old.threshold),
        expected_version=expected_version,
        note=f"恢复版本 {version}",
    )
