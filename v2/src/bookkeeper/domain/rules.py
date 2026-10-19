"""Classification rules: a condition AST over record facts and actions that build the proposed
transaction (docs/06 §6). Pure — reference resolution and persistence live in the service layer."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bookkeeper.domain.errors import DomainError, FieldError

STAGES = ("normalize", "classify", "enrich")
OPS: dict[str, int] = {  # op → specificity weight
    "eq": 10,
    "ne": 10,
    "in": 9,
    "not_in": 9,
    "alias_of": 9,
    "approx": 5,
    "between": 5,
    "date_between": 5,
    "time_between": 5,
    "gt": 1,
    "gte": 1,
    "lt": 1,
    "lte": 1,
    "weekday_in": 1,
    "is_null": 1,
    "not_null": 1,
    "contains": 0,
    "not_contains": 0,
    "starts_with": 0,
    "ends_with": 0,
    "regex": 0,
}
FIELDS = (
    "source",
    "source_kind",
    "direction",
    "amount",
    "commodity",
    "fee_amount",
    "occurred_at",
    "effective_date",
    "time_of_day",
    "weekday",
    "counterparty_text",
    "counterparty",
    "description",
    "order_no",
    "reference",
    "status_text",
    "batch",
)
ACTIONS = (
    "set_transaction_type",
    "set_counterparty",
    "set_input",
    "unset_input",
    "set_channel",
    "set_category",
    "set_fee",
    "set_description",
    "ignore",
    "add_tag",
)
MAX_REGEX_INPUT = 2000


@dataclass(frozen=True)
class RuleDef:
    id: str
    code: str
    version: int
    stage: str
    priority: int
    condition: Mapping[str, Any]
    actions: Sequence[Mapping[str, Any]]
    stop_processing: bool = False

    @property
    def specificity(self) -> int:
        return specificity(self.condition)


@dataclass
class Outcome:
    classification: dict[str, Any]
    trace: list[dict[str, Any]] = field(default_factory=list)
    ignored: str | None = None
    matched_rules: list[str] = field(default_factory=list)


def norm(value: Any) -> str:
    """Full-width → half-width, lower case, no whitespace."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).lower()


def specificity(cond: Mapping[str, Any]) -> int:
    if "all" in cond:
        return sum(specificity(c) for c in cond["all"])
    if "any" in cond:
        return min((specificity(c) for c in cond["any"]), default=0)
    if "not" in cond:
        return specificity(cond["not"])
    return OPS.get(str(cond.get("op")), 0)


def validate_condition(cond: Any, path: str = "condition") -> None:
    errors: list[FieldError] = []
    _validate(cond, path, errors)
    if errors:
        raise DomainError("VALIDATION_FAILED", f"规则条件有误：{errors[0].path} {errors[0].message}。", errors=errors)


def _validate(cond: Any, path: str, errors: list[FieldError]) -> None:
    if not isinstance(cond, Mapping):
        errors.append(FieldError(path, "INPUT_INVALID", "必须是对象"))
        return
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        items = cond[key]
        if not isinstance(items, list) or not items:
            errors.append(FieldError(f"{path}.{key}", "INPUT_INVALID", "必须是非空数组"))
            return
        for i, item in enumerate(items):
            _validate(item, f"{path}.{key}.{i}", errors)
        return
    if "not" in cond:
        _validate(cond["not"], f"{path}.not", errors)
        return
    fld, op = cond.get("field"), cond.get("op")
    if not isinstance(fld, str) or not (fld in FIELDS or fld.startswith("extracted.")):
        errors.append(
            FieldError(f"{path}.field", "INPUT_INVALID", f"未知字段 {fld}；可用 {'、'.join(FIELDS)} 或 extracted.<键>")
        )
    if op not in OPS:
        errors.append(FieldError(f"{path}.op", "INPUT_INVALID", f"未知操作符 {op}；可用 {'、'.join(OPS)}"))
        return
    if op == "regex":
        try:
            re.compile(str(cond.get("value")))
        except re.error as exc:
            errors.append(FieldError(f"{path}.value", "INPUT_INVALID", f"正则错误：{exc}"))
    if op in ("in", "not_in", "weekday_in", "between", "date_between", "time_between") and not isinstance(
        cond.get("value"), list
    ):
        errors.append(FieldError(f"{path}.value", "INPUT_INVALID", f"{op} 的 value 必须是数组"))


def validate_actions(actions: Any, path: str = "actions") -> None:
    if not isinstance(actions, list) or not actions:
        raise DomainError("VALIDATION_FAILED", "规则至少需要一个动作。")
    for i, action in enumerate(actions):
        kind = action.get("type") if isinstance(action, Mapping) else None
        if kind not in ACTIONS:
            raise DomainError(
                "VALIDATION_FAILED",
                f"{path}.{i}：未知动作 {kind}；可用 {'、'.join(ACTIONS)}。",
                errors=[FieldError(f"{path}.{i}.type", "INPUT_INVALID", "未知动作")],
            )
        if kind in (
            "set_transaction_type",
            "set_counterparty",
            "set_channel",
            "set_category",
            "set_fee",
            "set_description",
            "add_tag",
        ) and action.get("value") in (None, ""):
            raise DomainError("VALIDATION_FAILED", f"{path}.{i}：动作 {kind} 需要 value。")
        if kind in ("set_input", "unset_input") and not action.get("name"):
            raise DomainError("VALIDATION_FAILED", f"{path}.{i}：动作 {kind} 需要 name。")


def _get(facts: Mapping[str, Any], path: str) -> Any:
    if path.startswith("extracted."):
        value: Any = facts.get("extracted") or {}
        for part in path.split(".")[1:]:
            value = value.get(part) if isinstance(value, Mapping) else None
        return value
    return facts.get(path)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def evaluate(cond: Mapping[str, Any], facts: Mapping[str, Any]) -> tuple[bool, dict[str, str]]:
    """True/False and the named regex groups captured on the way."""
    captures: dict[str, str] = {}
    return _eval(cond, facts, captures), captures


def _eval(cond: Mapping[str, Any], facts: Mapping[str, Any], captures: dict[str, str]) -> bool:
    if "all" in cond:
        return all(_eval(c, facts, captures) for c in cond["all"])
    if "any" in cond:
        return any(_eval(c, facts, captures) for c in cond["any"])
    if "not" in cond:
        return not _eval(cond["not"], facts, {})
    op = cond["op"]
    target: Any = cond.get("value")
    value = _get(facts, cond["field"])
    if op == "is_null":
        return value in (None, "")
    if op == "not_null":
        return value not in (None, "")
    if op == "alias_of":
        return target in (facts.get("counterparty_candidates") or ()) or target == facts.get("counterparty")
    if op in ("eq", "ne", "in", "not_in"):
        values = target if isinstance(target, list) else [target]
        left_num = _dec(value)
        hit = any(
            (left_num is not None and _dec(v) is not None and left_num == _dec(v)) or norm(value) == norm(v)
            for v in values
        )
        return hit if op in ("eq", "in") else not hit
    if op in ("gt", "gte", "lt", "lte", "between", "approx"):
        number = _dec(value)
        if number is None:
            return False
        if op == "approx":
            spec = target if isinstance(target, Mapping) else {"value": target}
            centre = _dec(spec.get("value")) or Decimal(0)
            tolerance = _dec(spec.get("tolerance")) or Decimal(0)
            limit = centre * tolerance / 100 if spec.get("mode") == "pct" else tolerance
            return abs(number - centre) <= limit
        if op == "between":
            low, high = _dec(target[0]), _dec(target[1])
            return low is not None and high is not None and low <= number <= high
        bound = _dec(target)
        if bound is None:
            return False
        return {"gt": number > bound, "gte": number >= bound, "lt": number < bound, "lte": number <= bound}[op]
    if op == "date_between":
        day = _date(value)
        low_d, high_d = _date(target[0]), _date(target[1])
        return day is not None and low_d is not None and high_d is not None and low_d <= day <= high_d
    if op == "time_between":
        text = str(value or "")
        start, end = str(target[0]), str(target[1])
        return start <= text <= end if start <= end else (text >= start or text <= end)
    if op == "weekday_in":
        return value in target
    text = norm(value)
    needle = norm(target)
    if op == "contains":
        return needle in text
    if op == "not_contains":
        return needle not in text
    if op == "starts_with":
        return text.startswith(needle)
    if op == "ends_with":
        return text.endswith(needle)
    match = re.search(str(target), str(value or "")[:MAX_REGEX_INPUT])  # regex on the original text
    if match:
        captures.update({k: v for k, v in match.groupdict().items() if v is not None})
        return True
    return False


TEMPLATE = re.compile(r"\{([a-z_][a-z0-9_.]*)\}")


def render(value: Any, facts: Mapping[str, Any], captures: Mapping[str, str]) -> Any:
    """Fill ``{amount}``, ``{captures.face}``, ``{extracted.site}`` … in strings (recursively in objects)."""
    if isinstance(value, str):

        def sub(match: re.Match[str]) -> str:
            key = match.group(1)
            found = captures.get(key.removeprefix("captures.")) if key.startswith("captures.") else _get(facts, key)
            return "" if found is None else (format(found, "f") if isinstance(found, Decimal) else str(found))

        return TEMPLATE.sub(sub, value)
    if isinstance(value, Mapping):
        return {k: render(v, facts, captures) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, facts, captures) for v in value]
    return value


def apply(
    rules: Sequence[RuleDef],
    facts: Mapping[str, Any],
    classification: Mapping[str, Any],
    locked: Sequence[str] = (),
) -> Outcome:
    """Run stages in order; within a stage lower priority first, then less specific first, so the
    most specific rule runs last and wins. Locked (hand-edited) fields are never overwritten."""
    out = Outcome(classification={**classification, "inputs": dict(classification.get("inputs") or {})})
    for stage in STAGES:
        ordered = sorted((r for r in rules if r.stage == stage), key=lambda r: (r.priority, r.specificity, r.code))
        for rule in ordered:
            hit, captures = evaluate(rule.condition, facts)
            if not hit:
                continue
            out.matched_rules.append(rule.id)
            changes = _actions(rule, facts, captures, out, set(locked))
            out.trace.append({"rule": rule.code, "version": rule.version, "stage": stage, "changes": changes})
            if out.ignored or rule.stop_processing:
                break
        if out.ignored:
            break
    return out


def _actions(
    rule: RuleDef, facts: Mapping[str, Any], captures: Mapping[str, str], out: Outcome, locked: set[str]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    c = out.classification

    def set_field(path: str, value: Any) -> None:
        if path in locked:
            changes.append({"field": path, "skipped": "locked"})
            return
        if path.startswith("inputs."):
            c["inputs"][path.removeprefix("inputs.")] = value
        else:
            c[path] = value
        changes.append({"field": path, "value": value})

    for action in rule.actions:
        kind = action["type"]
        value = render(action.get("value"), facts, captures)
        if kind == "set_transaction_type":
            set_field("type", value)
        elif kind == "set_counterparty":
            set_field("counterparty", value)
        elif kind == "set_input":
            set_field(f"inputs.{action['name']}", value)
        elif kind == "unset_input":
            if f"inputs.{action['name']}" not in locked:
                c["inputs"].pop(action["name"], None)
                changes.append({"field": f"inputs.{action['name']}", "value": None})
        elif kind == "set_channel":
            set_field("inputs.channel", value)
        elif kind == "set_category":
            set_field("inputs.category", value)
        elif kind == "set_fee":
            set_field(
                "inputs.fee",
                value if isinstance(value, Mapping) else {"amount": value, "commodity": facts.get("commodity")},
            )
        elif kind == "set_description":
            set_field("description", value)
        elif kind == "add_tag":  # tags accumulate across rules; templates allowed, e.g. "活动-{captures.month}"
            tags = list(c.get("tags") or [])
            if str(value) not in tags:
                tags.append(str(value))
            set_field("tags", tags)
        elif kind == "ignore":
            out.ignored = str(action.get("reason") or rule.code)
            changes.append({"ignored": out.ignored})
    return changes
