import pytest

from bookkeeper.security.passwords import hash_password, needs_rehash, verify_password
from bookkeeper.security.secrets import (
    looks_like_api_token,
    new_api_token,
    token_display_prefix,
    token_hash,
)


def test_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong password!!")
    assert not needs_rehash(hashed)


def test_short_password_rejected() -> None:
    with pytest.raises(ValueError, match="at least"):
        hash_password("short")


def test_garbage_hash_does_not_raise() -> None:
    assert not verify_password("not-a-hash", "whatever password")


def test_api_token_format() -> None:
    token = new_api_token()
    assert looks_like_api_token(token)
    assert token.startswith("bk_pat_")
    assert len(token) == 47
    assert token_display_prefix(token) == token[:12]
    assert len(token_hash(token)) == 64
    assert not looks_like_api_token(token[:-1])
    assert new_api_token() != token
