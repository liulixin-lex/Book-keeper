from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import UserSession

_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Verifying a real hash for unknown users keeps the login path broadly uniform.
_dummy_password_hash = _password_hasher.hash("not-a-real-user-password")


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate_hash = password_hash or _dummy_password_hash
    try:
        verified = _password_hasher.verify(candidate_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False
    return bool(verified and password_hash)


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str, settings: Settings, purpose: str) -> str:
    payload = f"{purpose}:{token}".encode()
    return hmac.new(settings.app_secret_key.encode(), payload, hashlib.sha256).hexdigest()


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


def create_user_session(
    db: Session,
    *,
    user_id: str,
    settings: Settings,
) -> tuple[UserSession, str, str]:
    session_token = generate_token()
    csrf_token = generate_token()
    now = utc_now()
    user_session = UserSession(
        id=str(uuid4()),
        user_id=user_id,
        token_hash=token_digest(session_token, settings, "session"),
        csrf_hash=token_digest(csrf_token, settings, "csrf"),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(user_session)
    return user_session, session_token, csrf_token


def revoke_user_sessions(
    db: Session,
    user_id: str,
    *,
    except_session_id: str | None = None,
) -> None:
    statement = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    if except_session_id is not None:
        statement = statement.where(UserSession.id != except_session_id)
    db.execute(statement)


def set_auth_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    max_age = settings.session_ttl_hours * 60 * 60
    secure = settings.session_cookie_secure or settings.is_production
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    secure = settings.session_cookie_secure or settings.is_production
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )
