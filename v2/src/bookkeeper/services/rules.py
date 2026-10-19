"""Classification rules: save (versioned), enable / disable, dry-run test, apply to unbooked records."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import ImportSource, Rule, SourceRecord
from bookkeeper.domain import rules as engine
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit, imports
from bookkeeper.services.context import RequestContext


def view(rule: Rule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "code": rule.code,
        "name": rule.name,
        "stage": rule.stage,
        "priority": rule.priority,
        "condition": rule.condition,
        "actions": rule.actions,
        "stop_processing": rule.stop_processing,
        "is_active": rule.is_active,
        "hit_count": rule.hit_count,
        "last_hit_at": rule.last_hit_at.isoformat() if rule.last_hit_at else None,
        "specificity": engine.specificity(rule.condition),
        "note": rule.note,
        "version": rule.version,
    }


def get_rule(session: Session, book_id: str, ref: str) -> Rule:
    rule = session.execute(
        select(Rule).where(Rule.book_id == book_id, (Rule.id == ref) | (Rule.code == ref))
    ).scalar_one_or_none()
    if rule is None:
        raise not_found("规则", ref)
    return rule


def list_rules(session: Session, book_id: str) -> list[Rule]:
    return list(
        session.execute(
            select(Rule).where(Rule.book_id == book_id).order_by(Rule.stage, Rule.priority, Rule.code)
        ).scalars()
    )


def save_rule(session: Session, ctx: RequestContext, data: dict[str, Any]) -> Rule:
    """Create a rule or replace an existing one with the same code (version + 1)."""
    ctx.require(Scope.RULES_WRITE)
    book_id = ctx.require_book()
    stage = data.get("stage") or "classify"
    if stage not in engine.STAGES:
        raise DomainError("VALIDATION_FAILED", f"stage 只能是 {', '.join(engine.STAGES)}。")
    engine.validate_condition(data["condition"])
    engine.validate_actions(data["actions"])
    rule = session.execute(
        select(Rule).where(Rule.book_id == book_id, Rule.code == data["code"]).with_for_update()
    ).scalar_one_or_none()
    before = view(rule) if rule else None
    if rule is None:
        rule = Rule(
            id=new_id("rul"),
            book_id=book_id,
            code=data["code"],
            name=data.get("name") or data["code"],
            condition=data["condition"],
            actions=data["actions"],
        )
        session.add(rule)
    else:
        rule.version += 1
    rule.name = data.get("name") or rule.name
    rule.stage = stage
    rule.priority = int(data.get("priority", rule.priority if before else 100))
    rule.condition = data["condition"]
    rule.actions = data["actions"]
    rule.stop_processing = bool(data.get("stop_processing", False))
    rule.is_active = bool(data.get("is_active", True))
    rule.note = data.get("note")
    session.flush()
    audit.record(session, ctx, "rule.save", "rule", rule.id, before=before, after=view(rule))
    return rule


def set_active(session: Session, ctx: RequestContext, ref: str, active: bool) -> Rule:
    ctx.require(Scope.RULES_WRITE)
    rule = get_rule(session, ctx.require_book(), ref)
    rule.is_active = active
    rule.version += 1
    session.flush()
    audit.record(
        session, ctx, "rule.enable" if active else "rule.disable", "rule", rule.id, after={"is_active": active}
    )
    return rule


def try_rule(
    session: Session,
    ctx: RequestContext,
    *,
    rule: dict[str, Any] | None = None,
    code: str | None = None,
    source: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Which records the rule would hit and what it would change. Writes nothing."""
    ctx.require(Scope.LEDGER_READ)
    book_id = ctx.require_book()
    if rule is None:
        if not code:
            raise DomainError("VALIDATION_FAILED", "请提供 rule（待测试的规则）或 code（已有规则）。")
        row = get_rule(session, book_id, code)
        rule = {
            "code": row.code,
            "stage": row.stage,
            "priority": row.priority,
            "condition": row.condition,
            "actions": row.actions,
            "stop_processing": row.stop_processing,
        }
    engine.validate_condition(rule["condition"])
    engine.validate_actions(rule["actions"])
    trial = engine.RuleDef(
        "trial",
        rule.get("code", "trial"),
        0,
        rule.get("stage", "classify"),
        int(rule.get("priority", 100)),
        rule["condition"],
        rule["actions"],
    )
    stmt = select(SourceRecord).where(SourceRecord.book_id == book_id, SourceRecord.status != "duplicate")
    if source:
        stmt = stmt.where(SourceRecord.source_id == imports.get_source(session, book_id, source).id)
    if date_from:
        stmt = stmt.where(SourceRecord.effective_date >= date_from)
    if date_to:
        stmt = stmt.where(SourceRecord.effective_date <= date_to)
    records = list(session.execute(stmt.order_by(SourceRecord.occurred_at.desc()).limit(limit)).scalars())
    sources = {s.id: s for s in session.execute(select(ImportSource).where(ImportSource.book_id == book_id)).scalars()}
    hits = []
    for rec in records:
        facts = imports.facts_for(session, sources[rec.source_id], rec)
        hit, captures = engine.evaluate(trial.condition, facts)
        if not hit:
            continue
        outcome = engine.apply([trial], facts, dict(rec.classification), rec.locked_fields)
        hits.append(
            {
                "record_id": rec.id,
                "status": rec.status,
                "date": rec.effective_date.isoformat(),
                "description": rec.description,
                "counterparty_text": rec.counterparty_text,
                "captures": captures,
                "changes": outcome.trace[0]["changes"] if outcome.trace else [],
                "booked": rec.status == "booked",
            }
        )
    return {
        "checked": len(records),
        "hits": len(hits),
        "samples": hits[:50],
        "booked_hits": sum(1 for h in hits if h["booked"]),
    }


def apply_rules(
    session: Session, ctx: RequestContext, *, batch_id: str | None = None, record_ids: list[str] | None = None
) -> dict[str, Any]:
    """Re-run all active rules on unbooked records; booked ones change by editing their transaction."""
    count = imports.reclassify(session, ctx, record_ids=record_ids, batch_id=batch_id)
    audit.record(session, ctx, "rules.apply", "rule", None, after={"records": count, "batch_id": batch_id})
    return {"reclassified": count}
