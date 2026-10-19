"""Request context passed to every service call."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Role, Scope

ActorType = Literal["user", "token", "system", "migration"]
Channel = Literal["ui", "api", "mcp", "agent", "import", "worker", "cli", "migration", "system"]


@dataclass(frozen=True)
class Actor:
    type: ActorType
    user_id: str | None = None
    token_id: str | None = None
    role: Role | None = None
    scopes: frozenset[Scope] = frozenset()
    is_superadmin: bool = False
    mcp_client: str | None = None

    @property
    def key(self) -> str:
        """Stable identity used to scope idempotency keys."""
        return self.token_id or self.user_id or self.type

    @classmethod
    def system(cls) -> Actor:
        return cls(type="system", scopes=frozenset(Scope), is_superadmin=True)


@dataclass
class RequestContext:
    actor: Actor
    channel: Channel
    book_id: str | None = None
    request_id: str = field(default_factory=lambda: new_id("req"))
    ip: str | None = None
    user_agent: str | None = None
    idempotency_key: str | None = None
    dry_run: bool = False
    change_set_id: str | None = None
    content_store: Any = None  # file storage, for interfaces that receive file contents inline (MCP)

    @property
    def scope(self) -> str:
        return self.book_id or "global"

    def has(self, scope: Scope) -> bool:
        return scope in self.actor.scopes

    def require(self, *scopes: Scope) -> None:
        missing = [s.value for s in scopes if s not in self.actor.scopes]
        if missing:
            raise DomainError(
                "FORBIDDEN_SCOPE",
                f"缺少权限：{', '.join(missing)}。",
                extra={"missing_scopes": missing},
            )

    def require_superadmin(self) -> None:
        if not self.actor.is_superadmin:
            raise DomainError("FORBIDDEN_SCOPE", "该操作仅限系统管理员。")

    def require_book(self) -> str:
        if self.book_id is None:
            raise DomainError("VALIDATION_FAILED", "该操作需要指定账套。")
        return self.book_id
