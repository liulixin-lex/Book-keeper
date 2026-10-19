"""Opaque cursors."""

from __future__ import annotations

import base64
import json
from typing import Any

from bookkeeper.domain.errors import DomainError


def encode_cursor(value: dict[str, Any]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise DomainError("VALIDATION_FAILED", "cursor 无效。") from exc
    if not isinstance(value, dict):
        raise DomainError("VALIDATION_FAILED", "cursor 无效。")
    return value
