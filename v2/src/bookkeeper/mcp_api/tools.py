"""MCP tools: task-oriented, schema-strict, sharing the service layer with REST (docs/09 §5).

Each tool declares the scopes it needs (it is hidden from tokens without them), whether it writes,
and — for ledger writes — the shared operation that also provides the dry run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import AuditEvent, Book, ChangeSet, Commodity, DimensionValue
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.money import AmountError, to_minor
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import (
    accounts,
    ai_providers,
    analytics,
    books,
    business,
    checks,
    exports,
    fees,
    identity,
    matching,
    operations,
    reference,
    reports,
    rules,
    tags,
    tokens,
    transactions,
    work,
)
from bookkeeper.services.context import RequestContext
from bookkeeper.services.inputs import FeeRuleIn

Kind = Literal["read", "write", "high"]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class Output:
    data: Any
    message: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
    next_action: dict[str, Any] | None = None


Handler = Callable[[Session, RequestContext, Any], Output]


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    model: type[BaseModel]
    kind: Kind
    scopes: tuple[Scope, ...]
    handler: Handler | None = None
    operation: str | None = None  # shared operation (dry run handled generically)
    rest: str | None = None  # corresponding REST operation, for drift tests and documentation
    rollback: bool = False  # read tool that needs a scratch transaction (hypothetical postings)
    any_of: tuple[Scope, ...] = ()  # visible when the token has at least one of these


TOOLS: dict[str, Tool] = {}


def tool(t: Tool) -> Tool:
    TOOLS[t.name] = t
    return t


def _book(session: Session, ctx: RequestContext) -> Book:
    book = session.get(Book, ctx.require_book())
    assert book is not None
    return book


def _minor(session: Session, ctx: RequestContext, value: str | None) -> int | None:
    if value is None:
        return None
    book = _book(session, ctx)
    try:
        return to_minor(value, reference.commodity_scales(session)[book.base_commodity])
    except AmountError as exc:
        raise DomainError("VALIDATION_FAILED", f"金额 {value} 无效：{exc}") from exc


# ------------------------------------------------------------------ context & reference (read)


class NoArgs(Args):
    pass


def _get_context(session: Session, ctx: RequestContext, args: NoArgs) -> Output:
    book = _book(session, ctx)
    today = datetime.now(ZoneInfo(book.timezone)).date()
    pending = work.collect(session, ctx, None, 0)
    data = {
        "book": {
            "id": book.id,
            "name": book.name,
            "base_commodity": book.base_commodity,
            "timezone": book.timezone,
            "fiscal_year_start_month": book.fiscal_year_start_month,
            "journal_codes": book.journal_codes,
        },
        "today": today.isoformat(),
        "caller": {"scopes": sorted(s.value for s in ctx.actor.scopes), "token_id": ctx.actor.token_id},
        "pending_work": {k: v["count"] for k, v in pending["summary"].items()},
        "conventions": {
            "amount": '写入金额用字符串小数 {"amount": "51.50", "commodity": "CNY"}，读取以 minor（最小单位整数）为准',
            "references": "科目可用编码 / 名称 / ID，渠道用代码，往来方用名称 / ID，交易用编号 T2026-000123 / ID",
            "description": "摘要格式“主体 · 业务 · 补充”；业务类型省略摘要时自动生成",
            "writes": "写入立即生效；修改与删除保留历史，可用 restore_transaction 或 undo_change_set 撤回",
        },
    }
    return Output(data, f"账套 {book.name}，本位币 {book.base_commodity}，今天 {today}，待处理 {pending['total']} 项")


tool(
    Tool(
        "get_context",
        "账套上下文",
        "开始工作时先调用：账套、本位币、时区、今天、你的权限、待处理事项数量、录入约定。",
        NoArgs,
        "read",
        (Scope.LEDGER_READ,),
        _get_context,
        rest="meta_capabilities",
    )
)


class SearchAccountsArgs(Args):
    query: str | None = Field(default=None, description="编码前缀或名称片段")
    classification: Literal["asset", "liability", "equity", "revenue", "expense"] | None = None
    role: str | None = Field(default=None, description="科目角色，如 funds、cost_operating、expense_finance_fee")
    postable_only: bool = Field(default=True, description="只返回可记账的明细科目")
    include_balances: bool = Field(default=False, description="附当前余额（各币种）")


def _search_accounts(session: Session, ctx: RequestContext, args: SearchAccountsArgs) -> Output:
    book = _book(session, ctx)
    items = accounts.list_accounts(
        session,
        book.id,
        query=args.query,
        role=args.role,
        classification=args.classification,
        postable_only=args.postable_only,
    )
    fmt = reports._Fmt(session, book)
    data = []
    for acc in items:
        row: dict[str, Any] = {
            "code": acc.code,
            "name": acc.name,
            "classification": acc.classification,
            "role": acc.role,
            "is_default_for_role": acc.is_default_for_role,
            "postable": not acc.is_group and acc.is_active,
            "manual_entry_allowed": acc.manual_entry_allowed,
            "allowed_commodities": acc.allowed_commodities,
            "description": acc.description,
        }
        if args.include_balances:
            row["balances"] = [
                {
                    "commodity": b.commodity,
                    "balance": fmt.money(b.balance, b.commodity),
                    "base": fmt.base_money(b.base_balance),
                }
                for b in accounts.current_balances(session, acc.id)
                if b.balance or b.base_balance
            ]
        data.append(row)
    return Output(data, f"找到 {len(data)} 个科目")


tool(
    Tool(
        "search_accounts",
        "查找科目",
        "按编码、名称、分类或角色查找科目（含收支分类），可附余额。",
        SearchAccountsArgs,
        "read",
        (Scope.LEDGER_READ,),
        _search_accounts,
        rest="accounts_list",
    )
)


class SearchCounterpartiesArgs(Args):
    query: str | None = Field(default=None, description="名称、别名、域名或网址；不确定写法时直接给原文")
    category: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


def _search_counterparties(session: Session, ctx: RequestContext, args: SearchCounterpartiesArgs) -> Output:
    book_id = ctx.require_book()
    items = reference.list_counterparties(session, book_id, args.query, args.category, args.limit)
    data = [reference.counterparty_details(session, cp) for cp in items]
    resolved: list[dict[str, Any]] = []
    if args.query:
        resolved = reference.resolve_counterparty_text(session, book_id, args.query)[:5]
    message = f"找到 {len(data)} 个往来方" + (f"；文本解析候选 {len(resolved)} 个" if resolved else "")
    return Output({"counterparties": data, "resolved": resolved}, message)


tool(
    Tool(
        "search_counterparties",
        "查找往来方",
        "按名称、别名、域名查找上游站点、供应商、客户；resolved 给出文本解析的候选与匹配方式。",
        SearchCounterpartiesArgs,
        "read",
        (Scope.LEDGER_READ,),
        _search_counterparties,
        rest="counterparties_list",
    )
)


class ReferenceArgs(Args):
    kind: Literal[
        "transaction_types",
        "transaction_type",
        "fee_rules",
        "channels",
        "commodities",
        "fx_rates",
        "reports",
        "tags",
    ]
    code: str | None = Field(default=None, description="kind=transaction_type 时的类型代码；fx_rates 时的外币代码")


def _get_reference(session: Session, ctx: RequestContext, args: ReferenceArgs) -> Output:
    book_id = ctx.require_book()
    data: Any
    if args.kind in ("transaction_types", "transaction_type"):
        catalogue = business.catalogue(session, book_id)
        if args.kind == "transaction_type":
            match = [t for t in catalogue if t["code"] == args.code]
            if not match:
                raise DomainError(
                    "NOT_FOUND",
                    f"交易类型 {args.code} 不存在。",
                    candidates=[{"code": t["code"], "name": t["name"]} for t in catalogue],
                )
            data = match[0]
        else:
            data = [
                {
                    k: t[k]
                    for k in ("code", "name", "category", "description", "input_mode", "fee_rules_apply", "example")
                }
                for t in catalogue
            ]
    elif args.kind == "fee_rules":
        ctx.require(Scope.ADMIN_READ)
        data = [fees.view(r) for r in fees.list_rules(session, book_id)]
    elif args.kind == "channels":
        data = [
            {"code": v.code, "name": v.name, "id": v.id, "is_active": v.is_active}
            for t, values in reference.list_dimensions(session, book_id)
            if t.code == "channel"
            for v in values
        ]
    elif args.kind == "commodities":
        data = [reference.commodity_view(c) for c in reference.commodities_by_code(session).values()]
    elif args.kind == "fx_rates":
        data = [
            reference.fx_rate_view(r)
            for r in reference.list_fx_rates(
                session, base=args.code, quote=None, date_from=None, date_to=None, limit=60
            )
        ]
    elif args.kind == "tags":
        data = tags.list_tags(session, ctx)
    else:
        data = analytics.CATALOGUE
    count = len(data) if isinstance(data, list) else 1
    return Output(data, f"{args.kind}：{count} 项")


tool(
    Tool(
        "get_reference",
        "基础资料",
        "交易类型（transaction_type 返回输入 JSON Schema、默认科目与示例）、"
        "手续费规则（需要管理员只读档位；算某笔的手续费用 evaluate_fee）、渠道、币种、汇率、标签、报表目录。",
        ReferenceArgs,
        "read",
        (Scope.LEDGER_READ,),
        _get_reference,
        rest="transaction_types_list",
    )
)


# ------------------------------------------------------------------ queries (read)


class SearchTransactionsArgs(Args):
    q: str | None = Field(default=None, description="摘要、交易编号或订单号片段")
    status: Literal["posted", "reversed"] = Field(default="posted", description="posted 正常；reversed 已删除")
    type: str | None = Field(default=None, description="交易类型代码；多个用逗号分隔，如 sale_refund,purchase_refund")
    date_from: date | None = None
    date_to: date | None = None
    counterparty: str | None = None
    channel: str | None = Field(default=None, description="渠道代码")
    account: str | None = Field(default=None, description="科目编码，含下级科目")
    amount_min: str | None = Field(default=None, description='金额下限（本位币，字符串小数，如 "50"）')
    amount_max: str | None = None
    is_estimate: bool | None = None
    linked_to: str | None = Field(default=None, description="与该交易有退款关联的交易")
    tag: str | None = Field(default=None, description="带有该标签的交易")
    commodity: str | None = Field(
        default=None, description="有该币种分录行的交易，如 GBP；与 account 同时给出时限定在该科目"
    )
    created_channel: Literal["ui", "api", "mcp", "import", "system", "migration", "cli"] | None = None
    cursor: str | None = Field(default=None, description="上一页返回的 next_cursor")
    limit: int = Field(default=20, ge=1, le=100)


def _search_transactions(session: Session, ctx: RequestContext, args: SearchTransactionsArgs) -> Output:
    cursor = tuple(args.cursor.split("|", 1)) if args.cursor else None
    rows = transactions.search(
        session,
        ctx,
        status=args.status,
        type_code=args.type,
        date_from=args.date_from,
        date_to=args.date_to,
        counterparty=args.counterparty,
        text=args.q,
        created_channel=args.created_channel,
        cursor=cursor,  # type: ignore[arg-type]
        limit=args.limit,
        channel=args.channel,
        account=args.account,
        amount_min=_minor(session, ctx, args.amount_min),
        amount_max=_minor(session, ctx, args.amount_max),
        is_estimate=args.is_estimate,
        linked_to=args.linked_to,
        tag=args.tag,
        commodity=args.commodity,
    )
    more = len(rows) > args.limit
    rows = rows[: args.limit]
    keys = ("id", "number", "type", "status", "effective_date", "description", "amount", "is_estimate")
    data = [{k: transactions.header_view(t, c)[k] for k in keys} for t, c in rows]
    next_cursor = f"{rows[-1][0].effective_date.isoformat()}|{rows[-1][0].id}" if more else None
    return Output(
        {"transactions": data, "next_cursor": next_cursor}, f"{len(data)} 笔交易" + ("（还有更多）" if more else "")
    )


tool(
    Tool(
        "search_transactions",
        "查找交易",
        "按文本、类型、日期、往来方、渠道、科目、币种、金额区间、估算、关联交易、标签筛选，按日期倒序分页；"
        "status=reversed 查已删除的交易。",
        SearchTransactionsArgs,
        "read",
        (Scope.LEDGER_READ,),
        _search_transactions,
        rest="transactions_list",
    )
)


class GetTransactionArgs(Args):
    ref: str = Field(description="交易编号或 ID")
    explain: bool = Field(default=False, description="附解释链（手续费规则候选、计算过程）")


def _get_transaction(session: Session, ctx: RequestContext, args: GetTransactionArgs) -> Output:
    txn, code = transactions.load(session, ctx, args.ref)
    data = transactions.full_view(session, txn, code)
    if args.explain:
        data["explain"] = transactions.explain(session, txn, code)
    return Output(data, f"{txn.number} {txn.description}（{txn.status}）")


tool(
    Tool(
        "get_transaction",
        "交易详情",
        "交易头、输入、计算值、分录与历史、关联交易（退款）、来源与解释链。",
        GetTransactionArgs,
        "read",
        (Scope.LEDGER_READ,),
        _get_transaction,
        rest="transactions_get",
    )
)


class BalancesArgs(Args):
    as_of: date | None = Field(default=None, description="截止日期，默认今天")
    accounts: list[str] = Field(default_factory=list, description="科目编码；空 = 全部有余额的科目")


def _get_balances(session: Session, ctx: RequestContext, args: BalancesArgs) -> Output:
    book = _book(session, ctx)
    as_of = args.as_of or datetime.now(ZoneInfo(book.timezone)).date()
    data = reports.balances(session, ctx, as_of, args.accounts or None)
    return Output(data, f"{as_of} 余额")


tool(
    Tool(
        "get_balances",
        "科目余额",
        "截至某日的科目余额（原币与本位币）。",
        BalancesArgs,
        "read",
        (Scope.LEDGER_READ,),
        _get_balances,
        rest="balances_get",
    )
)


class ReportArgs(Args):
    report: Literal["summary", "income_statement", "operations", "sales", "fees", "credit_purchases", "trial_balance"]
    date_from: date
    date_to: date
    period: Literal["year", "quarter", "month", "week", "day"] | None = Field(
        default=None, description="经营 / 销售 / 采购报表的分期；利润表用 columns"
    )
    columns: Literal["year", "quarter", "month", "week", "day"] | None = None


def _run_report(session: Session, ctx: RequestContext, args: ReportArgs) -> Output:
    a, b = args.date_from, args.date_to
    data = {
        "summary": lambda: analytics.summary(session, ctx, a, b),
        "income_statement": lambda: analytics.income_statement(session, ctx, a, b, args.columns),
        "operations": lambda: analytics.operations(session, ctx, a, b, args.period or "day"),
        "sales": lambda: analytics.sales(session, ctx, a, b, args.period),
        "fees": lambda: analytics.fees(session, ctx, a, b),
        "credit_purchases": lambda: analytics.credit_purchases(session, ctx, a, b, args.period),
        "trial_balance": lambda: reports.trial_balance(session, ctx, a, b),
    }[args.report]()
    return Output(data, data.get("title", args.report))


tool(
    Tool(
        "run_report",
        "运行报表",
        "概览（利润、各币种资金、前五渠道与站点）、利润表、经营日报、销售分析（渠道）、手续费分析、"
        "额度采购分析（上游站点）、试算平衡表；每行带 drilldown，可直接作为 search_transactions 的参数反查明细。",
        ReportArgs,
        "read",
        (Scope.LEDGER_READ,),
        _run_report,
        rest="reports_get",
    )
)


class ExportArgs(Args):
    format: Literal["csv", "xlsx", "beancount", "json"] = Field(
        description="csv / xlsx（表格）、beancount（纯文本复式账本，可用 bean-check / Fava 打开）、json（结构化）"
    )
    date_from: date | None = Field(default=None, description="省略则从第一笔分录开始")
    date_to: date | None = None


def _export(session: Session, ctx: RequestContext, args: ExportArgs) -> Output:
    if ctx.content_store is None:
        raise DomainError("INVALID_STATE", "文件存储不可用。")
    data = exports.save(session, ctx, ctx.content_store, args.format, args.date_from, args.date_to)
    params = "&".join(f"{k}={v}" for k, v in (("date_from", args.date_from), ("date_to", args.date_to)) if v)
    data["export_url"] = f"/api/v1/books/{ctx.require_book()}/exports/{args.format}" + (f"?{params}" if params else "")
    return Output(
        data,
        f"已导出 {data['lines']} 行分录：{data['filename']}",
        next_action={
            "download": data["download"],
            "export_url": data["export_url"],
            "note": "用同一令牌 GET：download 是存档快照（需 files:read），export_url 现场重新生成（需 ledger:read）",
        },
    )


tool(
    Tool(
        "export_ledger",
        "导出账本",
        "把指定区间的分录导出为 CSV / XLSX / Beancount / JSON 文件并存入文件库，返回文件 ID 与下载地址；"
        "分析数据优先用 run_report / query_ledger，导出用于存档或交给其他工具。",
        ExportArgs,
        "read",
        (Scope.LEDGER_READ,),
        _export,
        rest="exports_get",
    )
)


class QueryArgs(Args):
    date_from: date
    date_to: date
    group_by: list[str] = Field(default_factory=list, description="最多 4 个：" + "、".join(analytics.GROUPS))
    measures: list[str] = Field(
        default_factory=lambda: ["base_amount", "count"], description="、".join(analytics.MEASURES)
    )
    accounts: list[str] = Field(default_factory=list, description="科目编码（含下级）")
    classifications: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    counterparties: list[str] = Field(default_factory=list)
    transaction_types: list[str] = Field(default_factory=list)
    line_roles: list[str] = Field(default_factory=list)
    commodities: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, description="只统计带这些标签（任一）的交易")
    sign: Literal["natural", "debit"] = "natural"


def _query(session: Session, ctx: RequestContext, args: QueryArgs) -> Output:
    data = analytics.aggregate(session, ctx, analytics.Query(**args.model_dump()))
    return Output(data, f"{len(data['rows'])} 行汇总")


tool(
    Tool(
        "query_ledger",
        "自定义汇总",
        "对分录行按任意维度汇总（期间、科目、分类、渠道、往来方、交易类型、行角色、币种、估算），每行带反查条件。"
        "例：支出分类 classifications=[expense], group_by=[account]；"
        "渠道月报 accounts=[5001], group_by=[month, channel]。",
        QueryArgs,
        "read",
        (Scope.LEDGER_READ,),
        _query,
        rest="reports_query",
    )
)


class ExplainArgs(Args):
    ref: str | None = Field(default=None, description="已有交易的编号或 ID")
    type: str | None = Field(default=None, description="假设录入：交易类型")
    inputs: dict[str, Any] | None = Field(default=None, description="假设录入：业务输入")
    effective_date: date | None = None
    counterparty: str | None = None


def _explain(session: Session, ctx: RequestContext, args: ExplainArgs) -> Output:
    if args.ref:
        txn, code = transactions.load(session, ctx, args.ref)
        return Output(transactions.explain(session, txn, code), f"{txn.number} 的解释链")
    if not args.type:
        raise DomainError("VALIDATION_FAILED", "请提供 ref，或 type + inputs 进行假设计算。")
    book = _book(session, ctx)
    txn, _code = transactions.hypothetical(
        session,
        ctx,
        {
            "type": args.type,
            "effective_date": args.effective_date or datetime.now(ZoneInfo(book.timezone)).date(),
            "inputs": args.inputs or {},
            "counterparty": args.counterparty,
        },
    )
    data = transactions.explain(session, txn, args.type) | {"description": txn.description, "hypothetical": True}
    return Output(data, "假设录入的解释链（未保存）")


tool(
    Tool(
        "explain_posting",
        "解释分录",
        "说明一笔交易（或一组假设输入）如何生成分录：解析后的输入、命中与未命中的手续费规则及原因、计算值、分录行。不保存任何数据。",
        ExplainArgs,
        "read",
        (Scope.LEDGER_READ,),
        _explain,
        rest="transactions_explain",
        rollback=True,
    )
)


class EvaluateFeeArgs(Args):
    type: Literal["sale", "credit_purchase", "expense", "transfer", "sale_refund"]
    amount: str = Field(description="计费基数：销售毛额或采购面值，字符串小数")
    on: date
    channel: str | None = None
    counterparty: str | None = None
    commodity: str = "CNY"


def _evaluate_fee(session: Session, ctx: RequestContext, args: EvaluateFeeArgs) -> Output:
    data = fees.evaluate(
        session, ctx.require_book(), args.type, args.amount, args.on, args.channel, args.counterparty, args.commodity
    )
    rule = data["rule"]
    return Output(
        data, f"手续费 {data['fee']}" + (f"（规则 {rule['code']}@{rule['version']}）" if rule else "（无适用规则）")
    )


tool(
    Tool(
        "evaluate_fee",
        "试算手续费",
        "按与记账相同的规则选择逻辑，返回命中的手续费规则与金额。",
        EvaluateFeeArgs,
        "read",
        (Scope.LEDGER_READ,),
        _evaluate_fee,
        rest="fee_rules_evaluate",
    )
)


class ChecksArgs(Args):
    codes: list[str] = Field(default_factory=list, description="检查代码；空 = 全部")


def _run_checks(session: Session, ctx: RequestContext, args: ChecksArgs) -> Output:
    run = checks.run_checks(session, ctx, args.codes or None)
    data = checks.run_view(session, run)
    failed = [r for r in data.get("results", []) if r.get("status") == "failed"]
    return Output(data, f"检查 {run.status}：{len(failed)} 项未通过")


tool(
    Tool(
        "run_checks",
        "健康检查",
        "试算平衡、分录平衡、哈希链、编号连续、余额缓存、锁账、孤立数据、待核对款项等检查。",
        ChecksArgs,
        "read",
        (Scope.LEDGER_READ,),
        _run_checks,
        rest="checks_run",
    )
)


class AuditArgs(Args):
    view: Literal["events", "change_sets"] = "events"
    entity_id: str | None = None
    change_set_id: str | None = None
    channel: Literal["ui", "api", "mcp", "import", "worker", "cli", "migration", "system"] | None = None
    since: datetime | None = None
    limit: int = Field(default=30, ge=1, le=200)


def _audit(session: Session, ctx: RequestContext, args: AuditArgs) -> Output:
    book_id = ctx.require_book()
    if args.view == "change_sets":
        stmt = select(ChangeSet).where(ChangeSet.book_id == book_id)
        if args.channel:
            stmt = stmt.where(ChangeSet.channel == args.channel)
        if args.since:
            stmt = stmt.where(ChangeSet.created_at >= args.since)
        rows = session.execute(stmt.order_by(ChangeSet.created_at.desc()).limit(args.limit)).scalars()
        data: list[dict[str, Any]] = [
            {
                "id": c.id,
                "operation": c.operation,
                "channel": c.channel,
                "mcp_client": c.mcp_client,
                "status": c.status,
                "entity_counts": c.entity_counts,
                "summary": c.summary,
                "created_at": c.created_at.isoformat(),
            }
            for c in rows
        ]
        return Output(data, f"{len(data)} 个变更集")
    stmt2 = select(AuditEvent).where(AuditEvent.book_id == book_id)
    if args.entity_id:
        stmt2 = stmt2.where(AuditEvent.entity_id == args.entity_id)
    if args.change_set_id:
        stmt2 = stmt2.where(AuditEvent.change_set_id == args.change_set_id)
    if args.channel:
        stmt2 = stmt2.where(AuditEvent.channel == args.channel)
    if args.since:
        stmt2 = stmt2.where(AuditEvent.occurred_at >= args.since)
    events = session.execute(stmt2.order_by(AuditEvent.seq.desc()).limit(args.limit)).scalars()
    rows_out: list[dict[str, Any]] = [
        {
            "seq": e.seq,
            "occurred_at": e.occurred_at.isoformat(),
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "channel": e.channel,
            "mcp_client": e.mcp_client,
            "change_set_id": e.change_set_id,
            "diff": e.diff,
        }
        for e in events
    ]
    return Output(rows_out, f"{len(rows_out)} 条审计事件")


tool(
    Tool(
        "get_audit_trail",
        "审计记录",
        "按实体、变更集、渠道（如 mcp）、时间查询审计事件或变更集，用于追溯与撤销。需要管理员只读档位。",
        AuditArgs,
        "read",
        (Scope.ADMIN_READ,),
        _audit,
        rest="audit_events_list",
    )
)


class AdminInfoArgs(Args):
    kind: Literal["members", "tokens", "rules", "pairing_rules", "fee_rules", "ai", "book"] = Field(
        description="members 成员与角色；tokens 令牌（不含密钥）；rules 分类规则；pairing_rules 配对规则；"
        "fee_rules 手续费规则；ai AI 提供商与任务分配（不含密钥）；book 账套设置"
    )


def _admin_info(session: Session, ctx: RequestContext, args: AdminInfoArgs) -> Output:
    book_id = ctx.require_book()
    data: Any
    if args.kind == "members":
        data = [
            {"user": identity.user_view(user), "role": member.role, "since": member.created_at.isoformat()}
            for member, user in books.list_members(session, ctx)
        ]
    elif args.kind == "tokens":
        data = tokens.list_views(session, ctx)
    elif args.kind == "rules":
        data = [rules.view(r) for r in rules.list_rules(session, book_id)]
    elif args.kind == "pairing_rules":
        data = [matching.pairing_view(r) for r in matching.list_pairing_rules(session, book_id)]
    elif args.kind == "fee_rules":
        data = [fees.view(r) for r in fees.list_rules(session, book_id)]
    elif args.kind == "ai":
        data = {
            "providers": [ai_providers.view(p) for p in ai_providers.list_providers(session, book_id)],
            "routes": ai_providers.get_routes(session, book_id),
            "note": "密钥不出现在任何接口里；修改只能在网页端 设置 → AI 模型。",
        }
    else:
        data = books.book_view(_book(session, ctx))
    count = len(data) if isinstance(data, list) else 1
    return Output(data, f"{args.kind}：{count} 项")


tool(
    Tool(
        "get_admin_info",
        "管理信息",
        "只读查看成员、令牌、分类规则、配对规则、手续费规则、AI 提供商与任务分配、账套设置；不含任何密钥。"
        "需要管理员只读档位。",
        AdminInfoArgs,
        "read",
        (Scope.ADMIN_READ,),
        _admin_info,
        rest="members_list",
    )
)


class WorkArgs(Args):
    kinds: list[str] = Field(default_factory=list, description="空 = 全部：" + "、".join(work.KINDS))
    limit: int = Field(default=20, ge=1, le=100)


def _work(session: Session, ctx: RequestContext, args: WorkArgs) -> Output:
    data = work.collect(session, ctx, args.kinds or None, args.limit)
    return Output(data, f"待处理 {data['total']} 项")


tool(
    Tool(
        "list_pending_work",
        "待处理事项",
        "待补全的导入记录、待确认的匹配、未完成的导入、估算手续费、待核对款项、未通过的检查；每项附建议使用的工具与参数。",
        WorkArgs,
        "read",
        (Scope.LEDGER_READ,),
        _work,
        rest="work_items_list",
    )
)


# ------------------------------------------------------------------ writes


class UpsertReferenceArgs(Args):
    kind: Literal[
        "counterparty", "counterparty_update", "alias", "counterparty_account", "channel", "commodity", "fx_rate"
    ]
    fields: dict[str, Any] = Field(
        description="counterparty: name, category, roles?, domains?, aliases?, notes?；"
        "counterparty_update: id, expected_version, 及要改的字段；alias: counterparty, pattern, match_type；"
        "counterparty_account: counterparty, label, identifier?；"
        "channel: code, name?, aliases?, is_active?（代码已存在则修改）；"
        "commodity: code, name?, kind?(fiat/credit/other), scale?, symbol?, is_active?（代码已存在则修改）；"
        "fx_rate: base, quote, rate_date, rate"
    )


def _upsert_reference(session: Session, ctx: RequestContext, args: UpsertReferenceArgs) -> Output:
    f = dict(args.fields)
    book_id = ctx.require_book()
    try:
        if args.kind == "counterparty":
            cp = reference.create_counterparty(session, ctx, **f)
            return Output(reference.counterparty_details(session, cp), f"已新建往来方 {cp.name}")
        if args.kind == "counterparty_update":
            cp_id = reference.get_counterparty(session, book_id, f.pop("id")).id
            cp = reference.update_counterparty(session, ctx, cp_id, int(f.pop("expected_version")), f)
            return Output(reference.counterparty_details(session, cp), f"已修改往来方 {cp.name}")
        if args.kind == "alias":
            cp = reference.get_counterparty(session, book_id, f.pop("counterparty"))
            alias = reference.add_alias(
                session, ctx, cp.id, f["pattern"], f.get("match_type", "exact"), f.get("priority", 100)
            )
            return Output(
                {"id": alias.id, "counterparty": cp.name, "pattern": alias.pattern}, f"已为 {cp.name} 添加别名"
            )
        if args.kind == "counterparty_account":
            cp = reference.get_counterparty(session, book_id, f.pop("counterparty"))
            acc = reference.add_counterparty_account(session, ctx, cp.id, f["label"], f.get("identifier"))
            return Output({"id": acc.id, "counterparty": cp.name, "label": acc.label}, f"已为 {cp.name} 添加子账户")
        if args.kind == "channel":
            channel_type = reference.get_dimension_type(session, book_id, "channel")
            code = str(f.pop("code"))
            existing = session.execute(
                select(DimensionValue).where(DimensionValue.type_id == channel_type.id, DimensionValue.code == code)
            ).scalar_one_or_none()
            if existing is None:
                value = reference.create_dimension_value(
                    session, ctx, type_code="channel", code=code, name=f["name"], aliases=f.get("aliases") or []
                )
                verb = "已新增"
            else:
                value = reference.update_dimension_value(session, ctx, existing.id, existing.version, f)
                verb = "已修改"
            return Output(reference.dimension_value_view(value, "channel"), f"{verb}渠道 {value.name}")
        if args.kind == "commodity":
            code = str(f.pop("code")).upper()
            if session.get(Commodity, code) is None:
                item = reference.create_commodity(session, ctx, code=code, **f)
                verb = "已新增"
            else:
                item = reference.update_commodity(session, ctx, code, f)
                verb = "已修改"
            return Output(reference.commodity_view(item), f"{verb}币种 {item.code} {item.name}")
        rate = reference.add_manual_rate(
            session,
            ctx,
            base=f["base"],
            quote=f["quote"],
            rate_date=date.fromisoformat(str(f["rate_date"])),
            rate=f["rate"],
        )
        return Output(reference.fx_rate_view(rate), f"已录入汇率 {rate.base}/{rate.quote} {rate.rate}")
    except (KeyError, TypeError) as exc:
        raise DomainError("VALIDATION_FAILED", f"fields 缺少或包含不支持的字段：{exc}。") from exc


tool(
    Tool(
        "upsert_reference",
        "维护基础资料",
        "新建 / 修改往来方，添加别名、子账户，新增渠道，录入手工汇率。",
        UpsertReferenceArgs,
        "write",
        (Scope.REFERENCE_WRITE,),
        _upsert_reference,
        rest="counterparties_create",
    )
)


class FeeRuleArgs(Args):
    action: Literal["save", "retire"]
    rule: FeeRuleIn | None = Field(default=None, description="action=save：规则内容；同 code 再提交即新版本")
    code: str | None = Field(default=None, description="action=retire：停用的规则代码")


def _fee_rule(session: Session, ctx: RequestContext, args: FeeRuleArgs) -> Output:
    if args.action == "save":
        if args.rule is None:
            raise DomainError("VALIDATION_FAILED", "action=save 需要 rule。")
        row = fees.save_rule(session, ctx, args.rule.model_dump())
        return Output(
            fees.view(row),
            f"已保存手续费规则 {row.code}@{row.version}（{row.valid_from} 起）",
            next_action={
                "tool": "repost_transactions",
                "hint": "已入账的交易保持原手续费；如需按新规则重算，先 dry_run 试算",
                "args": {
                    "reason": f"手续费规则 {row.code} 更新",
                    "date_from": row.valid_from.isoformat(),
                    "dry_run": True,
                },
            },
        )
    if not args.code:
        raise DomainError("VALIDATION_FAILED", "action=retire 需要 code。")
    rows = fees.retire(session, ctx, args.code)
    return Output([fees.view(r) for r in rows], f"已停用规则 {args.code}（{len(rows)} 个版本）")


tool(
    Tool(
        "manage_fee_rule",
        "手续费规则",
        "新建规则或新版本（比例 rate、固定额 fixed、上下限、币种、适用类型 / 渠道 / 往来方、生效日），或停用规则。",
        FeeRuleArgs,
        "high",
        (Scope.CONFIG_WRITE,),
        _fee_rule,
        rest="fee_rules_save",
    )
)


# ------------------------------------------------------------------ import tools

from bookkeeper.mcp_api import tools_import  # noqa: E402,F401  (registers its tools)

# ------------------------------------------------------------------ operation-backed tools

OPERATION_TOOLS: tuple[tuple[str, str, str, str, Kind, tuple[Scope, ...], str], ...] = (
    (
        "create_transaction",
        "记账",
        "记一笔交易，立即入账：业务类型（sale、sale_refund、credit_purchase、expense、purchase_refund、"
        "transfer）填 inputs，手工凭证 / 期初余额填 lines。先用 get_reference(kind=transaction_type) "
        "查看输入结构；dry_run=true 只试算分录。",
        "transactions.create",
        "write",
        (Scope.LEDGER_WRITE,),
        "transactions_create",
    ),
    (
        "create_transactions",
        "批量记账",
        "一次记最多 200 笔；atomic=true 任一失败全部不入账（错误含 index），false 逐条返回结果。",
        "transactions.batch",
        "write",
        (Scope.LEDGER_WRITE,),
        "transactions_batch",
    ),
    (
        "update_transaction",
        "修改交易",
        "修改任何字段，inputs 只给变化的键（null 删除该键）。影响账面的修改会冲销原分录并按新内容重新入账，"
        "交易编号不变；可先 dry_run 查看新分录与手续费。",
        "transactions.edit",
        "write",
        (Scope.LEDGER_WRITE,),
        "transactions_edit",
    ),
    (
        "delete_transaction",
        "删除交易",
        "删除一笔交易：原分录被冲销，交易从列表与报表中消失；账本保留历史，restore_transaction 可恢复。",
        "transactions.delete",
        "high",
        (Scope.LEDGER_WRITE,),
        "transactions_delete",
    ),
    (
        "restore_transaction",
        "恢复交易",
        "恢复已删除的交易（按删除前的分录重新入账）。",
        "transactions.restore",
        "write",
        (Scope.LEDGER_WRITE,),
        "transactions_restore",
    ),
    (
        "repost_transactions",
        "按新规则重算",
        "手续费规则或汇率修正后，按当前规则重算销售 / 额度采购等交易；实际录入的手续费不受影响。务必先 dry_run。",
        "transactions.repost",
        "high",
        (Scope.LEDGER_WRITE,),
        "transactions_repost",
    ),
    (
        "commit_import",
        "完成导入",
        "把导入批次入账：已分类记录直接入账，匹配 / 配对的记录作为证据关联，"
        "未分类记录按来源策略留待补全或记入待核对款项；有待确认匹配的记录不会入账。",
        "imports.commit",
        "high",
        (Scope.IMPORT_WRITE,),
        "import_batches_commit",
    ),
    (
        "revert_import",
        "撤销导入",
        "撤销已完成的批次：删除它入账的交易、解除证据关联；记录保留并可重新导入。",
        "imports.revert",
        "high",
        (Scope.IMPORT_WRITE,),
        "import_batches_revert",
    ),
    (
        "apply_rules",
        "执行规则",
        "按当前规则、往来方与来源默认值重新分类未入账的来源记录（可限定批次或记录）。",
        "rules.apply",
        "write",
        (Scope.IMPORT_WRITE,),
        "rules_apply",
    ),
    (
        "undo_change_set",
        "撤销变更集",
        "撤销某次写入的全部结果（新记的删除、删除的恢复、修改的改回、导入撤销、规则改动还原）；"
        "change_set_id 见写入回执或 get_audit_trail。",
        "change_sets.undo",
        "high",
        (Scope.LEDGER_WRITE,),
        "change_sets_undo",
    ),
)

COMMON_WRITE_FIELDS: dict[str, Any] = {
    "dry_run": (bool, Field(default=False, description="只计算并返回结果，不保存")),
    "idempotency_key": (
        str | None,
        Field(default=None, max_length=128, description="重试同一写入时传相同的键，避免重复入账"),
    ),
}


def tool_model(base: type[BaseModel], name: str) -> type[BaseModel]:
    model: type[BaseModel] = create_model(name, __base__=base, **COMMON_WRITE_FIELDS)
    return model


for _name, _title, _desc, _op, _kind, _scopes, _rest in OPERATION_TOOLS:
    tool(
        Tool(
            _name,
            _title,
            _desc,
            tool_model(operations.get(_op).model, "".join(p.title() for p in _name.split("_")) + "Args"),
            _kind,
            _scopes,
            operation=_op,
            rest=_rest,
        )
    )

for _t in [t for t in TOOLS.values() if t.kind != "read" and t.operation is None]:
    TOOLS[_t.name] = Tool(
        _t.name,
        _t.title,
        _t.description,
        tool_model(_t.model, _t.model.__name__ + "WithOptions"),
        _t.kind,
        _t.scopes,
        _t.handler,
        rest=_t.rest,
    )

# ------------------------------------------------------------------ file tools

from bookkeeper.mcp_api import tools_files  # noqa: E402,F401  (registers its tools)
