"""Login, logout, current user, password change."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import (
    SESSION_COOKIE,
    AuthDep,
    DbDep,
    SettingsDep,
    anonymous_context,
    run_read,
    run_write,
)
from bookkeeper.api.envelope import envelope
from bookkeeper.services import books as books_service
from bookkeeper.services import identity
from bookkeeper.services.context import RequestContext
from bookkeeper.services.tokens import token_view

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class PasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


@router.post("/login")
def login(
    body: LoginIn,
    db: DbDep,
    settings: SettingsDep,
    ctx: Annotated[RequestContext, Depends(anonymous_context)],
) -> JSONResponse:
    with db.begin():
        outcome = identity.login(db, ctx, settings, body.email, body.password)
    if outcome.error is not None:
        raise outcome.error
    result = outcome.result
    assert result is not None
    data = {
        "user": identity.user_view(result.user),
        "csrf_token": result.csrf_token,
        "expires_at": result.expires_at.isoformat(),
    }
    response = JSONResponse(envelope(data, ctx))
    response.set_cookie(
        SESSION_COOKIE,
        result.session_token,
        max_age=settings.session_absolute_days * 86400,
        httponly=True,
        secure=settings.public_url.startswith("https://"),
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
def logout(auth: AuthDep, db: DbDep) -> JSONResponse:
    if auth.session_token:
        with db.begin():
            identity.logout(db, auth.session_token)
    response = JSONResponse(envelope({"logged_out": True}, auth.ctx))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
def me(auth: AuthDep, db: DbDep) -> dict[str, Any]:
    def load() -> dict[str, Any]:
        memberships = books_service.list_books_for_user(db, auth.auth.user.id)
        data: dict[str, Any] = {
            "user": identity.user_view(auth.auth.user),
            "books": [{"id": b.id, "name": b.name, "role": role} for b, role in memberships],
            "auth_method": "token" if auth.auth.token else "session",
        }
        if auth.auth.token is not None:
            data["token"] = token_view(auth.auth.token)
            data["scopes"] = sorted(s.value for s in auth.ctx.actor.scopes)
        if auth.auth.session is not None:
            data["csrf_token"] = auth.auth.session.csrf_secret
        return data

    return run_read(db, load, auth.ctx)


@router.post("/password")
def change_password(
    body: PasswordIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    user_id = auth.auth.user.id

    def apply() -> dict[str, Any]:
        identity.change_password(db, auth.ctx, user_id, body.current_password, body.new_password, auth.session_token)
        return {"changed": True}

    return run_write(request, db, auth.ctx, settings, "auth.password", {"user": user_id}, apply)
