"""API tokens (docs/08-rest-api.md §3.3, docs/10-security-operations.md §1.2)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import ApiToken
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import ROLE_CAPS, Preset, Scope, parse_scopes, scopes_for_preset
from bookkeeper.security.secrets import new_api_token, token_display_prefix, token_hash
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext


def token_view(token: ApiToken) -> dict[str, Any]:
    return {
        "id": token.id,
        "book_id": token.book_id,
        "user_id": token.user_id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "scopes": sorted(token.scopes),
        "preset": token.preset,
        "mcp_enabled": token.mcp_enabled,
        "ip_allowlist": token.ip_allowlist,
        "rate_limit_per_min": token.rate_limit_per_min,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
        "revoked_at": token.revoked_at.isoformat() if token.revoked_at else None,
        "created_at": token.created_at.isoformat() if token.created_at else None,
        "version": token.version,
    }


@dataclass(frozen=True)
class IssuedToken:
    token: ApiToken
    plaintext: str


def create_token(
    session: Session,
    ctx: RequestContext,
    *,
    name: str,
    preset: Preset = Preset.READER,
    scopes: Sequence[str] | None = None,
    mcp_enabled: bool = False,
    expires_in_days: int | None = None,
    never_expires: bool = False,
    ip_allowlist: Sequence[str] | None = None,
    default_days: int = 90,
) -> IssuedToken:
    """Create a token for the calling user, capped by the user's role in this book."""
    book_id = ctx.require_book()
    role = ctx.actor.role
    if ctx.actor.user_id is None or role is None:
        raise DomainError("FORBIDDEN_SCOPE", "只有账套成员可以创建令牌。")
    if ctx.actor.type == "token" and Scope.ADMIN not in ctx.actor.scopes:
        raise DomainError("FORBIDDEN_SCOPE", "用令牌创建令牌需要 admin 权限。")
    if preset is Preset.CUSTOM:
        if not scopes:
            raise DomainError("VALIDATION_FAILED", "自定义预设必须给出 scopes。")
        try:
            requested = parse_scopes(scopes)
        except ValueError as exc:
            raise DomainError("VALIDATION_FAILED", str(exc)) from exc
        excess = requested - ROLE_CAPS[role]
        if excess:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                f"令牌权限不能超过你的角色：{', '.join(sorted(s.value for s in excess))}。",
            )
        granted = requested
    else:
        if scopes:
            raise DomainError("VALIDATION_FAILED", "使用预设时不要同时给出 scopes。")
        granted = scopes_for_preset(preset, role)
    if ctx.actor.type == "token":
        granted = granted & ctx.actor.scopes
    if never_expires and Scope.ADMIN not in ctx.actor.scopes:
        raise DomainError("FORBIDDEN_SCOPE", "永不过期的令牌需要 admin 权限。")
    if never_expires:
        expires_at = None
    else:
        days = expires_in_days or default_days
        if not 1 <= days <= 3650:
            raise DomainError("VALIDATION_FAILED", "有效期须在 1–3650 天之间。")
        expires_at = datetime.now(UTC) + timedelta(days=days)
    plaintext = new_api_token()
    token = ApiToken(
        id=new_id("tok"),
        book_id=book_id,
        user_id=ctx.actor.user_id,
        name=name.strip(),
        token_hash=token_hash(plaintext),
        token_prefix=token_display_prefix(plaintext),
        scopes=sorted(s.value for s in granted),
        preset=preset.value,
        mcp_enabled=mcp_enabled,
        ip_allowlist=list(ip_allowlist) if ip_allowlist else None,
        expires_at=expires_at,
        created_by=ctx.actor.user_id,
    )
    session.add(token)
    session.flush()
    audit.record(session, ctx, "token.create", "api_token", token.id, after=token_view(token))
    return IssuedToken(token, plaintext)


def list_tokens(session: Session, ctx: RequestContext) -> list[ApiToken]:
    query = select(ApiToken).where(ApiToken.book_id == ctx.require_book())
    if Scope.ADMIN not in ctx.actor.scopes:
        query = query.where(ApiToken.user_id == ctx.actor.user_id)
    return list(session.execute(query.order_by(ApiToken.created_at)).scalars())


def _load_manageable(session: Session, ctx: RequestContext, token_id: str) -> ApiToken:
    token = session.get(ApiToken, token_id, with_for_update=True)
    if token is None or token.book_id != ctx.require_book():
        raise not_found("令牌", token_id)
    if token.user_id != ctx.actor.user_id and Scope.ADMIN not in ctx.actor.scopes:
        raise DomainError("FORBIDDEN_SCOPE", "只能管理自己的令牌。")
    return token


def revoke_token(session: Session, ctx: RequestContext, token_id: str) -> ApiToken:
    token = _load_manageable(session, ctx, token_id)
    if token.revoked_at is not None:
        return token
    before = token_view(token)
    token.revoked_at = datetime.now(UTC)
    token.version += 1
    session.flush()
    audit.record(session, ctx, "token.revoke", "api_token", token.id, before=before, after=token_view(token))
    from bookkeeper.services import oauth  # an OAuth-issued token: end the grant so it cannot be refreshed

    for family_id in oauth.families_of_api_token(session, token.id):
        oauth.revoke_family(session, family_id, "token_revoked")
    return token


def rotate_token(session: Session, ctx: RequestContext, token_id: str) -> IssuedToken:
    """Issue a new secret with the same settings and revoke the old one."""
    old = _load_manageable(session, ctx, token_id)
    if old.revoked_at is not None:
        raise DomainError("INVALID_STATE", "已吊销的令牌不能轮换。")
    plaintext = new_api_token()
    new = ApiToken(
        id=new_id("tok"),
        book_id=old.book_id,
        user_id=old.user_id,
        name=old.name,
        token_hash=token_hash(plaintext),
        token_prefix=token_display_prefix(plaintext),
        scopes=list(old.scopes),
        preset=old.preset,
        mcp_enabled=old.mcp_enabled,
        ip_allowlist=old.ip_allowlist,
        rate_limit_per_min=old.rate_limit_per_min,
        expires_at=old.expires_at,
        created_by=ctx.actor.user_id or old.created_by,
    )
    old.revoked_at = datetime.now(UTC)
    old.version += 1
    session.add(new)
    session.flush()
    audit.record(session, ctx, "token.rotate", "api_token", old.id, after={"replaced_by": new.id})
    audit.record(session, ctx, "token.create", "api_token", new.id, after=token_view(new))
    return IssuedToken(new, plaintext)
