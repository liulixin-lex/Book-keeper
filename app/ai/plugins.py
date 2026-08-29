from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    api_version: str = "1"
    commands: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: tuple[str, ...]
    data_scope: tuple[str, ...]
    effect: Literal["read", "propose"]
    approval_policy: Literal["none", "user_confirmation", "admin_approval"]
    idempotent: bool
    timeout_seconds: int = Field(ge=1, le=600)
    config_schema: dict[str, Any]
    core: bool = False


EMPTY_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
PROPOSAL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"proposal_ids": {"type": "array", "items": {"type": "string"}}},
    "required": ["proposal_ids"],
    "additionalProperties": False,
}


def _manifest(
    plugin_id: str,
    name: str,
    commands: tuple[str, ...],
    *,
    effect: Literal["read", "propose"],
    permissions: tuple[str, ...],
    data_scope: tuple[str, ...],
    approval_policy: Literal["none", "user_confirmation", "admin_approval"] = "none",
    core: bool = False,
) -> PluginManifest:
    return PluginManifest(
        id=plugin_id,
        name=name,
        version="1.0.0",
        commands=commands,
        input_schema=EMPTY_OBJECT_SCHEMA,
        output_schema=PROPOSAL_OUTPUT_SCHEMA if effect == "propose" else EMPTY_OBJECT_SCHEMA,
        permissions=permissions,
        data_scope=data_scope,
        effect=effect,
        approval_policy=approval_policy,
        idempotent=True,
        timeout_seconds=120,
        config_schema=EMPTY_OBJECT_SCHEMA,
        core=core,
    )


BUILTIN_PLUGINS: tuple[PluginManifest, ...] = (
    _manifest(
        "ledger.query",
        "账本查询",
        ("/查询账单", "/汇总", "/预览", "/状态", "/帮助"),
        effect="read",
        permissions=("ledger.read",),
        data_scope=("records", "journal", "master_data"),
        core=True,
    ),
    _manifest(
        "ledger.income-entry",
        "收入录入",
        ("/录入收入", "/修改草稿"),
        effect="propose",
        permissions=("ledger.propose",),
        data_scope=("categories", "providers", "fx_rates"),
        approval_policy="user_confirmation",
        core=True,
    ),
    _manifest(
        "ledger.expense-entry",
        "支出录入",
        ("/录入支出", "/分类"),
        effect="propose",
        permissions=("ledger.propose",),
        data_scope=("categories", "providers", "fx_rates"),
        approval_policy="user_confirmation",
        core=True,
    ),
    _manifest(
        "ledger.batch-entry",
        "批量录入",
        ("/批量录入", "/补充"),
        effect="propose",
        permissions=("ledger.propose",),
        data_scope=("document_extractions", "master_data"),
        approval_policy="user_confirmation",
    ),
    _manifest(
        "ledger.duplicate-check",
        "交易查重",
        ("/查重",),
        effect="read",
        permissions=("ledger.read",),
        data_scope=("records",),
        core=True,
    ),
    _manifest(
        "ledger.lifecycle",
        "删除与冲正",
        ("/删除收入", "/删除支出", "/冲正", "/确认", "/取消"),
        effect="propose",
        permissions=("ledger.propose",),
        data_scope=("records", "journal", "record_links"),
        approval_policy="admin_approval",
        core=True,
    ),
    _manifest(
        "ledger.document-extract",
        "附件提取",
        (),
        effect="read",
        permissions=("document.extract",),
        data_scope=("temporary_uploads",),
    ),
    _manifest(
        "ledger.knowledge-retrieve",
        "知识检索",
        (),
        effect="read",
        permissions=("knowledge.read",),
        data_scope=("authorized_business_domain",),
    ),
)

PLUGIN_INDEX = {plugin.id: plugin for plugin in BUILTIN_PLUGINS}


def plugin_for_command(command: str) -> PluginManifest:
    for plugin in BUILTIN_PLUGINS:
        if command in plugin.commands:
            return plugin
    raise KeyError(command)
