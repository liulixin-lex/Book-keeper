"""Display labels for enums (docs/14-taxonomy-and-copy.md §10.1). Single source for UI and MCP."""

from __future__ import annotations

from bookkeeper.domain.scopes import TIER_TEXT

ENUM_LABELS: dict[str, dict[str, str]] = {
    "transaction_status": {"posted": "已入账", "reversed": "已删除"},
    "entry_kind": {
        "posting": "入账",
        "reversal": "删除冲销",
        "repost_reversal": "修改冲销",
        "repost": "修改入账",
        "adjustment": "调整",
    },
    "source_record_status": {
        "new": "待处理",
        "classified": "已分类",
        "matched": "已匹配",
        "booked": "已入账",
        "ignored": "已忽略",
        "duplicate": "重复",
    },
    "import_batch_status": {
        "extracting": "识别中",
        "failed": "识别失败",
        "parsed": "待完成",
        "committed": "已完成",
        "reverted": "已撤销",
    },
    "match_status": {
        "pending": "待确认",
        "accepted": "已接受",
        "auto_accepted": "自动接受",
        "rejected": "已拒绝",
        "superseded": "已被替代",
    },
    "check_severity": {"error": "错误", "warning": "警告", "info": "提示"},
    "created_channel": {
        "ui": "界面",
        "api": "API",
        "mcp": "MCP",
        "import": "导入",
        "system": "系统",
        "migration": "迁移",
        "cli": "命令行",
    },
    "role": {"viewer": "只读", "accountant": "记账员", "admin": "管理员", "owner": "所有者"},
    "token_tier": {tier.value: text[0] for tier, text in TIER_TEXT.items()},
    "token_tier_hint": {tier.value: text[1] for tier, text in TIER_TEXT.items()},
    "line_role": {
        "manual": "手工",
        "gross": "毛额",
        "net": "到账",
        "fee": "手续费",
        "cost": "成本",
        "pay": "付款",
        "out": "转出",
        "in": "转入",
        "trading": "货币兑换",
        "fx_realization": "汇兑损益",
        "rounding": "尾差",
        "opening_offset": "期初调整",
    },
    "account_classification": {
        "asset": "资产",
        "liability": "负债",
        "equity": "权益",
        "revenue": "收入",
        "expense": "费用",
    },
    "transaction_link": {"refund_of": "退款", "related": "关联"},
    "job_status": {
        "queued": "排队中",
        "running": "执行中",
        "succeeded": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
    },
}
