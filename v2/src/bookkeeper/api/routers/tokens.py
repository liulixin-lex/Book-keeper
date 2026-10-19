"""API tokens."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Tier
from bookkeeper.services import tokens as service

router = APIRouter(prefix="/books/{book_id}/tokens", tags=["tokens"])


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    tier: Tier = Tier.USER_READ
    mcp_enabled: bool = False
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    never_expires: bool = False
    ip_allowlist: list[str] | None = None


@router.get("")
def list_tokens(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    return run_read(db, lambda: service.list_views(db, auth.ctx), auth.ctx)


@router.post("", status_code=201)
def create_token(
    book_id: str,
    body: TokenCreate,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        issued = service.create_token(
            db,
            auth.ctx,
            name=body.name,
            tier=body.tier,
            mcp_enabled=body.mcp_enabled,
            expires_in_days=body.expires_in_days,
            never_expires=body.never_expires,
            ip_allowlist=body.ip_allowlist,
            default_days=settings.token_default_days,
        )
        return service.token_view(issued.token) | {"token": issued.plaintext}

    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "tokens.create",
        body.model_dump(mode="json"),
        apply,
        status_code=201,
        secret_fields=("token",),
    )


@router.post("/{token_id}:revoke")
def revoke_token(
    book_id: str, token_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "tokens.revoke",
        {"token_id": token_id},
        lambda: service.token_view(service.revoke_token(db, auth.ctx, token_id)),
    )


@router.post("/{token_id}:rotate")
def rotate_token(
    book_id: str, token_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        issued = service.rotate_token(db, auth.ctx, token_id)
        return service.token_view(issued.token) | {"token": issued.plaintext}

    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "tokens.rotate",
        {"token_id": token_id},
        apply,
        status_code=201,
        secret_fields=("token",),
    )
