"""Liveness and readiness probes (no authentication)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from bookkeeper import __version__
from bookkeeper.api.deps import DbDep
from bookkeeper.db.models import WorkerHeartbeat
from bookkeeper.db.roles import REQUIRED_TRIGGERS
from bookkeeper.paths import ALEMBIC_INI

router = APIRouter(tags=["health"])

WORKER_STALE_AFTER = timedelta(minutes=2)


def alembic_head() -> str | None:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return script.get_current_head()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
def readyz(request: Request, db: DbDep) -> JSONResponse:
    checks: dict[str, object] = {}
    ok = True
    try:
        with db.begin():
            db.execute(text("SELECT 1"))
            current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            head = request.app.state.alembic_head
            checks["migrations"] = {"current": current, "head": head, "ok": current == head}
            ok &= current == head
            present = set(
                db.execute(
                    text("SELECT tgname FROM pg_trigger WHERE tgname = ANY(:names)"),
                    {"names": list(REQUIRED_TRIGGERS)},
                ).scalars()
            )
            missing = sorted(set(REQUIRED_TRIGGERS) - present)
            checks["triggers"] = {"missing": missing, "ok": not missing}
            ok &= not missing
            last_beat = db.execute(select(func.max(WorkerHeartbeat.beat_at))).scalar()
            fresh = last_beat is not None and datetime.now(UTC) - last_beat < WORKER_STALE_AFTER
            checks["worker"] = {
                "last_beat": last_beat.isoformat() if last_beat else None,
                "ok": fresh,
            }
        checks["database"] = {"ok": True}
    except Exception as exc:
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        ok = False
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)
