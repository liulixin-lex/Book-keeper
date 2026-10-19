"""Scopes, roles and the four token tiers (docs/08-rest-api.md §3, docs/19 §2).

Tokens (API, MCP, OAuth) and the in-app AI assistant get one of four tiers; ``TIER_SCOPES`` is the only place a
tier turns into scopes. Web sessions get their role's scopes.
"""

from __future__ import annotations

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


class Tier(StrEnum):
    USER_READ = "user_read"
    USER_WRITE = "user_write"
    ADMIN_READ = "admin_read"
    ADMIN_WRITE = "admin_write"


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

_USER_READ = frozenset({Scope.LEDGER_READ, Scope.FILES_READ})
TIER_SCOPES: dict[Tier, frozenset[Scope]] = {
    Tier.USER_READ: _USER_READ,
    Tier.USER_WRITE: _USER_READ | {Scope.LEDGER_WRITE, Scope.IMPORT_WRITE, Scope.REFERENCE_WRITE},
    Tier.ADMIN_READ: _USER_READ | {Scope.ADMIN_READ},
    Tier.ADMIN_WRITE: frozenset(Scope),
}

TIER_TEXT: dict[Tier, tuple[str, str]] = {
    Tier.USER_READ: ("用户只读", "查看账本、统计、导入批次与记录、上传的文件"),
    Tier.USER_WRITE: ("用户读写", "另可记账、修改、删除、恢复、导入、匹配决策、往来方与渠道；所有写入可撤销"),
    Tier.ADMIN_READ: ("管理员只读", "另可查看成员、令牌、审计日志、规则与手续费规则、AI 配置（不含密钥）；不能写"),
    Tier.ADMIN_WRITE: ("管理员读写", "全部权限"),
}

# Which tiers a member may hand to a token or the AI assistant: ordinary members only the user tiers.
ROLE_TIERS: dict[Role, tuple[Tier, ...]] = {
    Role.VIEWER: (Tier.USER_READ,),
    Role.ACCOUNTANT: (Tier.USER_READ, Tier.USER_WRITE),
    Role.ADMIN: tuple(Tier),
    Role.OWNER: tuple(Tier),
}


def tier_for_role(tier: Tier, role: Role) -> Tier | None:
    """The tier a token actually gets: its own, or after a role downgrade the highest allowed tier inside it."""
    if tier in ROLE_TIERS[role]:
        return tier
    inside = [t for t in ROLE_TIERS[role] if TIER_SCOPES[t] <= TIER_SCOPES[tier]]
    return max(inside, key=lambda t: len(TIER_SCOPES[t])) if inside else None


def tier_scopes(tier: Tier, role: Role) -> frozenset[Scope]:
    effective = tier_for_role(tier, role)
    return TIER_SCOPES[effective] & ROLE_CAPS[role] if effective else frozenset()
