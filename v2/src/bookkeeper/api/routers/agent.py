"""AI 助手: one instruction, a step timeline, a question when it needs one, and one-click undo of the whole run
(its change set, via /change-sets/{id}:undo). Started and answered from the web app only (docs/19 §3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.ai import agent as service
from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Tier

router = APIRouter(prefix="/books/{book_id}/agent", tags=["agent"])


class RunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=1, max_length=service.MAX_INSTRUCTION)
    tier: Tier = Tier.USER_WRITE
    file_ids: list[str] = Field(default_factory=list, max_length=service.MAX_FILES)
    playbook: str | None = Field(default=None, max_length=80)


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=2000)


@router.get("/runs")
def list_runs(book_id: str, auth: AuthDep, db: DbDep, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """Recent runs: your own; with admin:read, everyone's."""
    return run_read(db, lambda: [service.run_view(r) for r in service.list_runs(db, auth.ctx, limit)], auth.ctx)


@router.post("/runs", status_code=201)
def start_run(
    book_id: str, body: RunIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Start a run. It works with your permissions ∩ the chosen tier; with files attached it only reads and stages."""

    def apply() -> dict[str, Any]:
        run = service.start(
            db,
            auth.ctx,
            settings,
            instruction=body.instruction,
            tier=body.tier,
            file_ids=body.file_ids,
            playbook=body.playbook,
        )
        return service.run_view(run)

    return run_write(
        request, db, auth.ctx, settings, "agent.start", body.model_dump(mode="json"), apply, status_code=201
    )


@router.get("/runs/{run_id}")
def get_run(book_id: str, run_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    """The run and its steps: instruction, model turns, tool calls with results, questions and answers."""

    return run_read(db, lambda: service.get_run(db, auth.ctx, run_id), auth.ctx)


@router.post("/runs/{run_id}:answer")
def answer_run(
    book_id: str, run_id: str, body: AnswerIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Answer the run's question; it continues from where it stopped."""
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "agent.answer",
        {"run_id": run_id, "answer": body.answer},
        lambda: service.run_view(service.answer(db, auth.ctx, run_id, body.answer)),
    )


@router.post("/runs/{run_id}:cancel")
def cancel_run(
    book_id: str, run_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Stop a run. Writes it already made stay, and undo together through its change set."""
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "agent.cancel",
        {"run_id": run_id},
        lambda: service.run_view(service.cancel(db, auth.ctx, run_id)),
    )
