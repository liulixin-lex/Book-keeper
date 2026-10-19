"""Books and members."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Role, Scope
from bookkeeper.services import books as service
from bookkeeper.services.identity import user_view

router = APIRouter(tags=["books"])


class BookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    base_commodity: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    timezone: str = "Asia/Shanghai"
    owner_user_id: str | None = None


class BookUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    name: str | None = Field(default=None, min_length=1, max_length=80)
    timezone: str | None = None
    rounding_mode: str | None = Field(default=None, pattern=r"^(half_up|half_even)$")
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    journal_codes: list[str] | None = Field(default=None, min_length=1)
    rounding_tolerance_per_line: int | None = Field(default=None, ge=0, le=10)
    fx_lookback_days: int | None = Field(default=None, ge=0, le=31)
    settings: dict[str, Any] | None = None


class MemberSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role


@router.get("/books")
def list_books(auth: AuthDep, db: DbDep) -> dict[str, Any]:
    def load() -> list[dict[str, Any]]:
        return [
            service.book_view(book) | {"role": role}
            for book, role in service.list_books_for_user(db, auth.auth.user.id)
        ]

    return run_read(db, load, auth.ctx)


@router.post("/books", status_code=201)
def create_book(body: BookCreate, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep) -> JSONResponse:
    def apply() -> dict[str, Any]:
        book = service.create_book(
            db,
            auth.ctx,
            name=body.name,
            base_commodity=body.base_commodity,
            timezone=body.timezone,
            owner_user_id=body.owner_user_id,
        )
        return service.book_view(book)

    return run_write(request, db, auth.ctx, settings, "books.create", body.model_dump(), apply, status_code=201)


@router.get("/books/{book_id}")
def get_book(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(
        db,
        lambda: service.book_view(service.get_book(db, book_id)) | {"role": auth.ctx.actor.role},
        auth.ctx,
    )


@router.patch("/books/{book_id}")
def update_book(
    book_id: str,
    body: BookUpdate,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})

    def apply() -> dict[str, Any]:
        return service.book_view(service.update_book(db, auth.ctx, body.expected_version, changes))

    return run_write(request, db, auth.ctx, settings, "books.update", body.model_dump(exclude_unset=True), apply)


@router.get("/books/{book_id}/members")
def list_members(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    def load() -> list[dict[str, Any]]:
        return [
            {"user": user_view(user), "role": member.role, "since": member.created_at.isoformat()}
            for member, user in service.list_members(db, auth.ctx)
        ]

    return run_read(db, load, auth.ctx)


@router.put("/books/{book_id}/members/{user_id}")
def set_member(
    book_id: str,
    user_id: str,
    body: MemberSet,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        member = service.set_member(db, auth.ctx, user_id, body.role)
        return {"user_id": member.user_id, "role": member.role}

    return run_write(request, db, auth.ctx, settings, "members.set", body.model_dump(mode="json"), apply)


@router.delete("/books/{book_id}/members/{user_id}")
def remove_member(
    book_id: str, user_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        service.remove_member(db, auth.ctx, user_id)
        return {"user_id": user_id, "removed": True}

    return run_write(request, db, auth.ctx, settings, "members.remove", {"user_id": user_id}, apply)
