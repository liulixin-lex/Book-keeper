"""Canonical JSON serialisation and hash chaining."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetime cannot be canonicalised")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value != 0 else "0"
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"cannot canonicalise {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, UTF-8, UTC microsecond timestamps."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def genesis_hash(namespace: str, scope: str) -> bytes:
    return hashlib.sha256(f"bookkeeper-{namespace}-genesis:{scope}".encode()).digest()


def chain_hash(prev_hash: bytes, payload: Any) -> bytes:
    """hash = SHA-256(prev_hash || canonical_bytes(payload))."""
    return hashlib.sha256(prev_hash + canonical_bytes(payload)).digest()
