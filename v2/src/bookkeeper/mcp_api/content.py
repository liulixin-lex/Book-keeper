"""Server instructions, resources and prompts for AI clients (docs/09 §3, §7)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import mcp_types as types

from bookkeeper.domain.errors import DomainError

if TYPE_CHECKING:
    from bookkeeper.mcp_api.server import Executor, McpAuth

INSTRUCTIONS = """你连接的是记账系统 bookkeeper，用来记录与统计中转站的经营数据（账套由令牌决定，本位币通常为 CNY，时区 Asia/Shanghai）。
1. 开始时调用 get_context：账套、今天、你的权限、待处理事项。
2. 金额：读取以 minor（最小单位整数）为准；写入用字符串小数 {"amount": "51.50", "commodity": "CNY"}，不要用浮点数。
3. 记账用 create_transaction 的业务类型：sale（销售）、sale_refund、credit_purchase（向上游站点购买额度，必须给 counterparty）、
   expense（其他支出，category 为支出科目）、purchase_refund、transfer（划转 / 结汇）。手续费由规则自动计算，有实际手续费时一并填写。
   不确定输入结构时先 get_reference(kind="transaction_type", code=...)；不确定结果时先 dry_run=true。
4. 不要猜测：往来方先 search_counterparties，科目先 search_accounts；收到 candidates 时请用户确认。
5. 摘要可省略（系统按“主体 · 业务 · 补充”自动生成）；订单号放 order_no，外部唯一单号放 external_ref（用于防重复）。
6. 写入立即生效。update_transaction 可改任何字段（inputs 只给变化的键），delete_transaction 删除，restore_transaction 恢复；
   账本保留全部历史，修改与删除都能撤回。
7. 出错时读 code、message、errors、next_action；retryable=false 不要原样重试。重试写入时传同一个 idempotency_key。
8. 你的写入都标记为 MCP 写入并归入变更集（meta.change_set_id），写错了用 undo_change_set 整次撤销。
9. 报表每行带 drilldown，可直接作为 search_transactions 的参数查看明细。"""

GUIDES: dict[str, str] = {
    "posting": """# 记账指南
- 销售：sale，inputs = {gross, channel, fee?}；手续费按渠道规则从毛额扣除，实际扣费不同则填 fee。
- 额度采购：credit_purchase，counterparty = 上游站点；inputs = {face?, total?, credit_quantity?, channel}，面值计成本，差额计手续费。
- 其他支出：expense，inputs = {amount, category}；category 为支出科目，如 5401.04 服务器与网络、5601.01 广告推广费。
- 退款：sale_refund / purchase_refund，inputs.original = 原交易编号，系统继承渠道与科目并校验累计不超额。
- 划转与结汇：transfer，同一资金账户不同币种即结汇；无当日参考汇率时按实际兑换汇率折算。
- 手工凭证：manual_journal，lines = [{account, side, amount}]，摘要格式“调整 · 原因”。
- 渠道写代码、名称或别名都行（liandong = 链动 = 链动小铺）。
- 往来方设了默认交易类型与默认渠道时（upsert_reference 的 default_type / default_channel），只给 counterparty 与金额即可，
  如 {counterparty: "relay-b.example", inputs: {face: {amount: "50"}}}；回执 provenance.defaults 标出自动带出的字段。
- 新币种：upsert_reference(kind="commodity", fields={code: "JPY", name: "日元", scale: 0})，法币每日自动获取参考汇率。""",
    "edits": """# 修改、删除与撤销
- 修改：update_transaction(ref, …)，任何字段都能改，inputs 只给变化的键。影响账面的修改（金额、日期、往来方、渠道…）
  会冲销原分录并按新内容重新入账，交易编号不变。
- 删除：delete_transaction（原分录被冲销，交易从列表与报表中消失）；restore_transaction 恢复。
- AI 写错：get_audit_trail(channel="mcp") 找到变更集，undo_change_set 撤销整次写入。""",
    "fees": """# 手续费规则
- 规则 = 比例 rate + 固定额 fixed，可设上下限与币种，按交易类型、渠道、往来方、生效日选择；同 code 再保存即新版本。
- 适用类型：sale、credit_purchase、expense、transfer、sale_refund；不列类型的规则只用于 sale 与 credit_purchase。
- 某站点按渠道的费率：规则 counterparties=[站点]、channels=[渠道]（如 relay-b.example 经链动 3%、经云猫 0%）；往来方详情列出这些规则。
- 实际录入的手续费总是优先，与规则不一致时给出 FEE_DEVIATION 警告。
- evaluate_fee 试算；explain_posting 查看命中与未命中原因。
- 改规则不影响已入账的交易；需要追溯时 repost_transactions 先 dry_run，再执行（实际录入的手续费不受影响）。""",
    "review": """# 月度复盘
1. list_pending_work：补全导入记录、确认匹配、处理估算手续费与待核对款项。
2. run_report：summary（利润与资金）、operations（逐日经营）、sales（渠道）、credit_purchases（上游站点）、fees（手续费）。
3. run_checks：账本完整性检查。
4. 存档：export_ledger(format="beancount" 或 "xlsx")。""",
}

RESOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("ledger://context", "context", "账套上下文", "get_context"),
    ("ledger://accounts", "accounts", "科目表（含收支分类）", "search_accounts"),
    ("ledger://transaction-types", "transaction-types", "交易类型与示例", "get_reference"),
    ("ledger://fee-rules", "fee-rules", "手续费规则", "get_reference"),
    ("ledger://channels", "channels", "渠道", "get_reference"),
    ("ledger://reports", "reports", "报表目录", "get_reference"),
    ("ledger://work", "work", "待处理事项", "list_pending_work"),
)
TOOL_ARGS: dict[str, dict[str, Any]] = {
    "ledger://context": {},
    "ledger://accounts": {"postable_only": False},
    "ledger://transaction-types": {"kind": "transaction_types"},
    "ledger://fee-rules": {"kind": "fee_rules"},
    "ledger://channels": {"kind": "channels"},
    "ledger://reports": {"kind": "reports"},
    "ledger://work": {},
}


def resources() -> list[types.Resource]:
    items = [
        types.Resource(uri=uri, name=name, title=title, mime_type="application/json")
        for uri, name, title, _t in RESOURCES
    ]
    items += [
        types.Resource(
            uri=f"ledger://guides/{topic}",
            name=f"guide-{topic}",
            title=text.splitlines()[0].lstrip("# "),
            mime_type="text/markdown",
        )
        for topic, text in GUIDES.items()
    ]
    return items


def resource_templates() -> list[types.ResourceTemplate]:
    return [
        types.ResourceTemplate(
            uri_template="ledger://transactions/{ref}",
            name="transaction",
            title="交易详情",
            mime_type="application/json",
        ),
        types.ResourceTemplate(
            uri_template="ledger://accounts/{code}", name="account", title="科目与余额", mime_type="application/json"
        ),
    ]


def read(executor: Executor, auth: McpAuth, uri: str) -> tuple[str, str]:
    if uri.startswith("ledger://guides/"):
        topic = uri.removeprefix("ledger://guides/")
        if topic not in GUIDES:
            raise DomainError("NOT_FOUND", f"资源 {uri} 不存在。")
        return GUIDES[topic], "text/markdown"
    if uri in TOOL_ARGS:
        tool = next(t for u, _n, _ti, t in RESOURCES if u == uri)
        body, _err = executor.call(auth, tool, TOOL_ARGS[uri])
    elif uri.startswith("ledger://transactions/"):
        body, _err = executor.call(auth, "get_transaction", {"ref": uri.removeprefix("ledger://transactions/")})
    elif uri.startswith("ledger://accounts/"):
        body, _err = executor.call(
            auth,
            "search_accounts",
            {"query": uri.removeprefix("ledger://accounts/"), "include_balances": True, "postable_only": False},
        )
    else:
        raise DomainError("NOT_FOUND", f"资源 {uri} 不存在。")
    return json.dumps(body, ensure_ascii=False), "application/json"


PROMPTS: dict[str, tuple[str, list[tuple[str, str, bool]], str]] = {
    "record_transactions": (
        "用自然语言记账",
        [("description", "业务内容或凭证要点（可多笔）", True)],
        "请把下面的业务记入账本：\n{description}\n\n"
        "步骤：get_context → 判断每笔的交易类型（必要时 get_reference 查看输入）→ 往来方用 search_counterparties 确认 → "
        "不确定的地方先问我 → create_transaction 或 create_transactions 录入 → 把每笔的编号、金额与手续费列给我"
        "（写错了用 undo_change_set 撤销）。",
    ),
    "monthly_review": (
        "月度复盘",
        [("month", "月份，如 2026-10", True)],
        "请复盘 {month}：list_pending_work 逐项处理（不确定的先问我）→ run_report 的 summary、operations、sales、"
        "credit_purchases 汇总给我，并与上月对比 → run_checks 确认账本完好。",
    ),
    "fix_fee_rule": (
        "修正手续费规则",
        [("rule", "规则代码或渠道", True), ("rate", "新费率，如 0.025", True), ("valid_from", "生效日", True)],
        "手续费规则 {rule} 自 {valid_from} 起改为 {rate}：manage_fee_rule(action=save) 保存新版本 → "
        "repost_transactions(dry_run=true) 列出受影响交易与差额给我确认 → 确认后执行。",
    ),
    "investigate_difference": (
        "查找差异",
        [("target", "科目或报表项目", True), ("expected", "期望金额", True)],
        "{target} 的金额应为 {expected}，请查明差异：run_report / query_ledger 定位期间与维度 → "
        "search_transactions 按 drilldown 列出明细 → 找出遗漏、重复或错误的交易并给出修改建议（不要直接修改）。",
    ),
}


def prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name=name,
            title=title,
            arguments=[types.PromptArgument(name=a, description=d, required=r) for a, d, r in args],
        )
        for name, (title, args, _text) in PROMPTS.items()
    ]


def get_prompt(name: str, arguments: dict[str, str]) -> types.GetPromptResult:
    if name not in PROMPTS:
        raise DomainError("NOT_FOUND", f"提示词 {name} 不存在。")
    title, args, template = PROMPTS[name]
    missing = [a for a, _d, required in args if required and not arguments.get(a)]
    if missing:
        raise DomainError("VALIDATION_FAILED", f"缺少参数：{', '.join(missing)}。")
    text = template.format(**{a: arguments.get(a, "") for a, _d, _r in args})
    return types.GetPromptResult(
        description=title,
        messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))],
    )
