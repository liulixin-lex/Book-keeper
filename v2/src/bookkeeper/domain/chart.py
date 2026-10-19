"""Default chart of accounts, channels and transaction types (docs/14-taxonomy-and-copy.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass

CLASSIFICATIONS = ("asset", "liability", "equity", "revenue", "expense")
NORMAL_SIDE = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "revenue": "credit",
}
ROLES = frozenset(
    {
        "funds",
        "receivable",
        "other_receivable",
        "prepaid",
        "payable",
        "advance_received",
        "other_payable",
        "equity_capital",
        "current_year_profit",
        "retained_earnings",
        "trading",
        "opening_balance",
        "suspense",
        "revenue_operating",
        "revenue_other",
        "non_operating_income",
        "cost_operating",
        "expense_selling",
        "expense_admin",
        "expense_finance_fee",
        "fx_gain_loss",
        "interest",
        "rounding",
        "non_operating_expense",
        "income_tax",
    }
)
SYSTEM_ROLES = frozenset(
    {
        "trading",
        "opening_balance",
        "suspense",
        "current_year_profit",
        "retained_earnings",
        "fx_gain_loss",
        "rounding",
    }
)
CODE_RE = re.compile(r"^\d{4}(\.\d{2})*$")


def parent_code(code: str) -> str | None:
    head, sep, _ = code.rpartition(".")
    return head if sep else None


def code_level(code: str) -> int:
    return code.count(".") + 1


@dataclass(frozen=True)
class ChartAccount:
    code: str
    name: str
    classification: str
    role: str | None = None
    is_group: bool = False
    is_system: bool = False
    manual_entry_allowed: bool = True
    description: str | None = None

    @property
    def normal_side(self) -> str:
        return NORMAL_SIDE[self.classification]

    @property
    def standard_code(self) -> str:
        return self.code.split(".")[0]


def _a(code: str, name: str, cls: str, role: str | None = None, **kw: object) -> ChartAccount:
    return ChartAccount(code, name, cls, role, **kw)  # type: ignore[arg-type]


SMALL_ENTERPRISE_V1: tuple[ChartAccount, ...] = (
    _a("1012", "其他货币资金", "asset", is_group=True),
    _a(
        "1012.01",
        "资金账户",
        "asset",
        "funds",
        description="微信、支付宝、银行卡、平台余额统一记入；允许多币种",
    ),
    _a("1122", "应收账款", "asset", "receivable"),
    _a("1123", "预付账款", "asset", "prepaid"),
    _a("1221", "其他应收款", "asset", "other_receivable"),
    _a(
        "1999",
        "待核对款项",
        "asset",
        "suspense",
        is_system=True,
        description="去向待确认的金额；归类后应回到 0",
    ),
    _a("2202", "应付账款", "liability", "payable"),
    _a("2203", "预收账款", "liability", "advance_received"),
    _a("2241", "其他应付款", "liability", "other_payable"),
    _a("3001", "实收资本", "equity", "equity_capital"),
    _a("3103", "本年利润", "equity", "current_year_profit", is_system=True, manual_entry_allowed=False),
    _a("3104", "利润分配", "equity", "retained_earnings", is_system=True),
    _a(
        "3901",
        "货币兑换",
        "equity",
        "trading",
        is_system=True,
        manual_entry_allowed=False,
        description="跨币种交易的兑换腿",
    ),
    _a("3902", "期初余额调整", "equity", "opening_balance", is_system=True),
    _a("5001", "主营业务收入", "revenue", is_group=True),
    _a("5001.01", "API 额度销售", "revenue", "revenue_operating"),
    _a("5051", "其他业务收入", "revenue", "revenue_other"),
    _a("5301", "营业外收入", "revenue", "non_operating_income"),
    _a("5401", "主营业务成本", "expense", is_group=True),
    _a("5401.01", "上游额度", "expense", "cost_operating", description="面值部分；记额度数量"),
    _a("5401.02", "账号", "expense", "cost_operating"),
    _a("5401.03", "AI 服务订阅", "expense", "cost_operating"),
    _a("5401.04", "服务器与网络", "expense", "cost_operating"),
    _a("5601", "销售费用", "expense", is_group=True),
    _a("5601.01", "广告推广费", "expense", "expense_selling"),
    _a("5602", "管理费用", "expense", is_group=True),
    _a("5602.01", "注册与办公费", "expense", "expense_admin"),
    _a("5602.02", "软件与工具费", "expense", "expense_admin"),
    _a("5602.99", "其他管理费用", "expense", "expense_admin"),
    _a("5603", "财务费用", "expense", is_group=True),
    _a("5603.01", "手续费", "expense", "expense_finance_fee"),
    _a("5603.02", "汇兑损益", "expense", "fx_gain_loss", is_system=True, manual_entry_allowed=False),
    _a("5603.03", "利息收支", "expense", "interest"),
    _a("5603.09", "尾差", "expense", "rounding", is_system=True, manual_entry_allowed=False),
    _a("5711", "营业外支出", "expense", "non_operating_expense"),
)

CHART_TEMPLATES: dict[str, tuple[ChartAccount, ...]] = {"small_enterprise_v1": SMALL_ENTERPRISE_V1}

CHANNELS: tuple[tuple[str, str], ...] = (
    ("liandong", "链动"),
    ("yunmao", "云猫"),
    ("k16888", "16888"),
    ("stripe", "Stripe"),
    ("xorpay", "XorPay"),
    ("site_shop", "站内商店"),
    ("direct", "官网直付"),
    ("other", "其他"),
)
# Common longer spellings accepted wherever a channel is named (doc 14 §6 keeps names short).
CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "liandong": ("链动小铺",),
    "yunmao": ("云猫寄售",),
    "site_shop": ("站内",),
    "direct": ("官网",),
}


@dataclass(frozen=True)
class TransactionTypeDef:
    code: str
    name: str
    category: str
    description: str


TRANSACTION_TYPES: tuple[TransactionTypeDef, ...] = (
    TransactionTypeDef("sale", "销售收入", "income", "经销售渠道收到的 API 额度销售款；渠道扣除的手续费单独入账"),
    TransactionTypeDef("sale_refund", "销售退款", "income", "退还客户款项，关联原销售"),
    TransactionTypeDef("credit_purchase", "额度采购", "expense", "向上游站点购买 API 额度，付款即计成本"),
    TransactionTypeDef("expense", "费用支出", "expense", "额度采购以外的所有支出，按收支分类入账"),
    TransactionTypeDef("purchase_refund", "采购退款", "expense", "供应商退款，关联原采购或支出"),
    TransactionTypeDef("transfer", "资金划转", "transfer", "资金在科目或币种之间转移（含结汇、换汇），不影响损益"),
    TransactionTypeDef("opening_balance", "期初余额", "adjustment", "建账时录入期初余额"),
    TransactionTypeDef("manual_journal", "手工凭证", "adjustment", "其他调整事项，直接录入分录行"),
)
LINE_INPUT_TYPES = frozenset({"manual_journal", "opening_balance"})
