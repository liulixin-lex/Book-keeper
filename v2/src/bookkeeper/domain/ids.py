"""Prefixed ULID identifiers, e.g. ``txn_01JB8Q6N0V2W3X4Y5Z6A7B8C9D``."""

from __future__ import annotations

import re
import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_PREFIX_RE = re.compile(r"^[a-z]{2,4}$")

PREFIXES: frozenset[str] = frozenset(
    {
        "usr",
        "ses",
        "bk",
        "tok",
        "oac",
        "ogr",
        "cpr",
        "fxr",
        "acc",
        "dmt",
        "dmv",
        "cpt",
        "cal",
        "cpa",
        "tty",
        "tpl",
        "fee",
        "txn",
        "tln",
        "jen",
        "jln",
        "fp",
        "lex",
        "src",
        "imb",
        "srec",
        "rul",
        "rrn",
        "msg",
        "mex",
        "prl",
        "bas",
        "rcn",
        "lmt",
        "mgp",
        "rpt",
        "chk",
        "aud",
        "chs",
        "fil",
        "att",
        "tag",
        "prv",
        "job",
        "jsc",
        "obx",
        "whe",
        "whd",
        "mcp",
        "req",
        "chr",
    }
)


def ulid(timestamp_ms: int | None = None) -> str:
    """Return a 26-character Crockford base32 ULID (48-bit ms time + 80-bit randomness)."""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ms < 2**48:
        raise ValueError("timestamp out of range")
    value = (ms << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{ulid()}"


def is_valid_id(value: str, prefix: str | None = None) -> bool:
    head, sep, tail = value.partition("_")
    if not sep or not _PREFIX_RE.match(head) or head not in PREFIXES:
        return False
    if prefix is not None and head != prefix:
        return False
    return bool(_ULID_RE.match(tail))


def ulid_timestamp_ms(value: str) -> int:
    """Extract the millisecond timestamp from a ULID or a prefixed id."""
    raw = value.rpartition("_")[2]
    if not _ULID_RE.match(raw):
        raise ValueError("not a ULID")
    number = 0
    for char in raw:
        number = number * 32 + _CROCKFORD.index(char)
    return number >> 80
