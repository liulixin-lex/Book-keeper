from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class CommandEffect(StrEnum):
    READ = "read"
    PROPOSE = "propose"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    command: str
    label: str
    description: str
    effect: CommandEffect
    plugin_id: str
    starts_workflow: bool = False

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


COMMANDS: tuple[CommandDefinition, ...] = (
    CommandDefinition(
        "/录入收入",
        "录入收入",
        "收集资料并生成收入提案",
        CommandEffect.PROPOSE,
        "ledger.income-entry",
        True,
    ),
    CommandDefinition(
        "/录入支出",
        "录入支出",
        "收集资料并生成支出提案",
        CommandEffect.PROPOSE,
        "ledger.expense-entry",
        True,
    ),
    CommandDefinition(
        "/批量录入",
        "批量录入",
        "从表格或附件生成原子批次提案",
        CommandEffect.PROPOSE,
        "ledger.batch-entry",
        True,
    ),
    CommandDefinition(
        "/删除收入",
        "删除收入",
        "取消未提交提案或生成已过账收入的冲正提案",
        CommandEffect.PROPOSE,
        "ledger.lifecycle",
        True,
    ),
    CommandDefinition(
        "/删除支出",
        "删除支出",
        "取消未提交提案或生成已过账支出的冲正提案",
        CommandEffect.PROPOSE,
        "ledger.lifecycle",
        True,
    ),
    CommandDefinition(
        "/冲正",
        "冲正",
        "预览原记录与反向分录，确认后进入审批",
        CommandEffect.PROPOSE,
        "ledger.lifecycle",
        True,
    ),
    CommandDefinition(
        "/修改草稿",
        "修改草稿",
        "修改服务端提案",
        CommandEffect.CONTROL,
        "ledger.income-entry",
    ),
    CommandDefinition(
        "/分类",
        "分类",
        "修改提案分类",
        CommandEffect.CONTROL,
        "ledger.expense-entry",
    ),
    CommandDefinition(
        "/补充", "补充资料", "继续补充当前工作流资料", CommandEffect.CONTROL, "ledger.batch-entry"
    ),
    CommandDefinition(
        "/预览", "预览", "查看提案、金额关系和预计分录", CommandEffect.CONTROL, "ledger.query"
    ),
    CommandDefinition(
        "/查重",
        "查重",
        "对当前提案执行精确键和业务指纹检查",
        CommandEffect.CONTROL,
        "ledger.duplicate-check",
    ),
    CommandDefinition(
        "/确认", "确认", "确认已冻结快照并提交", CommandEffect.CONTROL, "ledger.lifecycle"
    ),
    CommandDefinition("/取消", "取消", "取消当前工作流", CommandEffect.CONTROL, "ledger.lifecycle"),
    CommandDefinition("/状态", "状态", "查看当前工作流状态", CommandEffect.CONTROL, "ledger.query"),
    CommandDefinition(
        "/查询账单", "查询账单", "只读查询账务记录", CommandEffect.READ, "ledger.query"
    ),
    CommandDefinition("/汇总", "汇总", "只读汇总账务数据", CommandEffect.READ, "ledger.query"),
    CommandDefinition("/帮助", "帮助", "查看可用命令", CommandEffect.READ, "ledger.query"),
)

COMMAND_INDEX = {item.command: item for item in COMMANDS}


def parse_command(value: str) -> tuple[CommandDefinition | None, str]:
    normalized = value.strip()
    if not normalized.startswith("/"):
        return None, normalized
    token, separator, rest = normalized.partition(" ")
    command = COMMAND_INDEX.get(token)
    if command is None:
        return None, normalized
    return command, rest.strip() if separator else ""


def is_write_intent(value: str) -> bool:
    if value.lstrip().startswith("/"):
        return False
    keywords = ("录入", "记一笔", "记账", "新增收入", "新增支出", "删除账单", "冲正")
    return any(keyword in value for keyword in keywords)
