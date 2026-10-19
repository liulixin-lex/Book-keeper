"""Built-in maintenance tasks and their default schedules."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import AuditHead, Book, Commodity, McpCall
from bookkeeper.db.session import rowcount
from bookkeeper.fx_providers import frankfurter
from bookkeeper.jobs.registry import task
from bookkeeper.services import audit, checks, idempotency, identity, ratelimit, reference
from bookkeeper.services.context import Actor, RequestContext

DEFAULT_SCHEDULES: tuple[tuple[str, str], ...] = (
    ("idempotency.cleanup", "every:3600"),
    ("sessions.cleanup", "every:3600"),
    ("audit.verify_chains", "daily:04:00"),
    ("fx.fetch", "daily:23:30"),
    ("checks.run", "daily:04:30"),
    ("maintenance.purge", "daily:03:30"),
    ("exports.archive", "daily:05:00"),
)


@task("system.noop")
def noop(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("fail"):
        raise RuntimeError(str(payload["fail"]))
    return {"echo": payload.get("echo")}


@task("maintenance.purge")
def purge_operational_data(session: Session, payload: dict[str, Any]) -> dict[str, int]:
    """MCP call logs (180 days), stale rate-limit windows, old OAuth requests and codes."""
    now = datetime.now(UTC)
    calls = rowcount(session.execute(delete(McpCall).where(McpCall.created_at < now - timedelta(days=180))))
    from bookkeeper.services import oauth

    return {"mcp_calls": calls, "rate_counters": ratelimit.purge(session)} | oauth.purge(session)


@task("idempotency.cleanup")
def cleanup_idempotency(session: Session, payload: dict[str, Any]) -> dict[str, int]:
    return {"deleted": idempotency.purge_expired(session)}


@task("sessions.cleanup")
def cleanup_sessions(session: Session, payload: dict[str, Any]) -> dict[str, int]:
    return {"deleted": identity.purge_sessions(session)}


@task("audit.verify_chains")
def verify_audit_chains(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    scopes = payload.get("scopes") or list(session.execute(select(AuditHead.scope)).scalars())
    results = [audit.verify_chain(session, scope) for scope in scopes]
    failures = [r.__dict__ for r in results if not r.ok]
    if failures:
        raise RuntimeError(f"audit chain verification failed: {failures}")
    return {"verified": {r.scope: r.events for r in results}}


@task("fx.fetch")
def fetch_fx_rates(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Fetch reference rates (foreign fiat → base) for every active book's base commodity."""
    fetcher = frankfurter.http_get_json  # looked up at call time (tests patch it)
    fiat = [
        c
        for c in session.execute(
            select(Commodity.code).where(Commodity.kind == "fiat", Commodity.is_active.is_(True))
        ).scalars()
    ]
    stored: list[str] = []
    for base in sorted(
        {b.base_commodity for b in session.execute(select(Book).where(Book.status == "active")).scalars()}
    ):
        on = date.fromisoformat(payload["date"]) if payload.get("date") else datetime.now(UTC).date()
        quotes = [c for c in fiat if c != base]
        # Frankfurter quotes 1 unit of ``base``; we store foreign → base, so query per foreign currency.
        for foreign in quotes:
            for rate in frankfurter.fetch(foreign, [base], on, fetcher=fetcher):
                reference.upsert_fx_rate(
                    session,
                    base=rate.base,
                    quote=rate.quote,
                    rate_date=rate.rate_date,
                    rate=rate.rate,
                    rate_type="reference",
                    source="frankfurter",
                    raw=rate.raw,
                )
                stored.append(f"{rate.base}/{rate.quote}@{rate.rate_date}")
    return {"stored": stored}


@task("checks.run")
def run_health_checks(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    results = {}
    for book in session.execute(select(Book).where(Book.status == "active")).scalars():
        ctx = RequestContext(actor=Actor.system(), channel="worker", book_id=book.id)
        run = checks.run_checks(session, ctx, payload.get("codes"), trigger="scheduled")
        results[book.id] = run.summary
    return results


@task("exports.archive")
def archive_exports(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Readable monthly archive (Beancount + CSV) under ``<data>/archive``; months rewritten when they change."""
    from bookkeeper.config import get_settings
    from bookkeeper.services import exports

    root = get_settings().data_dir / "archive"
    written: dict[str, list[str]] = {}
    for book in session.execute(select(Book).where(Book.status == "active")).scalars():
        today = datetime.now(ZoneInfo(book.timezone)).date()
        months = exports.archive_months(session, book, root, today)
        if months:
            written[book.id] = months
    return {"written": written}


@task("imports.ai_extract", own_session=True)
def ai_extract_batch(session_factory: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Read an AI 识别 batch's files with Claude and stage the records. The read happens between two short
    transactions; a failure marks the batch 识别失败 with the reason, and the owner can retry it."""
    from bookkeeper.config import get_settings
    from bookkeeper.db.models import ImportBatch, ImportSource, StoredFile
    from bookkeeper.domain.errors import DomainError
    from bookkeeper.files.storage import ContentStore
    from bookkeeper.services import ai_extract, imports, reference

    settings = get_settings()
    batch_id, attempt = str(payload["batch_id"]), payload.get("attempt")
    with session_factory() as session, session.begin():
        batch = session.get(ImportBatch, batch_id)
        if batch is None or not imports.wants_read(batch, attempt):  # set aside, timed out, or a newer retry
            return {"skipped": batch_id}
        src = session.get(ImportSource, batch.source_id)
        assert src is not None
        order = list(batch.summary.get("files") or [batch.file_id])
        stored = {f.id: f for f in session.execute(select(StoredFile).where(StoredFile.id.in_(order))).scalars()}
        store = ContentStore(settings.files_dir)
        files = [
            (stored[i].original_name, store.open(stored[i].storage_key).read(), stored[i].mime_type)
            for i in order
            if i in stored
        ]
        hint, commodity = str(src.config.get("hint") or ""), src.config.get("commodity")
        book_id = batch.book_id
        known = reference.site_hosts(session, book_id)
    try:
        extracted = ai_extract.extract(
            files, hint=hint, commodity=str(commodity) if commodity else None, settings=settings, known_hosts=known
        )
    except Exception as exc:  # the batch must not stay 识别中: record why and let the owner retry
        message = exc.detail if isinstance(exc, DomainError) else f"识别出错：{exc}"
        with session_factory() as session, session.begin():
            imports.fail_extraction(session, batch_id, message, attempt)
        return {"failed": message}
    with session_factory() as session, session.begin():
        ctx = RequestContext(actor=Actor.system(), channel="worker", book_id=book_id)
        imports.finish_extraction(session, ctx, batch_id, extracted, attempt)
    return {"records": len(extracted.records)}
