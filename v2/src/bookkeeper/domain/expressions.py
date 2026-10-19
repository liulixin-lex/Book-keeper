"""Safe expression language for templates, fee rules and rules (docs/05-posting-engine.md §3).

Parsed with ``ast`` and evaluated by walking a whitelist of node types. Numbers are Decimal
(literals are re-read from source text, so ``0.03`` is exact). No subscripts, comprehensions,
lambdas, assignments or exponentiation; attribute access only on ``Namespace`` values.
"""

from __future__ import annotations

import ast
import re
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any

from bookkeeper.domain.money import ROUNDING_MODES, parse_decimal

MAX_LENGTH = 2000
MAX_NODES = 500
MAX_REGEX_INPUT = 2000


class ExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class Amount:
    """A quantity of a commodity in major units, e.g. Amount(Decimal('51.50'), 'CNY')."""

    value: Decimal
    commodity: str

    def _same(self, other: Amount) -> None:
        if other.commodity != self.commodity:
            raise ExpressionError(f"COMMODITY_MISMATCH: {self.commodity} 与 {other.commodity}")

    def __add__(self, other: object) -> Amount:
        if not isinstance(other, Amount):
            raise ExpressionError("金额只能与同币种金额相加")
        self._same(other)
        return Amount(self.value + other.value, self.commodity)

    def __sub__(self, other: object) -> Amount:
        if not isinstance(other, Amount):
            raise ExpressionError("金额只能与同币种金额相减")
        self._same(other)
        return Amount(self.value - other.value, self.commodity)

    def __mul__(self, other: object) -> Amount:
        if isinstance(other, Amount):
            raise ExpressionError("金额不能与金额相乘")
        return Amount(self.value * _num(other), self.commodity)

    __rmul__ = __mul__

    def __truediv__(self, other: object) -> Amount | Decimal:
        if isinstance(other, Amount):
            self._same(other)
            return self.value / other.value
        return Amount(self.value / _num(other), self.commodity)

    def __neg__(self) -> Amount:
        return Amount(-self.value, self.commodity)

    def _cmp_value(self, other: object) -> Decimal:
        if isinstance(other, Amount):
            self._same(other)
            return other.value
        return _num(other)

    def __lt__(self, other: object) -> bool:
        return self.value < self._cmp_value(other)

    def __le__(self, other: object) -> bool:
        return self.value <= self._cmp_value(other)

    def __gt__(self, other: object) -> bool:
        return self.value > self._cmp_value(other)

    def __ge__(self, other: object) -> bool:
        return self.value >= self._cmp_value(other)


class Namespace(Mapping[str, Any]):
    """Read-only attribute container exposed to expressions (``fees.channel_fee``)."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = dict(values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _num(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ExpressionError("布尔值不能参与算术")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise ExpressionError(f"需要数值，得到 {type(value).__name__}")


_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}
_CMP_OPS: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_ALLOWED = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.IfExp,
    ast.Call,
    ast.keyword,
    ast.List,
    ast.Tuple,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.USub,
    ast.UAdd,
    ast.Not,
    ast.And,
    ast.Or,
    *_CMP_OPS.keys(),
)


@dataclass(frozen=True)
class Compiled:
    source: str
    tree: ast.Expression
    names: frozenset[str]


def compile_expr(source: str) -> Compiled:
    if len(source) > MAX_LENGTH:
        raise ExpressionError(f"表达式超过 {MAX_LENGTH} 个字符")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            tree = ast.parse(source, mode="eval")
    except (SyntaxWarning, SyntaxError) as exc:
        message = exc.msg if isinstance(exc, SyntaxError) else str(exc)
        hint = "（正则请写成 r'...'）" if "escape" in message else ""
        raise ExpressionError(f"表达式语法错误：{message}{hint}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ExpressionError(f"表达式超过 {MAX_NODES} 个节点")
    names: set[str] = set()
    for node in nodes:
        if not isinstance(node, _ALLOWED):
            raise ExpressionError(f"不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError("不允许访问以下划线开头的属性")
        if isinstance(node, ast.Name):
            if node.id.startswith("_"):
                raise ExpressionError("不允许以下划线开头的名称")
            names.add(node.id)
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise ExpressionError("只能调用内置函数")
        if isinstance(node, ast.Constant) and isinstance(node.value, complex | bytes):
            raise ExpressionError("不支持该常量类型")
    return Compiled(source, tree, frozenset(names))


@dataclass
class EvalContext:
    variables: Mapping[str, Any]
    scales: Mapping[str, int]
    rounding_mode: str = "half_up"
    functions: Mapping[str, Callable[..., Any]] | None = None


def evaluate(expr: Compiled | str, ctx: EvalContext) -> Any:
    compiled = compile_expr(expr) if isinstance(expr, str) else expr
    functions = {**builtin_functions(ctx), **(ctx.functions or {})}
    try:
        return _eval(compiled.tree.body, compiled.source, ctx, functions)
    except ExpressionError:
        raise
    except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise ExpressionError("除数为零或数值无效") from exc
    except (TypeError, ValueError, KeyError) as exc:
        raise ExpressionError(f"求值失败：{exc}") from exc


def _eval(node: ast.AST, src: str, ctx: EvalContext, functions: Mapping[str, Callable[..., Any]]) -> Any:
    def ev(n: ast.AST) -> Any:
        return _eval(n, src, ctx, functions)

    match node:
        case ast.Constant(value=value):
            if isinstance(value, bool) or value is None or isinstance(value, str):
                return value
            if isinstance(value, int | float):
                text = ast.get_source_segment(src, node) or str(value)
                return parse_decimal(text)
            raise ExpressionError("不支持的常量")
        case ast.Name(id=name):
            if name in ("true", "True"):
                return True
            if name in ("false", "False"):
                return False
            if name in ("null", "None"):
                return None
            if name not in ctx.variables:
                raise ExpressionError(f"未定义的名称：{name}")
            return ctx.variables[name]
        case ast.Attribute(value=value, attr=attr):
            target = ev(value)
            if target is None:
                return None
            if not isinstance(target, Namespace):
                raise ExpressionError(f"不能访问属性 {attr}")
            if attr not in target:
                raise ExpressionError(f"未定义的属性：{attr}")
            return target[attr]
        case ast.BinOp(left=left, op=op, right=right):
            a, b = ev(left), ev(right)
            if isinstance(a, str) or isinstance(b, str):
                raise ExpressionError("字符串请使用 concat() 拼接")
            a = a if isinstance(a, Amount) else _num(a)
            b = b if isinstance(b, Amount) else _num(b)
            if isinstance(a, Decimal) and isinstance(b, Amount):
                if isinstance(op, ast.Mult):
                    return b * a
                raise ExpressionError("数值不能与金额相加、相减或相除")
            return _BIN_OPS[type(op)](a, b)
        case ast.UnaryOp(op=op, operand=operand):
            value = ev(operand)
            if isinstance(op, ast.Not):
                return not value
            if isinstance(op, ast.USub):
                return -value if isinstance(value, Amount) else -_num(value)
            return value if isinstance(value, Amount) else _num(value)
        case ast.BoolOp(op=op, values=values):
            if isinstance(op, ast.And):
                result: Any = True
                for v in values:
                    result = ev(v)
                    if not result:
                        return result
                return result
            for v in values:
                result = ev(v)
                if result:
                    return result
            return result
        case ast.Compare(left=left, ops=ops, comparators=comparators):
            current = ev(left)
            for cmp_op, comp in zip(ops, comparators, strict=True):
                other = ev(comp)
                if not _CMP_OPS[type(cmp_op)](current, other):
                    return False
                current = other
            return True
        case ast.IfExp(test=test, body=body, orelse=orelse):
            return ev(body) if ev(test) else ev(orelse)
        case ast.List(elts=elts) | ast.Tuple(elts=elts):
            return tuple(ev(e) for e in elts)
        case ast.Call(func=ast.Name(id=name), args=args, keywords=keywords):
            if name not in functions:
                raise ExpressionError(f"未知函数：{name}")
            kwargs = {k.arg: ev(k.value) for k in keywords if k.arg is not None}
            return functions[name](*[ev(a) for a in args], **kwargs)
    raise ExpressionError(f"不支持的语法：{type(node).__name__}")


def builtin_functions(ctx: EvalContext) -> dict[str, Callable[..., Any]]:
    def scale_of(commodity: str) -> int:
        if commodity not in ctx.scales:
            raise ExpressionError(f"未知币种：{commodity}")
        return ctx.scales[commodity]

    def _round(x: Any, scale: Any = None, mode: str | None = None) -> Any:
        rounding = ROUNDING_MODES.get(mode or ctx.rounding_mode)
        if rounding is None:
            raise ExpressionError(f"未知舍入方式：{mode}")
        if isinstance(x, Amount):
            digits = int(scale) if scale is not None else scale_of(x.commodity)
            return Amount(x.value.quantize(Decimal(1).scaleb(-digits), rounding=rounding), x.commodity)
        digits = int(scale) if scale is not None else 0
        return _num(x).quantize(Decimal(1).scaleb(-digits), rounding=rounding)

    def pct(x: Any, rate: Any) -> Any:
        return x * _num(rate) if isinstance(x, Amount) else _num(x) * _num(rate)

    def coalesce(*values: Any) -> Any:
        return next((v for v in values if v is not None), None)

    def zero(x: Amount) -> Amount:
        if not isinstance(x, Amount):
            raise ExpressionError("zero() 需要金额参数")
        return Amount(Decimal(0), x.commodity)

    def money(text: Any, commodity: str) -> Amount:
        scale_of(commodity)
        return Amount(parse_decimal(text if isinstance(text, str | int | Decimal) else str(text)), commodity)

    def units(x: Amount) -> Decimal:
        if not isinstance(x, Amount):
            raise ExpressionError("units() 需要金额参数")
        return x.value

    def _min(*values: Any) -> Any:
        return min(values)

    def _max(*values: Any) -> Any:
        return max(values)

    def _abs(x: Any) -> Any:
        if isinstance(x, Amount):
            return Amount(abs(x.value), x.commodity)
        return abs(_num(x))

    def concat(*parts: Any) -> str:
        return "".join("" if p is None else _text(p) for p in parts)

    def regex_extract(text: Any, pattern: str, group: Any = 0) -> str | None:
        if text is None:
            return None
        value = str(text)[:MAX_REGEX_INPUT]
        try:
            match = re.search(pattern, value)
        except re.error as exc:
            raise ExpressionError(f"正则表达式错误：{exc}") from exc
        if not match:
            return None
        key = group if isinstance(group, str) else int(group)
        return match.group(key)

    def days_between(a: date, b: date) -> Decimal:
        return Decimal((b - a).days)

    return {
        "round": _round,
        "pct": pct,
        "coalesce": coalesce,
        "zero": zero,
        "money": money,
        "units": units,
        "min": _min,
        "max": _max,
        "abs": _abs,
        "concat": concat,
        "lower": lambda s: None if s is None else str(s).lower(),
        "upper": lambda s: None if s is None else str(s).upper(),
        "regex_extract": regex_extract,
        "days_between": days_between,
    }


def _text(value: Any) -> str:
    if isinstance(value, Amount):
        return f"{value.value} {value.commodity}"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)
