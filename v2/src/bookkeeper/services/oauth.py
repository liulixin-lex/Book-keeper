"""OAuth 2.1 authorization server for remote MCP clients (claude.ai, ChatGPT connectors, …), docs/09 §2.

Flow: dynamic client registration → /oauth/authorize (validated by the MCP SDK) stores a pending
request → the user signs in and picks a book and an access level on our page → a single-use code
bound to the client, redirect URI and PKCE challenge → /oauth/token exchanges it for an ordinary
API token (``mcp_enabled``, the chosen tier capped by the user's role) plus a
refresh token. Refresh tokens rotate on every use; presenting a used one revokes the whole family.
All secrets (client secrets, codes, refresh tokens, API tokens) are stored as SHA-256 hashes.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from bookkeeper.config import Settings
from bookkeeper.db.models import (
    ApiToken,
    Book,
    BookMember,
    OAuthClient,
    OAuthCode,
    OAuthRefreshToken,
    OAuthRequest,
    User,
)
from bookkeeper.db.session import rowcount
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import ROLE_CAPS, ROLE_TIERS, Role, Tier, tier_for_role, tier_scopes
from bookkeeper.security.secrets import constant_time_equals, random_base62, token_hash
from bookkeeper.services import audit, identity, tokens
from bookkeeper.services.context import Actor, RequestContext

REQUEST_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=5)


class OAuthError(Exception):
    """Protocol-level failure; ``error`` is an RFC 6749 / 7591 error code."""

    def __init__(self, error: str, description: str) -> None:
        super().__init__(description)
        self.error = error
        self.description = description


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    scope: str


def _now() -> datetime:
    return datetime.now(UTC)


def _ctx(ip: str | None = None) -> RequestContext:
    return RequestContext(actor=Actor.system(), channel="api", ip=ip)


# ------------------------------------------------------------------ clients


def _redirect_allowed(uri: str) -> bool:
    parts = urlsplit(uri)
    if parts.fragment or not parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    if parts.scheme != "http":
        return False
    host = parts.hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def register_client(session: Session, registration: dict[str, Any], ip: str | None) -> None:
    uris = [str(u) for u in registration.get("redirect_uris") or []]
    bad = [u for u in uris if not _redirect_allowed(u)]
    if not uris or bad:
        raise OAuthError("invalid_redirect_uri", "回调地址必须是 https，或本机回环地址的 http：" + "、".join(bad))
    secret = registration.pop("client_secret", None)
    client = OAuthClient(
        client_id=str(registration["client_id"]),
        secret_hash=token_hash(secret) if secret else None,
        client_name=(registration.get("client_name") or "")[:100] or None,
        registration=registration,
        registered_ip=ip,
    )
    session.add(client)
    session.flush()
    audit.record(
        session,
        _ctx(ip),
        "oauth.client_register",
        "oauth_client",
        client.client_id,
        after={"client_name": client.client_name, "redirect_uris": uris},
        scope="global",
        in_change_set=False,
    )


def load_client(session: Session, client_id: str) -> dict[str, Any] | None:
    """Registration data with ``client_secret`` replaced by its hash (compared by the hashed authenticator)."""
    client = session.get(OAuthClient, client_id)
    if client is None:
        return None
    return dict(client.registration) | {"client_secret": client.secret_hash}


def client_name(session: Session, client_id: str) -> str:
    client = session.get(OAuthClient, client_id)
    return (client.client_name if client else None) or "未命名的 AI 客户端"


# ------------------------------------------------------------------ authorization requests and consent


def create_request(session: Session, client_id: str, params: dict[str, Any], settings: Settings) -> OAuthRequest:
    resource = params.get("resource")
    if resource and resource.rstrip("/") != mcp_resource(settings).rstrip("/"):
        raise OAuthError("invalid_target", f"资源 {resource} 不是本服务。")
    request = OAuthRequest(
        id=random_base62(32),
        client_id=client_id,
        params=params,
        csrf=random_base62(32),
        expires_at=_now() + REQUEST_TTL,
    )
    session.add(request)
    session.flush()
    return request


def pending_request(session: Session, request_id: str, csrf: str | None = None) -> OAuthRequest:
    request = session.get(OAuthRequest, request_id, with_for_update=True)
    if request is None or request.completed_at is not None or request.expires_at < _now():
        raise DomainError("INVALID_STATE", "授权请求不存在或已过期，请回到 AI 客户端重新发起连接。")
    if csrf is not None and not constant_time_equals(csrf, request.csrf):
        raise DomainError("CSRF_FAILED", "页面已失效，请回到 AI 客户端重新发起连接。")
    return request


def sign_in(
    session: Session, settings: Settings, request: OAuthRequest, email: str, password: str, ip: str | None
) -> DomainError | None:
    """Check credentials (lockout and audit as for UI login); remembers the user on the request."""
    user, error = identity.check_credentials(session, _ctx(ip), settings, email, password)
    if user is None:
        return error
    request.user_id = user.id
    return None


def memberships(session: Session, user_id: str) -> list[tuple[Book, Role]]:
    rows = session.execute(
        select(Book, BookMember.role)
        .join(BookMember, BookMember.book_id == Book.id)
        .where(BookMember.user_id == user_id, Book.status == "active")
        .order_by(Book.name)
    ).all()
    return [(book, Role(role)) for book, role in rows]


def _redirect(base: str, **params: str | None) -> str:
    parts = urlsplit(base)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(k, v) for k, v in params.items() if v is not None]
    return urlunsplit(parts._replace(query=urlencode(query)))


def approve(session: Session, request: OAuthRequest, book_id: str, tier: str, ip: str | None, issuer: str) -> str:
    if request.user_id is None:
        raise DomainError("UNAUTHENTICATED", "请先登录。")
    role = identity.member_role(session, book_id, request.user_id)
    if role is None:
        raise DomainError("FORBIDDEN_SCOPE", "你不是该账套的成员。")
    try:
        chosen = Tier(tier)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", "未知的访问级别。") from exc
    if chosen not in ROLE_TIERS[role]:
        raise DomainError("FORBIDDEN_SCOPE", "所选访问级别超过你在该账套的角色。")
    code = random_base62(43)
    params = request.params
    session.add(
        OAuthCode(
            code_hash=token_hash(code),
            client_id=request.client_id,
            user_id=request.user_id,
            book_id=book_id,
            tier=chosen.value,
            redirect_uri=params["redirect_uri"],
            redirect_uri_provided_explicitly=bool(params["redirect_uri_provided_explicitly"]),
            code_challenge=params["code_challenge"],
            resource=params.get("resource"),
            expires_at=_now() + CODE_TTL,
        )
    )
    request.completed_at = _now()
    audit.record(
        session,
        _ctx(ip),
        "oauth.consent",
        "oauth_client",
        request.client_id,
        after={"user_id": request.user_id, "book_id": book_id, "tier": chosen.value},
        scope="global",
        in_change_set=False,
    )
    return _redirect(params["redirect_uri"], code=code, state=params.get("state"), iss=issuer)  # RFC 9207


def deny(session: Session, request: OAuthRequest, issuer: str) -> str:
    request.completed_at = _now()
    params = request.params
    return _redirect(
        params["redirect_uri"],
        error="access_denied",
        error_description="用户拒绝授权",
        state=params.get("state"),
        iss=issuer,
    )


# ------------------------------------------------------------------ token endpoint


def load_code(session: Session, client_id: str, code: str) -> OAuthCode | None:
    row = session.get(OAuthCode, token_hash(code))
    if row is None or row.client_id != client_id or row.used_at is not None:
        return None
    return row


def _issue(
    session: Session,
    settings: Settings,
    *,
    client_id: str,
    user_id: str,
    book_id: str,
    tier: str,
    resource: str | None,
    family_id: str,
) -> IssuedTokens:
    user = session.get(User, user_id)
    role = identity.member_role(session, book_id, user_id)
    if user is None or not user.is_active or role is None:
        raise OAuthError("invalid_grant", "授权用户已停用或不再是账套成员。")
    chosen = tier_for_role(Tier(tier), role) or Tier.USER_READ  # the role may have been lowered since consent
    ctx = RequestContext(
        actor=Actor(type="user", user_id=user_id, role=role, scopes=ROLE_CAPS[role]),
        channel="api",
        book_id=book_id,
    )
    issued = tokens.create_token(
        session,
        ctx,
        name=f"OAuth · {client_name(session, client_id)}"[:100],
        tier=chosen,
        mcp_enabled=True,
        expires_in_days=settings.oauth_access_days,
    )
    refresh = random_base62(43)
    session.add(
        OAuthRefreshToken(
            token_hash=token_hash(refresh),
            family_id=family_id,
            client_id=client_id,
            user_id=user_id,
            book_id=book_id,
            tier=chosen.value,
            resource=resource,
            api_token_id=issued.token.id,
            expires_at=_now() + timedelta(days=settings.oauth_refresh_days),
        )
    )
    client = session.get(OAuthClient, client_id)
    if client is not None:
        client.last_used_at = _now()
    session.flush()
    return IssuedTokens(
        access_token=issued.plaintext,
        expires_in=settings.oauth_access_days * 86400,
        refresh_token=refresh,
        scope=" ".join(sorted(s.value for s in tier_scopes(chosen, role))),
    )


def exchange_code(session: Session, settings: Settings, client_id: str, code: str) -> IssuedTokens:
    row = session.execute(
        update(OAuthCode)
        .where(OAuthCode.code_hash == token_hash(code), OAuthCode.client_id == client_id, OAuthCode.used_at.is_(None))
        .values(used_at=_now())
        .returning(OAuthCode)
    ).scalar_one_or_none()
    if row is None or row.expires_at < _now():
        raise OAuthError("invalid_grant", "授权码无效、已使用或已过期。")
    return _issue(
        session,
        settings,
        client_id=client_id,
        user_id=row.user_id,
        book_id=row.book_id,
        tier=row.tier,
        resource=row.resource,
        family_id=new_id("ogr"),
    )


def load_refresh(session: Session, client_id: str, refresh: str) -> OAuthRefreshToken | None:
    row = session.get(OAuthRefreshToken, token_hash(refresh))
    if row is None or row.client_id != client_id or row.revoked_at is not None:
        return None
    if row.used_at is not None:
        revoke_family(session, row.family_id, "refresh_token_reuse")  # a rotated token came back: assume theft
        return None
    return row


def exchange_refresh(session: Session, settings: Settings, client_id: str, refresh: str) -> IssuedTokens:
    row = session.execute(
        update(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.token_hash == token_hash(refresh),
            OAuthRefreshToken.client_id == client_id,
            OAuthRefreshToken.used_at.is_(None),
            OAuthRefreshToken.revoked_at.is_(None),
        )
        .values(used_at=_now())
        .returning(OAuthRefreshToken)
    ).scalar_one_or_none()
    if row is None or row.expires_at < _now():
        raise OAuthError("invalid_grant", "刷新令牌无效、已使用或已过期。")
    _revoke_api_token(session, row.api_token_id)
    return _issue(
        session,
        settings,
        client_id=client_id,
        user_id=row.user_id,
        book_id=row.book_id,
        tier=row.tier,
        resource=row.resource,
        family_id=row.family_id,
    )


def _revoke_api_token(session: Session, token_id: str) -> None:
    session.execute(
        update(ApiToken).where(ApiToken.id == token_id, ApiToken.revoked_at.is_(None)).values(revoked_at=_now())
    )


def revoke_family(session: Session, family_id: str, reason: str) -> None:
    rows = session.execute(select(OAuthRefreshToken).where(OAuthRefreshToken.family_id == family_id)).scalars().all()
    for row in rows:
        if row.revoked_at is None:
            row.revoked_at = _now()
        _revoke_api_token(session, row.api_token_id)
    if rows:
        audit.record(
            session,
            _ctx(),
            "oauth.revoke",
            "oauth_client",
            rows[0].client_id,
            after={"family_id": family_id, "reason": reason, "user_id": rows[0].user_id},
            scope="global",
            in_change_set=False,
        )


def family_of_access_token(session: Session, client_id: str | None, access_token: str) -> OAuthRefreshToken | None:
    """The refresh-token row an OAuth-issued access token belongs to (optionally only for one client)."""
    token = session.execute(
        select(ApiToken).where(ApiToken.token_hash == token_hash(access_token))
    ).scalar_one_or_none()
    if token is None:
        return None
    stmt = select(OAuthRefreshToken).where(OAuthRefreshToken.api_token_id == token.id)
    if client_id is not None:
        stmt = stmt.where(OAuthRefreshToken.client_id == client_id)
    return session.execute(stmt).scalar_one_or_none()


def families_of_api_token(session: Session, api_token_id: str) -> list[str]:
    return list(
        session.execute(
            select(OAuthRefreshToken.family_id).where(OAuthRefreshToken.api_token_id == api_token_id).distinct()
        ).scalars()
    )


def mcp_resource(settings: Settings) -> str:
    return settings.public_url.rstrip("/") + "/mcp"


def purge(session: Session) -> dict[str, int]:
    """Expired pending requests and codes (maintenance task)."""
    cutoff = _now() - timedelta(days=1)
    return {
        "oauth_requests": rowcount(session.execute(delete(OAuthRequest).where(OAuthRequest.expires_at < cutoff))),
        "oauth_codes": rowcount(session.execute(delete(OAuthCode).where(OAuthCode.expires_at < cutoff))),
    }
