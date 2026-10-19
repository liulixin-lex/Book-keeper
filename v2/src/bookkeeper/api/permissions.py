"""What each book route needs, in one table (docs/08 §3, docs/19 §2).

Checked as soon as the caller is known, against the request path, before the body is validated: a missing
permission is always 403, never a 422 that reveals the body shape first. A book path not in the table is
refused; a test keeps the table and the served routes in step. Services keep their own checks as a second line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.scopes import Scope
from bookkeeper.services.context import RequestContext

BOOK = "/api/v1/books/{book_id}"


@dataclass(frozen=True)
class Need:
    scopes: tuple[Scope, ...] = ()
    any_of: tuple[Scope, ...] = ()
    web_only: str | None = None  # refusal text for tokens and MCP; set = only a signed-in web session
    as_token: tuple[Scope, ...] = ()  # also needed when the caller is a token rather than a signed-in member


def need(
    *scopes: Scope, any_of: tuple[Scope, ...] = (), web_only: str | None = None, as_token: tuple[Scope, ...] = ()
) -> Need:
    return Need(scopes, any_of, web_only, as_token)


READ = need(Scope.LEDGER_READ)
FILES = need(Scope.FILES_READ)
ADMIN_READ = need(Scope.ADMIN_READ)
LEDGER = need(Scope.LEDGER_WRITE)
IMPORT = need(Scope.IMPORT_WRITE)
REFERENCE = need(Scope.REFERENCE_WRITE)
RULES = need(Scope.RULES_WRITE)
CONFIG = need(Scope.CONFIG_WRITE)
ADMIN = need(Scope.ADMIN)
AGENT = need(Scope.LEDGER_READ, web_only="AI 助手在网页端使用；令牌与 MCP 客户端请直接调用工具。")
TOKENS = need(Scope.LEDGER_READ, as_token=(Scope.ADMIN,))  # members manage their own; a token needs admin_write
AI_CONFIG = need(Scope.CONFIG_WRITE, web_only="AI 提供商与密钥只能在网页端（设置 → AI 模型）修改，令牌与 MCP 不能改。")

# (method, path under /api/v1/books/{book_id}) → what it needs.
ROUTES: dict[tuple[str, str], Need] = {
    ("GET", ""): READ,
    ("PATCH", ""): ADMIN,
    # ledger
    ("GET", "/transactions"): READ,
    ("GET", "/transactions/{ref}"): READ,
    ("GET", "/transactions/{ref}/explain"): READ,
    ("POST", "/transactions"): LEDGER,
    ("PATCH", "/transactions/{ref}"): LEDGER,
    ("DELETE", "/transactions/{ref}"): LEDGER,
    ("POST", "/transactions/{ref}:restore"): LEDGER,
    ("POST", "/transactions:batch"): LEDGER,
    ("POST", "/transactions:repost"): LEDGER,
    ("GET", "/transaction-types"): READ,
    ("GET", "/journal-entries"): READ,
    ("GET", "/journal-entries/{ref}"): READ,
    ("GET", "/balances"): READ,
    ("GET", "/tags"): READ,
    ("POST", "/attachments"): LEDGER,
    ("GET", "/change-sets"): READ,
    ("GET", "/change-sets/{change_set_id}"): READ,
    ("POST", "/change-sets/{change_set_id}:undo"): LEDGER,  # fee-rule changes also need config:write (service)
    # reports, checks, exports, work
    ("GET", "/reports"): READ,
    ("GET", "/reports/query"): READ,
    ("GET", "/reports/summary"): READ,
    ("GET", "/reports/operations"): READ,
    ("GET", "/reports/sales"): READ,
    ("GET", "/reports/fees"): READ,
    ("GET", "/reports/credit-purchases"): READ,
    ("GET", "/reports/income-statement"): READ,
    ("GET", "/reports/trial-balance"): READ,
    ("GET", "/exports/{fmt}"): READ,
    ("POST", "/checks:run"): READ,  # recomputes checks, changes no data
    ("GET", "/check-runs"): READ,
    ("GET", "/check-runs/{run_id}"): READ,
    ("GET", "/work-items"): READ,
    ("GET", "/work-items/summary"): READ,
    ("GET", "/jobs/{job_id}"): READ,
    # files
    ("POST", "/files"): need(any_of=(Scope.LEDGER_WRITE, Scope.IMPORT_WRITE)),
    ("GET", "/files/{file_id}"): FILES,
    ("GET", "/files/{file_id}/content"): FILES,
    # imports
    ("GET", "/import-sources"): READ,
    ("POST", "/import-sources"): IMPORT,
    ("PATCH", "/import-sources/{ref}"): IMPORT,
    ("POST", "/import-sources:preview"): IMPORT,
    ("GET", "/import-batches"): READ,
    ("GET", "/import-batches/{batch_id}"): READ,
    ("POST", "/import-batches"): IMPORT,
    ("POST", "/import-batches:upload"): IMPORT,
    ("POST", "/import-batches/{batch_id}:commit"): IMPORT,
    ("POST", "/import-batches/{batch_id}:decide-matches"): IMPORT,
    ("POST", "/import-batches/{batch_id}:retry"): IMPORT,
    ("POST", "/import-batches/{batch_id}:revert"): IMPORT,
    ("GET", "/source-records"): READ,
    ("PATCH", "/source-records/{record_id}"): IMPORT,
    ("POST", "/source-records/{record_id}:link"): IMPORT,
    ("POST", "/source-records:ignore"): IMPORT,
    ("GET", "/match-suggestions"): READ,
    ("POST", "/match-suggestions/{suggestion_id}:accept"): IMPORT,
    ("POST", "/match-suggestions/{suggestion_id}:reject"): IMPORT,
    ("POST", "/rules:apply"): IMPORT,
    ("POST", "/rules:test"): READ,  # tries a rule given in the body against records
    # basic data: counterparties, channels
    ("GET", "/counterparties"): READ,
    ("GET", "/counterparties:resolve"): READ,
    ("GET", "/counterparties/{counterparty_id}"): READ,
    ("POST", "/counterparties"): REFERENCE,
    ("PATCH", "/counterparties/{counterparty_id}"): REFERENCE,
    ("POST", "/counterparties/{counterparty_id}/aliases"): REFERENCE,
    ("POST", "/counterparties/{counterparty_id}/accounts"): REFERENCE,
    ("GET", "/dimensions"): READ,
    ("POST", "/dimension-types"): CONFIG,
    ("POST", "/dimension-types/{type_code}/values"): REFERENCE,
    ("PATCH", "/dimension-values/{value_id}"): REFERENCE,
    # book configuration
    ("GET", "/accounts"): READ,
    ("GET", "/accounts/{account_ref}"): READ,
    ("POST", "/accounts"): CONFIG,
    ("PATCH", "/accounts/{account_ref}"): CONFIG,
    ("POST", "/accounts:apply-template"): CONFIG,
    ("GET", "/commodities"): READ,
    ("POST", "/commodities"): CONFIG,
    ("PATCH", "/commodities/{code}"): CONFIG,
    ("GET", "/commodity-price-rules"): READ,
    ("POST", "/commodity-price-rules"): CONFIG,
    ("GET", "/fx-rates"): READ,
    ("POST", "/fx-rates"): CONFIG,
    ("GET", "/fee-rules:evaluate"): READ,  # the fee a given entry would get
    ("GET", "/fee-rules"): ADMIN_READ,
    ("POST", "/fee-rules"): CONFIG,
    ("POST", "/fee-rules/{code}:retire"): CONFIG,
    ("GET", "/rules"): ADMIN_READ,
    ("POST", "/rules"): RULES,
    ("POST", "/rules/{ref}:enable"): RULES,
    ("POST", "/rules/{ref}:disable"): RULES,
    ("GET", "/pairing-rules"): ADMIN_READ,
    ("POST", "/pairing-rules"): RULES,
    # AI
    ("GET", "/ai/status"): READ,
    ("GET", "/ai/providers"): ADMIN_READ,
    ("GET", "/ai/routes"): ADMIN_READ,
    ("GET", "/ai/usage"): ADMIN_READ,
    ("POST", "/ai/providers"): AI_CONFIG,
    ("PATCH", "/ai/providers/{provider_id}"): AI_CONFIG,
    ("DELETE", "/ai/providers/{provider_id}"): AI_CONFIG,
    ("POST", "/ai/providers/{provider_id}:test"): AI_CONFIG,
    ("PUT", "/ai/routes"): AI_CONFIG,
    # AI assistant: anyone in the book may ask (it works within their own permissions), from the web app only
    ("GET", "/agent/runs"): READ,
    ("GET", "/agent/runs/{run_id}"): READ,
    ("POST", "/agent/runs"): AGENT,
    ("POST", "/agent/runs/{run_id}:answer"): AGENT,
    ("POST", "/agent/runs/{run_id}:cancel"): AGENT,
    # access and audit
    ("GET", "/members"): ADMIN_READ,
    ("PUT", "/members/{user_id}"): ADMIN,
    ("DELETE", "/members/{user_id}"): ADMIN,
    ("GET", "/tokens"): READ,  # your own; admin:read lists everyone's
    ("POST", "/tokens"): TOKENS,  # the tier is capped by the member's role (service)
    ("POST", "/tokens/{token_id}:revoke"): TOKENS,
    ("POST", "/tokens/{token_id}:rotate"): TOKENS,
    ("GET", "/audit-events"): ADMIN_READ,
    ("GET", "/audit-events/verify"): ADMIN_READ,
    ("GET", "/mcp-calls"): ADMIN_READ,
}


def _pattern(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{\w+\})", path)
    return re.compile(
        re.escape(BOOK.removesuffix("{book_id}"))
        + "[^/:]+"
        + "".join("[^/:]+" if p.startswith("{") else re.escape(p) for p in parts)
        + "$"
    )


_PATTERNS: dict[str, list[tuple[re.Pattern[str], Need]]] = {}
for (_method, _path), _rule in ROUTES.items():
    _PATTERNS.setdefault(_method, []).append((_pattern(_path), _rule))


def rule_for(method: str, path: str) -> Need | None:
    """The table entry for a concrete request path; path parameters never contain "/" or ":"."""
    found = [rule for pattern, rule in _PATTERNS.get(method, []) if pattern.match(path)]
    return found[0] if len(found) == 1 else None


def check(method: str, path: str, ctx: RequestContext) -> None:
    """Refuse the request unless the caller holds what the route needs. Paths outside a book are not gated here."""
    if not path.startswith(BOOK.removesuffix("{book_id}")):
        return
    rule = rule_for(method, path)
    if rule is None:
        raise DomainError("FORBIDDEN_SCOPE", "这个接口没有登记所需权限，已拒绝。")
    if rule.web_only and ctx.channel != "ui":
        raise DomainError("FORBIDDEN_SCOPE", rule.web_only)
    ctx.require(*rule.scopes)
    if ctx.actor.type == "token":
        ctx.require(*rule.as_token)
    if rule.any_of and not set(rule.any_of) & ctx.actor.scopes:
        wanted = " 或 ".join(s.value for s in rule.any_of)
        raise DomainError("FORBIDDEN_SCOPE", f"缺少权限：{wanted}。", extra={"missing_scopes": [wanted]})
