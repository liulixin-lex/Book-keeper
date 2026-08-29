from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.enums import AIMode


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    readonly: bool
    requires_approval: bool = False
    strict: bool = True


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


LEDGER_READONLY_TOOLS = (
    ToolDefinition(
        "get_overview",
        "读取指定日期范围的经营和现金概览。",
        _object_schema(
            {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "view": {"type": "string", "enum": ["operating", "cash", "both"]},
            },
            ["date_from", "date_to"],
        ),
        readonly=True,
    ),
    ToolDefinition(
        "list_records",
        "按业务字段筛选账务记录，不接受 SQL。",
        _object_schema(
            {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "record_type": {"type": "string"},
                "status": {"type": "string"},
                "category_id": {"type": "string"},
                "provider_id": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            }
        ),
        readonly=True,
    ),
    ToolDefinition(
        "summarize_ledger",
        "按日期、分类、提供商或渠道汇总账本数据。",
        _object_schema(
            {
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "group_by": {
                    "type": "string",
                    "enum": ["day", "month", "category", "provider", "channel"],
                },
            },
            ["date_from", "date_to", "group_by"],
        ),
        readonly=True,
    ),
    ToolDefinition(
        "get_trends",
        "读取收入、支出、经营净额或现金净额的时间趋势。",
        _object_schema(
            {
                "metric": {
                    "type": "string",
                    "enum": ["income", "expense", "operating_net", "cash_net"],
                },
                "date_from": {"type": "string", "format": "date"},
                "date_to": {"type": "string", "format": "date"},
                "interval": {"type": "string", "enum": ["day", "week", "month"]},
            },
            ["metric", "date_from", "date_to", "interval"],
        ),
        readonly=True,
    ),
    ToolDefinition(
        "get_record_source",
        "读取一条记录的来源凭据和定位信息。",
        _object_schema({"record_id": {"type": "string"}}, ["record_id"]),
        readonly=True,
    ),
)


LEDGER_EDIT_TOOLS = (
    ToolDefinition(
        "create_income",
        "创建收入草稿或普通收入记录。",
        _object_schema(
            {
                "accounting_date": {"type": "string", "format": "date"},
                "description": {"type": "string"},
                "currency": {"type": "string"},
                "gross": {"type": "string"},
                "fee": {"type": "string"},
                "net": {"type": "string"},
                "gross_cny": {"type": "string"},
                "fee_cny": {"type": "string"},
                "channel": {"type": "string"},
                "cash_received": {"type": "boolean"},
                "category_id": {"type": "string"},
                "provider_id": {"type": "string"},
                "external_id": {"type": "string"},
                "post": {"type": "boolean"},
            },
            ["accounting_date", "description", "currency", "gross"],
        ),
        readonly=False,
    ),
    ToolDefinition(
        "create_expense",
        "创建可扩展分类的支出草稿或普通支出记录。",
        _object_schema(
            {
                "accounting_date": {"type": "string", "format": "date"},
                "description": {"type": "string"},
                "currency": {"type": "string"},
                "cost": {"type": "string"},
                "cash": {"type": "string"},
                "cost_cny": {"type": "string"},
                "cash_cny": {"type": "string"},
                "category_id": {"type": "string"},
                "provider_id": {"type": "string"},
                "post": {"type": "boolean"},
            },
            ["accounting_date", "description", "currency", "cost"],
        ),
        readonly=False,
    ),
    ToolDefinition(
        "update_draft_record",
        "按版本号修改草稿记录。",
        _object_schema(
            {
                "record_id": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 1},
                "changes": {"type": "object"},
            },
            ["record_id", "expected_version", "changes"],
        ),
        readonly=False,
    ),
    ToolDefinition(
        "categorize_record",
        "为记录设置账务分类。",
        _object_schema(
            {
                "record_id": {"type": "string"},
                "category_id": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 1},
            },
            ["record_id", "category_id", "expected_version"],
        ),
        readonly=False,
    ),
    ToolDefinition(
        "reverse_posted_record",
        "请求冲正已过账记录；该操作必须进入审批。",
        _object_schema(
            {"record_id": {"type": "string"}, "reason": {"type": "string"}},
            ["record_id", "reason"],
        ),
        readonly=False,
        requires_approval=True,
    ),
)


def tools_for_mode(mode: AIMode) -> tuple[ToolDefinition, ...]:
    if mode == AIMode.CHAT:
        return LEDGER_READONLY_TOOLS
    return LEDGER_READONLY_TOOLS + LEDGER_EDIT_TOOLS


def canonical_tool_signature(name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"name": name, "arguments": arguments},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DomainToolExecutor(Protocol):
    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class UnconfiguredDomainToolExecutor:
    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        raise NotImplementedError(f"domain tool executor is not configured for {name}")
