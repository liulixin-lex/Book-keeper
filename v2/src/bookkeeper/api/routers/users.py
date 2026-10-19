"""System users (superadmin only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.db.models import User
from bookkeeper.services import identity

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=1024)
    is_superadmin: bool = False


@router.get("")
def list_users(auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require_superadmin()
    return run_read(
        db,
        lambda: [identity.user_view(u) for u in db.execute(select(User).order_by(User.created_at)).scalars()],
        auth.ctx,
    )


@router.post("", status_code=201)
def create_user(body: UserCreate, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep) -> JSONResponse:
    auth.ctx.require_superadmin()
    # Passwords never enter the idempotency hash.
    payload = body.model_dump(exclude={"password"})

    def apply() -> dict[str, Any]:
        user = identity.create_user(
            db,
            auth.ctx,
            email=body.email,
            display_name=body.display_name,
            password=body.password,
            is_superadmin=body.is_superadmin,
        )
        return identity.user_view(user)

    return run_write(request, db, auth.ctx, settings, "users.create", payload, apply, status_code=201)
