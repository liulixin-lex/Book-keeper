"""Change-set undo, pending work, MCP call log."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_operation, run_read
from bookkeeper.db.models import McpCall
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import work

router = APIRouter(prefix="/books/{book_id}", tags=["operations"])


class UndoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=200)


@router.post("/change-sets/{change_set_id}:undo")
def undo_change_set(
    book_id: str,
    change_set_id: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    body: UndoBody | None = None,
) -> JSONResponse:
    """Revert every write of one request by appending: delete what it created, restore what it deleted,
    put edited transactions back as they were."""
    raw = {"change_set_id": change_set_id, "reason": body.reason if body else None}
    return run_operation(request, db, auth.ctx, settings, "change_sets.undo", raw)


@router.get("/work-items")
def work_items(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    kinds: Annotated[list[str], Query(description="可重复或逗号分隔；默认全部")] = [],  # noqa: B006
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> dict[str, Any]:
    wanted = [k.strip() for v in kinds for k in v.split(",") if k.strip()] or None
    return run_read(db, lambda: work.collect(db, auth.ctx, wanted, limit), auth.ctx)


@router.get("/work-items/summary")
def work_summary(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        data = work.collect(db, auth.ctx, None, 0)
        return {"summary": data["summary"], "total": data["total"]}

    return run_read(db, load, auth.ctx)


@router.get("/mcp-calls")
def mcp_calls(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    tool: str | None = None,
    token_id: str | None = None,
    since: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    auth.ctx.require(Scope.ADMIN_READ)

    def load() -> list[dict[str, Any]]:
        stmt = select(McpCall).where(McpCall.book_id == book_id)
        if tool:
            stmt = stmt.where(McpCall.tool == tool)
        if token_id:
            stmt = stmt.where(McpCall.token_id == token_id)
        if since:
            stmt = stmt.where(McpCall.created_at >= since)
        rows = db.execute(stmt.order_by(McpCall.created_at.desc()).limit(limit)).scalars()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat(),
                "token_id": r.token_id,
                "client": r.client,
                "method": r.method,
                "tool": r.tool,
                "args": r.args,
                "ok": r.ok,
                "result_code": r.result_code,
                "summary": r.summary,
                "duration_ms": r.duration_ms,
                "change_set_id": r.change_set_id,
            }
            for r in rows
        ]

    return run_read(db, load, auth.ctx)
