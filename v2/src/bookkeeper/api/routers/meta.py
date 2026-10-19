"""Capabilities and display labels (docs/14-taxonomy-and-copy.md §10)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from bookkeeper import __version__
from bookkeeper.api.deps import AuthDep, DbDep, run_read
from bookkeeper.domain import labels

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/capabilities")
def capabilities(request: Request, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    settings = request.app.state.settings

    def load() -> dict[str, Any]:
        return {
            "version": __version__,
            "auth_method": "token" if auth.auth.token else "session",
            "role": auth.ctx.actor.role,
            "scopes": sorted(s.value for s in auth.ctx.actor.scopes),
            "features": {
                "mcp": settings.mcp_enabled,
                "mcp_write": settings.mcp_write_enabled,
                "ledger": True,
                "imports": True,
                "ai_extract": bool(settings.ai_key),
            },
            "limits": {
                "upload_max_bytes": settings.upload_max_bytes,
                "page_max": 200,
                "ai_max_files": settings.ai_max_files,
            },
        }

    return run_read(db, load, auth.ctx)


@router.get("/enums")
def enums(auth: AuthDep) -> dict[str, Any]:
    return {"data": labels.ENUM_LABELS, "meta": {"request_id": auth.ctx.request_id}, "warnings": []}
