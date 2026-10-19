from bookkeeper.domain.scopes import (
    ROLE_CAPS,
    ROLE_TIERS,
    TIER_SCOPES,
    Role,
    Scope,
    Tier,
    tier_for_role,
    tier_scopes,
)


def test_role_caps_are_nested() -> None:
    assert ROLE_CAPS[Role.VIEWER] < ROLE_CAPS[Role.ACCOUNTANT] < ROLE_CAPS[Role.ADMIN]
    assert ROLE_CAPS[Role.ADMIN] == ROLE_CAPS[Role.OWNER]
    assert Scope.ADMIN not in ROLE_CAPS[Role.ACCOUNTANT]


def test_the_four_tiers() -> None:
    user_read, user_write, admin_read, admin_write = (TIER_SCOPES[t] for t in Tier)
    assert user_read == {Scope.LEDGER_READ, Scope.FILES_READ}
    assert user_read < user_write and user_read < admin_read < admin_write and user_write < admin_write
    assert not {s for s in admin_read if s.value.endswith("write") or s is Scope.ADMIN}  # admin_read writes nothing
    assert admin_write == set(Scope)
    assert {Scope.RULES_WRITE, Scope.CONFIG_WRITE, Scope.ADMIN, Scope.ADMIN_READ}.isdisjoint(user_write)


def test_ordinary_members_hand_out_only_user_tiers() -> None:
    assert ROLE_TIERS[Role.ACCOUNTANT] == (Tier.USER_READ, Tier.USER_WRITE)
    assert ROLE_TIERS[Role.VIEWER] == (Tier.USER_READ,)
    assert set(ROLE_TIERS[Role.ADMIN]) == set(ROLE_TIERS[Role.OWNER]) == set(Tier)


def test_a_lowered_role_lowers_the_tier() -> None:
    assert tier_for_role(Tier.ADMIN_WRITE, Role.ACCOUNTANT) is Tier.USER_WRITE
    assert tier_for_role(Tier.ADMIN_READ, Role.ACCOUNTANT) is Tier.USER_READ
    assert tier_for_role(Tier.USER_WRITE, Role.VIEWER) is Tier.USER_READ
    assert tier_for_role(Tier.ADMIN_WRITE, Role.OWNER) is Tier.ADMIN_WRITE
    assert tier_scopes(Tier.ADMIN_WRITE, Role.VIEWER) == ROLE_CAPS[Role.VIEWER]
