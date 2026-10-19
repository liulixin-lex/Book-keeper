"""Request models shared by REST endpoints and MCP tools (one schema, two interfaces)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.services.transactions import LineSpec


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoneyIn(Strict):
    amount: str = Field(description='字符串小数，如 "51.50"；不接受浮点数')
    commodity: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,11}$")


class LineIn(Strict):
    account: str = Field(description="科目编码或 ID")
    side: Literal["debit", "credit"]
    amount: MoneyIn
    fx_rate: str | None = None
    base_amount: str | None = Field(default=None, description="本位币金额（实际折算值），给出时优先于汇率")
    counterparty: str | None = None
    counterparty_account: str | None = None
    dimensions: dict[str, str] | None = Field(default=None, description="{维度类型代码: 维度值代码}")
    memo: str | None = Field(default=None, max_length=200)
    quantity: str | None = None
    quantity_unit: str | None = Field(default=None, max_length=12)


class TransactionIn(Strict):
    type: str | None = Field(
        default=None,
        description="交易类型代码；业务类型用 inputs，手工凭证 / 期初余额用 lines（见 GET transaction-types）。"
        "省略时用往来方的默认交易类型",
    )
    effective_date: date | None = None
    occurred_at: datetime | None = None
    date_precision: Literal["timestamp", "day", "month"] | None = None
    description: str | None = Field(default=None, max_length=200)
    counterparty: str | None = None
    external_ref: str | None = Field(default=None, max_length=200)
    order_no: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)
    inputs: dict[str, Any] | None = Field(default=None, description="业务类型的输入，结构见该类型的 input_schema")
    lines: list[LineIn] | None = Field(default=None, min_length=1, max_length=200)
    allow_conversion: bool = False
    journal_code: str | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] = Field(
        default_factory=list, max_length=20, description="标签（活动、项目、待报销等），不存在则自动创建"
    )


class TransactionPatch(Strict):
    expected_version: int | None = Field(default=None, description="读取时的 version；给出时可防止覆盖别人的修改")
    effective_date: date | None = None
    occurred_at: datetime | None = None
    date_precision: Literal["timestamp", "day", "month"] | None = None
    description: str | None = Field(default=None, max_length=200)
    counterparty: str | None = None
    external_ref: str | None = None
    order_no: str | None = None
    notes: str | None = None
    inputs: dict[str, Any] | None = Field(default=None, description="部分修改：只需给出要改的键，值为 null 表示删除")
    lines: list[LineIn] | None = None
    allow_conversion: bool | None = None
    journal_code: str | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = Field(default=None, max_length=20, description="整体替换标签")


class RepostIn(Strict):
    reason: str = Field(min_length=2, max_length=200, description="重算原因，如“Stripe 费率调整”")
    ids: list[str] = Field(default_factory=list, max_length=1000, description="交易 ID 或编号")
    types: list[Literal["sale", "credit_purchase", "expense", "transfer", "sale_refund"]] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list, description="渠道代码")
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=500, ge=1, le=2000)


class BatchIn(Strict):
    items: list[TransactionIn] = Field(min_length=1, max_length=200)
    atomic: bool = Field(default=True, description="true：任一失败则全部不入账；false：逐条提交并返回各自结果")


TXN_REF = "交易编号（如 T2026-000123）或 ID"


class EditArgs(TransactionPatch):
    ref: str = Field(description=TXN_REF)


class DeleteIn(Strict):
    reason: str | None = Field(default=None, max_length=200, description="可选：删除原因")
    expected_version: int | None = None


class DeleteArgs(DeleteIn):
    ref: str = Field(description=TXN_REF)


class RestoreIn(Strict):
    expected_version: int | None = None


class RestoreArgs(RestoreIn):
    ref: str = Field(description=TXN_REF)


class UndoIn(Strict):
    change_set_id: str = Field(description="要撤销的变更集 ID（写入回执的 meta.change_set_id）")
    reason: str | None = Field(default=None, max_length=200, description="可选：撤销原因")


def line_specs(lines: list[LineIn] | None) -> list[LineSpec] | None:
    if lines is None:
        return None
    return [
        LineSpec(
            account=line.account,
            side=line.side,
            amount=line.amount.amount,
            commodity=line.amount.commodity,
            fx_rate=line.fx_rate,
            base_amount=line.base_amount,
            counterparty=line.counterparty,
            counterparty_account=line.counterparty_account,
            dimensions=line.dimensions,
            memo=line.memo,
            quantity=line.quantity,
            quantity_unit=line.quantity_unit,
        )
        for line in lines
    ]


class FeeRuleIn(Strict):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,47}$", description="规则代码；同代码再次提交 = 新版本")
    name: str | None = Field(default=None, max_length=60)
    rate: str | None = Field(default=None, description='比例，如 "0.03" 表示 3%')
    fixed: str | None = Field(default=None, description='每笔固定额，如 "0.30"')
    min: str | None = Field(default=None, description="每笔下限")
    max: str | None = Field(default=None, description="每笔上限")
    commodity: str | None = Field(default=None, description="fixed / min / max 的币种；只按比例时可省略")
    transaction_types: list[Literal["sale", "credit_purchase", "expense", "transfer", "sale_refund"]] = Field(
        default_factory=list,
        description="适用的交易类型；留空 = 销售收入与额度采购（费用支出、资金划转、销售退款须明确列出）",
    )
    channels: list[str] = Field(default_factory=list, description="渠道代码；空 = 所有渠道")
    counterparties: list[str] = Field(default_factory=list, description="往来方名称或 ID；空 = 所有")
    priority: int = Field(default=0, ge=-100, le=100)
    valid_from: date
    is_estimate: bool = Field(default=False, description="按此规则计算的手续费标记为估算，待实际到账核对")
    note: str | None = Field(default=None, max_length=200)


def create_data(body: TransactionIn) -> dict[str, Any]:
    """TransactionIn → the dict ``transactions.create`` expects."""
    data = body.model_dump(exclude={"lines"})
    data["lines"] = line_specs(body.lines)
    return data


def change_data(body: BaseModel, exclude: set[str] | None = None) -> dict[str, Any]:
    """A patch-like model → changes dict (only fields that were sent; lines converted)."""
    changes = body.model_dump(exclude_unset=True, exclude={"lines", *(exclude or set())})
    lines = getattr(body, "lines", None)
    if lines is not None:
        changes["lines"] = line_specs(lines)
    return changes


# ------------------------------------------------------------------ M4: import, rules


class SourceIn(Strict):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,47}$", description="来源代码，如 wechat、ld_orders、relay_log")
    name: str | None = Field(default=None, max_length=60)
    kind: Literal[
        "wechat_bill",
        "alipay_bill",
        "stripe_balance",
        "card_shop_orders",
        "upstream_usage_log",
        "generic_tabular",
        "records",
        "redeem_page",
        "ai_extract",
    ] = Field(
        description="redeem_page：中转站兑换码页面打印的 PDF；ai_extract：截图与 PDF 由 AI 读取（服务器需配置密钥）"
    )
    timezone: str = "Asia/Shanghai"
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="defaults（按方向 in / out / neutral 给出 type、channel、category、counterparty…）、"
        "unclassified_policy（leave / suspense）、match（匹配窗口与容差）、"
        "credit_rate（额度换算本位币，默认 1）、列映射 columns / wide、shop、counterparty；"
        "ai_extract 另有 hint（告诉 AI 这是什么页面）与 commodity（如 UCR：金额是站内额度）",
    )


class SourcePatch(Strict):
    expected_version: int
    name: str | None = None
    timezone: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class RecordIn(Strict):
    occurred_at: str = Field(description="发生时间，ISO 格式；无时区时按来源时区")
    direction: Literal["in", "out", "neutral"]
    amount: str = Field(description='正数字符串，如 "51.50"')
    commodity: str = "CNY"
    external_id: str | None = Field(default=None, description="来源内唯一号（订单号、流水号），用于去重")
    fee: str | None = None
    balance_after: str | None = None
    counterparty: str | None = None
    description: str | None = None
    order_no: str | None = None
    reference: str | None = None
    status: str | None = None
    extracted: dict[str, Any] | None = Field(
        default=None, description="补充字段：face（面值）、quantity、credits（额度数量）、account、code（会被摘要化）…"
    )


class BatchCreateIn(Strict):
    source: str = Field(description="来源代码或 ID")
    records: list[RecordIn] | None = Field(
        default=None, max_length=20000, description="结构化记录（与 file_id 二选一）"
    )
    file_id: str | None = Field(default=None, description="已上传文件的 ID")
    note: str | None = Field(default=None, max_length=200)


class CommitImportIn(Strict):
    batch_id: str
    accept_row_errors: bool = Field(default=False, description="个别行无法解析时仍提交其余行")
    exclude: list[str] = Field(default_factory=list, description="不提交的记录 ID")


class RevertImportIn(Strict):
    batch_id: str
    reason: str | None = Field(default=None, max_length=200, description="可选：撤销原因")


class ClassifyIn(Strict):
    type: str | None = None
    counterparty: str | None = None
    description: str | None = None
    inputs: dict[str, Any] | None = Field(default=None, description="只需给出要设置的键，null 删除")


class RuleIn(Strict):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,47}$")
    name: str | None = Field(default=None, max_length=80)
    stage: Literal["normalize", "classify", "enrich"] = "classify"
    priority: int = Field(default=100, ge=0, le=1000)
    condition: dict[str, Any] = Field(
        description='条件 AST：{"all":[…]} / {"any":[…]} / {"not":…} / '
        '{"field":"description","op":"regex","value":"(?P<face>\\\\d+)R"}'
    )
    actions: list[dict[str, Any]] = Field(
        description='动作：{"type":"set_transaction_type","value":"credit_purchase"}、{"type":"set_counterparty","value":"relay-b.example"}、'
        '{"type":"set_input","name":"face","value":{"amount":"{captures.face}","commodity":"CNY"}}、set_channel、set_category、'
        "set_fee、set_description、ignore（reason）"
    )
    stop_processing: bool = False
    is_active: bool = True
    note: str | None = Field(default=None, max_length=200)


class ApplyRulesIn(Strict):
    batch_id: str | None = None
    record_ids: list[str] | None = Field(default=None, max_length=20000)


class PairingRuleIn(Strict):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,47}$")
    name: str | None = None
    is_active: bool = True
    config: dict[str, Any] = Field(
        description='{"left":{"sources":["ld_orders"]},"right":{"sources":["relay_log"]},'
        '"left_keys":["counterparty","extracted.face"],"right_keys":["counterparty","extracted.face"],'
        '"window_minutes":{"before":10,"after":4320},"penalty_minutes":4320,"auto_accept_max_gap_minutes":30}'
    )
