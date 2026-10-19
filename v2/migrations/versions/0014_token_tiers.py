"""Token permissions become four tiers: user_read, user_write, admin_read, admin_write (docs/19 §2).

A token keeps only its tier; its scopes come from the tier at request time. Existing tokens move as
reader → user_read, bookkeeper → user_write, admin → admin_write; a custom token gets the highest tier
its scopes cover (files:read counts as covered by ledger:read: the old read preset never had it), and a
custom token without ledger:read is revoked. Every custom token is listed in the report printed here.
OAuth codes and refresh tokens carry the tier too.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRESET_TIER = {"reader": "user_read", "bookkeeper": "user_write", "admin": "admin_write"}
TIER_PRESET = {"user_read": "reader", "user_write": "bookkeeper", "admin_write": "admin"}
TIERS = "tier IN ('user_read','user_write','admin_read','admin_write')"
# This revision's own copy of the tier mapping, so later changes to the app cannot change what it did.
READ = {"ledger:read", "files:read"}
TIER_SCOPES = {
    "user_read": READ,
    "user_write": READ | {"ledger:write", "import:write", "reference:write"},
    "admin_read": READ | {"admin:read"},
    "admin_write": READ
    | {"ledger:write", "import:write", "rules:write", "reference:write", "config:write", "admin", "admin:read"},
}
OLD_PRESET_SCOPES = {
    "reader": ["ledger:read"],
    "bookkeeper": ["import:write", "ledger:read", "ledger:write", "reference:write"],
    "admin": sorted(TIER_SCOPES["admin_write"]),
}


def _custom_tier(scopes: set[str]) -> str | None:
    held = scopes | ({"files:read"} if "ledger:read" in scopes else set())
    inside = [tier for tier, need in TIER_SCOPES.items() if need <= held]
    return max(inside, key=lambda t: len(TIER_SCOPES[t])) if inside else None


def upgrade() -> None:
    bind = op.get_bind()
    op.add_column("api_tokens", sa.Column("tier", sa.Text(), nullable=True))
    for preset, tier in PRESET_TIER.items():
        bind.execute(
            sa.text("UPDATE api_tokens SET tier = :tier WHERE preset = :preset"), {"tier": tier, "preset": preset}
        )
    report = []
    customs = bind.execute(
        sa.text("SELECT id, name, scopes, revoked_at IS NOT NULL FROM api_tokens WHERE preset = 'custom' ORDER BY id")
    ).all()
    for token_id, name, scopes, revoked in customs:
        tier = _custom_tier(set(scopes))
        if tier is None:
            bind.execute(
                sa.text(
                    "UPDATE api_tokens SET tier = 'user_read', revoked_at = coalesce(revoked_at, now()) WHERE id = :id"
                ),
                {"id": token_id},
            )
            report.append(f"  {token_id} {name}: {','.join(sorted(scopes))} → 已吊销（没有 ledger:read）")
        else:
            bind.execute(sa.text("UPDATE api_tokens SET tier = :tier WHERE id = :id"), {"tier": tier, "id": token_id})
            dropped = sorted(set(scopes) - TIER_SCOPES[tier])
            note = f"，不再有 {','.join(dropped)}" if dropped else ""
            report.append(
                f"  {token_id} {name}{'（已吊销）' if revoked else ''}: {','.join(sorted(scopes))} → {tier}{note}"
            )
    counts = bind.execute(sa.text("SELECT tier, count(*) FROM api_tokens GROUP BY tier ORDER BY tier")).all()
    print("令牌档位迁移：" + ("、".join(f"{tier} {n} 个" for tier, n in counts) or "没有令牌"))
    if report:
        print("自定义令牌：\n" + "\n".join(report))
    op.alter_column("api_tokens", "tier", nullable=False)
    op.drop_constraint(op.f("ck_api_tokens_preset"), "api_tokens", type_="check")
    op.drop_column("api_tokens", "preset")
    op.drop_column("api_tokens", "scopes")
    op.create_check_constraint(op.f("ck_api_tokens_tier"), "api_tokens", TIERS)

    for table in ("oauth_codes", "oauth_refresh_tokens"):
        op.drop_constraint(op.f(f"ck_{table}_preset"), table, type_="check")
        op.alter_column(table, "preset", new_column_name="tier")
        for preset, tier in PRESET_TIER.items():
            update = sa.text(f"UPDATE {table} SET tier = :tier WHERE tier = :preset")  # noqa: S608 (fixed table names)
            bind.execute(update, {"tier": tier, "preset": preset})
        op.create_check_constraint(op.f(f"ck_{table}_tier"), table, TIERS)


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("oauth_codes", "oauth_refresh_tokens"):
        op.drop_constraint(op.f(f"ck_{table}_tier"), table, type_="check")
        bind.execute(sa.text(f"UPDATE {table} SET tier = 'reader' WHERE tier = 'admin_read'"))  # noqa: S608
        for tier, preset in TIER_PRESET.items():
            update = sa.text(f"UPDATE {table} SET tier = :preset WHERE tier = :tier")  # noqa: S608
            bind.execute(update, {"tier": tier, "preset": preset})
        op.alter_column(table, "tier", new_column_name="preset")
        op.create_check_constraint(op.f(f"ck_{table}_preset"), table, "preset IN ('reader','bookkeeper','admin')")

    op.drop_constraint(op.f("ck_api_tokens_tier"), "api_tokens", type_="check")
    op.add_column("api_tokens", sa.Column("preset", sa.Text(), nullable=True))
    op.add_column("api_tokens", sa.Column("scopes", sa.ARRAY(sa.Text()), nullable=True))
    for tier, preset in TIER_PRESET.items():
        bind.execute(
            sa.text("UPDATE api_tokens SET preset = :preset, scopes = :scopes WHERE tier = :tier"),
            {"tier": tier, "preset": preset, "scopes": OLD_PRESET_SCOPES[preset]},
        )
    bind.execute(
        sa.text("UPDATE api_tokens SET preset = 'custom', scopes = :scopes WHERE tier = 'admin_read'"),
        {"scopes": sorted(TIER_SCOPES["admin_read"])},
    )
    op.alter_column("api_tokens", "preset", nullable=False)
    op.alter_column("api_tokens", "scopes", nullable=False)
    op.drop_column("api_tokens", "tier")
    op.create_check_constraint(
        op.f("ck_api_tokens_preset"), "api_tokens", "preset IN ('reader','bookkeeper','admin','custom')"
    )
