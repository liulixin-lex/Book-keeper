"""Opaque secret generation: session tokens, API tokens, CSRF secrets."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string

_BASE62 = string.digits + string.ascii_letters
API_TOKEN_PREFIX = "bk_pat_"  # noqa: S105  (public prefix, not a secret)
API_TOKEN_BODY_LENGTH = 40
API_TOKEN_DISPLAY_LENGTH = 12


def random_base62(length: int) -> str:
    return "".join(secrets.choice(_BASE62) for _ in range(length))


def new_api_token() -> str:
    return API_TOKEN_PREFIX + random_base62(API_TOKEN_BODY_LENGTH)


def looks_like_api_token(value: str) -> bool:
    body = value.removeprefix(API_TOKEN_PREFIX)
    return value.startswith(API_TOKEN_PREFIX) and len(body) == API_TOKEN_BODY_LENGTH and all(c in _BASE62 for c in body)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_display_prefix(value: str) -> str:
    return value[:API_TOKEN_DISPLAY_LENGTH]


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
