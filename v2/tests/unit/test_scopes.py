import pytest

from bookkeeper.domain.scopes import (
    ROLE_CAPS,
    Preset,
    Role,
    Scope,
    effective_scopes,
    parse_scopes,
    scopes_for_preset,
)


def test_role_caps_are_nested() -> None:
    assert ROLE_CAPS[Role.VIEWER] < ROLE_CAPS[Role.ACCOUNTANT] < ROLE_CAPS[Role.ADMIN]
    assert ROLE_CAPS[Role.ADMIN] == ROLE_CAPS[Role.OWNER]
    assert Scope.ADMIN not in ROLE_CAPS[Role.ACCOUNTANT]


def test_reader_is_read_only() -> None:
    assert scopes_for_preset(Preset.READER, Role.OWNER) == {Scope.LEDGER_READ}


def test_preset_capped_by_role() -> None:
    granted = scopes_for_preset(Preset.BOOKKEEPER, Role.VIEWER)
    assert granted == {Scope.LEDGER_READ}


def test_effective_scopes_intersect_role() -> None:
    assert effective_scopes({Scope.ADMIN, Scope.LEDGER_READ}, Role.ACCOUNTANT) == {Scope.LEDGER_READ}


def test_parse_scopes_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown scope"):
        parse_scopes(["ledger:read", "root"])


def test_custom_preset_requires_scopes() -> None:
    with pytest.raises(ValueError, match="custom"):
        scopes_for_preset(Preset.CUSTOM, Role.ADMIN)
