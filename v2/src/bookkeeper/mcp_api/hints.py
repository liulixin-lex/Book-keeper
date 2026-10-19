"""Tool groups, examples and next steps (docs/09 §5): what a client reads in each tool's description.

Groups let a client look at one part of the toolset at a time (get_context lists them with the tools the caller
may use); each example is a valid call (a test checks it against the tool's schema); the next step says what
usually follows. Shared by MCP and the in-app assistant, which get the same descriptions.
"""

from __future__ import annotations

import json
from typing import Any

GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "开始": ("先了解账套、权限与待处理事项", ("get_context", "list_pending_work")),
    "查询与报表": (
        "查交易、余额、报表与规则命中，不写入",
        (
            "search_transactions",
            "get_transaction",
            "get_balances",
            "run_report",
            "query_ledger",
            "explain_posting",
            "evaluate_fee",
            "search_accounts",
            "search_counterparties",
            "get_reference",
            "run_checks",
            "export_ledger",
        ),
    ),
    "记账": (
        "记账、修改、删除、恢复、按新规则重算、整次撤销",
        (
            "create_transaction",
            "create_transactions",
            "update_transaction",
            "delete_transaction",
            "restore_transaction",
            "repost_transactions",
            "undo_change_set",
        ),
    ),
    "导入": (
        "账单与截图导入：暂存、分类、匹配、完成或撤销",
        (
            "manage_import_source",
            "import_records",
            "get_import_batch",
            "search_source_records",
            "classify_records",
            "resolve_match",
            "apply_rules",
            "commit_import",
            "revert_import",
        ),
    ),
    "规则与基础资料": (
        "往来方、渠道、分类规则、配对规则、手续费规则",
        ("upsert_reference", "manage_rule", "save_rule_from_record", "manage_pairing_rule", "manage_fee_rule"),
    ),
    "文件": ("读上传的原件（只读），在工作区写派生文件", ("list_files", "read_file", "write_file", "patch_file")),
    "管理": ("审计记录与管理信息（不含密钥）", ("get_audit_trail", "get_admin_info")),
}
GROUP_OF = {tool: group for group, (_purpose, tools) in GROUPS.items() for tool in tools}

_PURCHASE = {
    "type": "credit_purchase",
    "effective_date": "2026-10-18",
    "counterparty": "api.example.com",
    "inputs": {"face": {"amount": "50", "commodity": "CNY"}, "total": {"amount": "51.50", "commodity": "CNY"}},
}
# tool → (an example call, what usually comes next)
HINTS: dict[str, tuple[dict[str, Any], str]] = {
    "get_context": ({}, "按任务看 tool_groups 里相关的一组；有待处理事项时 list_pending_work"),
    "list_pending_work": ({"kinds": [], "limit": 20}, "每项附建议的工具，按它处理"),
    "search_transactions": (
        {"counterparty": "api.example.com", "date_from": "2026-10-01", "date_to": "2026-10-31"},
        "get_transaction 看单笔；要改用 update_transaction",
    ),
    "get_transaction": ({"ref": "T2026-000123", "explain": True}, "update_transaction / delete_transaction"),
    "get_balances": ({"as_of": "2026-10-31"}, "run_report(summary) 看利润与资金"),
    "run_report": (
        {"report": "summary", "date_from": "2026-10-01", "date_to": "2026-10-31"},
        "行里的 drilldown 直接给 search_transactions；拆维度用 query_ledger",
    ),
    "query_ledger": (
        {"date_from": "2026-10-01", "date_to": "2026-10-31", "group_by": ["channel"]},
        "search_transactions 看明细",
    ),
    "explain_posting": ({"ref": "T2026-000123"}, "手续费不对时 evaluate_fee 或检查手续费规则"),
    "evaluate_fee": (
        {"type": "credit_purchase", "amount": "50", "on": "2026-10-18", "counterparty": "api.example.com"},
        "结果不对时 manage_fee_rule 修正规则",
    ),
    "search_accounts": ({"query": "服务器"}, "记费用支出时把编码填进 inputs.category"),
    "search_counterparties": ({"query": "https://api.example.com/v1"}, "没有就 upsert_reference 新建"),
    "get_reference": (
        {"kind": "transaction_type", "code": "credit_purchase"},
        "照 input_schema 组织 create_transaction",
    ),
    "run_checks": ({}, "没通过的检查按 next_action 处理"),
    "export_ledger": (
        {"format": "xlsx", "date_from": "2026-10-01", "date_to": "2026-10-31"},
        "把下载链接给用户",
    ),
    "create_transaction": (_PURCHASE | {"dry_run": True}, "确认试算后去掉 dry_run 再提交；写错用 undo_change_set"),
    "create_transactions": ({"items": [_PURCHASE], "atomic": True}, "回执列出每笔编号；失败的单独修正后重提"),
    "update_transaction": (
        {"ref": "T2026-000123", "expected_version": 1, "inputs": {"total": {"amount": "52.00", "commodity": "CNY"}}},
        "get_transaction 复核",
    ),
    "delete_transaction": ({"ref": "T2026-000123", "reason": "重复记账"}, "误删用 restore_transaction"),
    "restore_transaction": ({"ref": "T2026-000123"}, "get_transaction 复核"),
    "repost_transactions": (
        {"reason": "手续费规则调整", "date_from": "2026-10-01", "dry_run": True},
        "确认差额后去掉 dry_run 执行",
    ),
    "undo_change_set": ({"change_set_id": "chs_01J…", "reason": "AI 写错"}, "manual 里的项人工处理"),
    "manage_import_source": ({"action": "list"}, "没有合适的来源时 action=create"),
    "import_records": (
        {
            "source": "relay_log",
            "records": [
                {"occurred_at": "2026-10-18T10:00:00", "direction": "in", "amount": "50", "external_id": "R-1"}
            ],
        },
        "get_import_batch 查看分类与匹配结果",
    ),
    "get_import_batch": ({"batch_id": "imb_01J…"}, "缺字段的用 classify_records 补全，确认后 commit_import"),
    "search_source_records": ({"status": "new", "limit": 20}, "classify_records 补全"),
    "classify_records": (
        {"record_ids": ["srec_01J…"], "set": {"type": "expense", "inputs": {"category": "5401.04"}}},
        "以后同类也这样分：save_rule_from_record",
    ),
    "resolve_match": ({"decisions": [{"suggestion_id": "mts_01J…", "accept": True}]}, "commit_import"),
    "apply_rules": ({"batch_id": "imb_01J…"}, "get_import_batch 复查"),
    "commit_import": ({"batch_id": "imb_01J…"}, "回执给出入账笔数；整批撤回用 revert_import"),
    "revert_import": ({"batch_id": "imb_01J…", "reason": "导错文件"}, "重新 import_records"),
    "upsert_reference": (
        {
            "kind": "counterparty",
            "fields": {"name": "api.example.com", "category": "upstream_site", "domains": ["api.example.com"]},
        },
        "需要手续费时 manage_fee_rule",
    ),
    "manage_rule": ({"action": "list"}, "改规则后 apply_rules 重新分类未入账记录"),
    "save_rule_from_record": ({"record_id": "srec_01J…"}, "get_import_batch 复查同批记录"),
    "manage_pairing_rule": ({"action": "list"}, "保存后对新的导入生效"),
    "manage_fee_rule": (
        {
            "action": "save",
            "rule": {
                "code": "site-example",
                "rate": "0.03",
                "counterparties": ["api.example.com"],
                "valid_from": "2026-10-01",
            },
            "dry_run": True,
        },
        "evaluate_fee 试算；追溯旧交易用 repost_transactions",
    ),
    "list_files": ({"kind": "evidence", "limit": 10}, "read_file 读内容"),
    "read_file": ({"file_id": "fil_01J…"}, "抄写成记录后 import_records；派生内容 write_file"),
    "write_file": ({"path": "notes/10月对账.md", "content": "# 10 月对账\n"}, "改一处用 patch_file"),
    "patch_file": ({"path": "notes/10月对账.md", "old": "待核", "new": "已核"}, "read_file 复核"),
    "get_audit_trail": ({"view": "change_sets", "channel": "agent", "limit": 10}, "撤销整次写入：undo_change_set"),
    "get_admin_info": ({"kind": "ai"}, "修改请到网页端设置"),
}


def describe(name: str, description: str) -> str:
    """The tool's description with its example call and next step."""
    hint = HINTS.get(name)
    if hint is None:
        return description
    example, following = hint
    return f"{description}\n例：{json.dumps(example, ensure_ascii=False)}\n下一步：{following}"


def tool_groups(usable: set[str]) -> list[dict[str, Any]]:
    """The groups with the tools this caller may use (empty groups left out)."""
    out = []
    for group, (purpose, tools) in GROUPS.items():
        mine = [t for t in tools if t in usable]
        if mine:
            out.append({"group": group, "purpose": purpose, "tools": mine})
    return out
