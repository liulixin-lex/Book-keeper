"""Scopes, roles and token presets (docs/08-rest-api.md §3)."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Scope(StrEnum):
    LEDGER_READ = "ledger:read"
    FILES_READ = "files:read"
    LEDGER_WRITE = "ledger:write"
    IMPORT_WRITE = "import:write"
    RULES_WRITE = "rules:write"
    REFERENCE_WRITE = "reference:write"
    CONFIG_WRITE = "config:write"
    ADMIN = "admin"
    ADMIN_READ = "admin:read"  # read management info: members, tokens, audit, rules, AI config (never secrets)


class Role(StrEnum):
    VIEWER = "viewer"
    ACCOUNTANT = "accountant"
    ADMIN = "admin"
    OWNER = "owner"


class Preset(StrEnum):
    READER = "reader"
    BOOKKEEPER = "bookkeeper"
    ADMIN = "admin"
    CUSTOM = "custom"


_VIEWER = frozenset({Scope.LEDGER_READ, Scope.FILES_READ})
_ACCOUNTANT = _VIEWER | {
    Scope.LEDGER_WRITE,
    Scope.IMPORT_WRITE,
    Scope.RULES_WRITE,
    Scope.REFERENCE_WRITE,
    Scope.ADMIN_READ,
}
_ADMIN = _ACCOUNTANT | {Scope.CONFIG_WRITE, Scope.ADMIN}

ROLE_CAPS: dict[Role, frozenset[Scope]] = {
    Role.VIEWER: _VIEWER,
    Role.ACCOUNTANT: frozenset(_ACCOUNTANT),
    Role.ADMIN: frozenset(_ADMIN),
    Role.OWNER: frozenset(_ADMIN),
}

PRESET_SCOPES: dict[Preset, frozenset[Scope]] = {
    Preset.READER: frozenset({Scope.LEDGER_READ}),
    Preset.BOOKKEEPER: frozenset({Scope.LEDGER_READ, Scope.LEDGER_WRITE, Scope.IMPORT_WRITE, Scope.REFERENCE_WRITE}),
    Preset.ADMIN: frozenset(_ADMIN),
}


def parse_scopes(values: Iterable[str]) -> frozenset[Scope]:
    result = set()
    for value in values:
        try:
            result.add(Scope(value))
        except ValueError as exc:
            raise ValueError(f"unknown scope: {value}") from exc
    return frozenset(result)


def scopes_for_preset(preset: Preset, role: Role) -> frozenset[Scope]:
    """Preset scopes, capped by the user's role. ``admin`` preset = everything the role allows."""
    if preset is Preset.CUSTOM:
        raise ValueError("custom preset requires explicit scopes")
    return PRESET_SCOPES[preset] & ROLE_CAPS[role]


def effective_scopes(token_scopes: Iterable[Scope], role: Role) -> frozenset[Scope]:
    return frozenset(token_scopes) & ROLE_CAPS[role]


def role_allows(role: Role, scopes: Iterable[Scope]) -> bool:
    return frozenset(scopes) <= ROLE_CAPS[role]
