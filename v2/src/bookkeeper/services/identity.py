"""Users, password login, sessions, and request authentication."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from bookkeeper.config import Settings
from bookkeeper.db.models import ApiToken, BookMember, User, UserSession
from bookkeeper.db.session import rowcount
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import ROLE_CAPS, Role, effective_scopes, parse_scopes
from bookkeeper.security import passwords
from bookkeeper.security.secrets import (
    looks_like_api_token,
    new_session_token,
    random_base62,
    token_hash,
)
from bookkeeper.services import audit
from bookkeeper.services.context import Actor, RequestContext

TOKEN_TOUCH_INTERVAL = timedelta(seconds=60)


def user_view(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_superadmin": user.is_superadmin,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "version": user.version,
    }


def normalise_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or len(value) > 254:
        raise DomainError("VALIDATION_FAILED", "邮箱格式不正确。")
    return value


def create_user(
    session: Session,
    ctx: RequestContext,
    *,
    email: str,
    display_name: str,
    password: str,
    is_superadmin: bool = False,
) -> User:
    email = normalise_email(email)
    if session.execute(select(User.id).where(User.email == email)).first():
        raise DomainError("CONFLICT", f"邮箱 {email} 已被使用。")
    try:
        password_hash = passwords.hash_password(password)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", f"密码至少 {passwords.MIN_PASSWORD_LENGTH} 位。") from exc
    user = User(
        id=new_id("usr"),
        email=email,
        display_name=display_name.strip(),
        password_hash=password_hash,
        is_superadmin=is_superadmin,
    )
    session.add(user)
    session.flush()
    audit.record(session, ctx, "user.create", "user", user.id, after=user_view(user), scope="global")
    return user


@dataclass(frozen=True)
class LoginResult:
    user: User
    session_token: str
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class LoginOutcome:
    """Login never raises: failures must be committed (counter, lock, audit) before reporting."""

    result: LoginResult | None = None
    error: DomainError | None = None


def check_credentials(
    session: Session, ctx: RequestContext, settings: Settings, email: str, password: str
) -> tuple[User | None, DomainError | None]:
    """Password check with lockout and audit; shared by session login and the OAuth sign-in page.

    Never raises for bad credentials: the caller must commit the failure counters before reporting.
    """
    now = datetime.now(UTC)
    try:
        email = normalise_email(email)
    except DomainError:
        email = ""
    user = session.execute(select(User).where(User.email == email).with_for_update()).scalar_one_or_none()
    bad_credentials = DomainError("UNAUTHENTICATED", "邮箱或密码不正确。")
    if user is None or not user.is_active:
        passwords.verify_password(passwords.DUMMY_HASH, password)
        audit.record(
            session,
            ctx,
            "auth.login_failed",
            "user",
            None,
            after={"email": email, "reason": "unknown_or_inactive"},
            scope="global",
            in_change_set=False,
        )
        return None, bad_credentials
    if user.locked_until and user.locked_until > now:
        return None, DomainError(
            "ACCOUNT_LOCKED",
            f"登录失败次数过多，账号锁定至 {user.locked_until.isoformat(timespec='minutes')}。",
        )
    if not passwords.verify_password(user.password_hash, password):
        user.failed_logins += 1
        locked = user.failed_logins >= settings.login_max_failures
        if locked:
            user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
        audit.record(
            session,
            ctx,
            "auth.login_failed",
            "user",
            user.id,
            after={"reason": "bad_password", "locked": locked},
            scope="global",
            in_change_set=False,
        )
        return None, bad_credentials
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    return user, None


def login(session: Session, ctx: RequestContext, settings: Settings, email: str, password: str) -> LoginOutcome:
    user, error = check_credentials(session, ctx, settings, email, password)
    if user is None:
        return LoginOutcome(error=error)
    now = datetime.now(UTC)
    raw = new_session_token()
    csrf = random_base62(32)
    expires = now + timedelta(days=settings.session_absolute_days)
    session.add(
        UserSession(
            id=new_id("ses"),
            user_id=user.id,
            token_hash=token_hash(raw),
            csrf_secret=csrf,
            ip=_ip_or_none(ctx.ip),
            user_agent=ctx.user_agent,
            expires_at=expires,
        )
    )
    session.flush()
    audit.record(session, ctx, "auth.login_succeeded", "user", user.id, scope="global", in_change_set=False)
    return LoginOutcome(result=LoginResult(user, raw, csrf, expires))


def logout(session: Session, raw_session_token: str) -> None:
    session.execute(
        update(UserSession)
        .where(
            UserSession.token_hash == token_hash(raw_session_token),
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


def change_password(
    session: Session,
    ctx: RequestContext,
    user_id: str,
    current: str,
    new: str,
    keep_session: str | None,
) -> None:
    user = session.get(User, user_id, with_for_update=True)
    if user is None:
        raise not_found("用户", user_id)
    if not passwords.verify_password(user.password_hash, current):
        raise DomainError("UNAUTHENTICATED", "当前密码不正确。")
    try:
        user.password_hash = passwords.hash_password(new)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", f"新密码至少 {passwords.MIN_PASSWORD_LENGTH} 位。") from exc
    user.version += 1
    revoke = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if keep_session:
        revoke = revoke.where(UserSession.token_hash != token_hash(keep_session))
    session.execute(revoke.values(revoked_at=datetime.now(UTC)))
    audit.record(session, ctx, "user.password_change", "user", user_id, scope="global")


def reset_password(session: Session, ctx: RequestContext, email: str, new: str) -> User:
    """Operator reset (CLI / superadmin): new hash, lockout cleared, every session revoked."""
    if not ctx.actor.is_superadmin:
        raise DomainError("FORBIDDEN", "只有超级管理员可以重置密码。")
    user = session.execute(
        select(User).where(User.email == normalise_email(email)).with_for_update()
    ).scalar_one_or_none()
    if user is None:
        raise not_found("用户", email)
    try:
        user.password_hash = passwords.hash_password(new)
    except ValueError as exc:
        raise DomainError("VALIDATION_FAILED", f"新密码至少 {passwords.MIN_PASSWORD_LENGTH} 位。") from exc
    user.failed_logins = 0
    user.locked_until = None
    user.version += 1
    session.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    audit.record(session, ctx, "user.password_reset", "user", user.id, scope="global")
    return user


def _ip_or_none(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        return ipaddress.ip_address(ip).compressed
    except ValueError:
        return None


@dataclass(frozen=True)
class Authenticated:
    actor: Actor
    user: User
    token: ApiToken | None = None
    session: UserSession | None = None


def member_role(session: Session, book_id: str, user_id: str) -> Role | None:
    role = session.execute(
        select(BookMember.role).where(BookMember.book_id == book_id, BookMember.user_id == user_id)
    ).scalar_one_or_none()
    return Role(role) if role else None


def authenticate_session(session: Session, settings: Settings, raw: str, book_id: str | None) -> Authenticated:
    now = datetime.now(UTC)
    row = session.execute(select(UserSession).where(UserSession.token_hash == token_hash(raw))).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        raise DomainError("UNAUTHENTICATED", "会话无效或已过期，请重新登录。")
    if row.last_seen_at + timedelta(hours=settings.session_idle_hours) <= now:
        raise DomainError("UNAUTHENTICATED", "会话已因长时间未操作而失效，请重新登录。")
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise DomainError("UNAUTHENTICATED", "用户已停用。")
    if now - row.last_seen_at > TOKEN_TOUCH_INTERVAL:
        row.last_seen_at = now
    role = member_role(session, book_id, user.id) if book_id else None
    scopes = ROLE_CAPS[role] if role else frozenset()
    actor = Actor(
        type="user",
        user_id=user.id,
        role=role,
        scopes=scopes,
        is_superadmin=user.is_superadmin,
    )
    return Authenticated(actor=actor, user=user, session=row)


def authenticate_token(
    session: Session, raw: str, book_id: str | None, ip: str | None, mcp_client: str | None = None
) -> Authenticated:
    now = datetime.now(UTC)
    if not looks_like_api_token(raw):
        raise DomainError("UNAUTHENTICATED", "令牌格式不正确。")
    token = session.execute(select(ApiToken).where(ApiToken.token_hash == token_hash(raw))).scalar_one_or_none()
    if token is None:
        raise DomainError("UNAUTHENTICATED", "令牌无效。")
    if token.revoked_at is not None:
        raise DomainError("TOKEN_REVOKED", "令牌已吊销。")
    if token.expires_at is not None and token.expires_at <= now:
        raise DomainError("TOKEN_EXPIRED", "令牌已过期。")
    if book_id is not None and token.book_id != book_id:
        raise DomainError("FORBIDDEN_SCOPE", "该令牌不属于此账套。")
    if token.ip_allowlist and not _ip_allowed(ip, token.ip_allowlist):
        raise DomainError("FORBIDDEN_SCOPE", "当前 IP 不在令牌的允许列表中。")
    user = session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise DomainError("UNAUTHENTICATED", "令牌所属用户已停用。")
    role = member_role(session, token.book_id, user.id)
    if role is None:
        raise DomainError("FORBIDDEN_SCOPE", "令牌所属用户已不是该账套成员。")
    if token.last_used_at is None or now - token.last_used_at > TOKEN_TOUCH_INTERVAL:
        token.last_used_at = now
        token.last_used_ip = _ip_or_none(ip)
    actor = Actor(
        type="token",
        user_id=user.id,
        token_id=token.id,
        role=role,
        scopes=effective_scopes(parse_scopes(token.scopes), role),
        is_superadmin=False,
        mcp_client=mcp_client,
    )
    return Authenticated(actor=actor, user=user, token=token)


def _ip_allowed(ip: str | None, allowlist: list[str]) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def purge_sessions(session: Session) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=30)
    return rowcount(session.execute(delete(UserSession).where(UserSession.expires_at < cutoff)))
