from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.enums import UserRole
from app.models import User, UserSession
from app.security import as_utc, secure_compare, token_digest, utc_now


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    session: UserSession


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="请先登录",
        headers={"WWW-Authenticate": "Session"},
    )


def get_auth_context(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    raw_token = request.cookies.get(settings.session_cookie_name)
    if not raw_token:
        raise _unauthorized()

    digest = token_digest(raw_token, settings, "session")
    result = db.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(UserSession.token_hash == digest)
    ).one_or_none()
    if result is None:
        raise _unauthorized()

    user_session, user = result
    if (
        user_session.revoked_at is not None
        or as_utc(user_session.expires_at) <= utc_now()
        or not user.is_active
    ):
        raise _unauthorized()
    return AuthContext(user=user, session=user_session)


def get_current_user(context: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return context.user


def require_csrf(
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token or not secure_compare(cookie_token, header_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")

    expected = token_digest(header_token, settings, "csrf")
    if not secure_compare(expected, context.session.csrf_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")
    return context


def require_roles(*roles: UserRole) -> Callable[..., User]:
    allowed = frozenset(roles)

    def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if UserRole(user.role) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return dependency


require_admin = require_roles(UserRole.ADMIN)
require_bookkeeper = require_roles(UserRole.ADMIN, UserRole.BOOKKEEPER)
require_viewer = require_roles(UserRole.ADMIN, UserRole.BOOKKEEPER, UserRole.VIEWER)

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]
