"""Exact amounts: integer minor units per commodity scale. Floats are rejected everywhere."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
)

ROUNDING_MODES: dict[str, str] = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
    "up": ROUND_UP,
    "down": ROUND_DOWN,
}


class AmountError(ValueError):
    """Invalid amount text or precision."""


def parse_decimal(value: object) -> Decimal:
    """Parse a decimal from str/int/Decimal. Floats, NaN and infinities are rejected."""
    if isinstance(value, bool | float):
        raise AmountError("金额必须是字符串或整数，不能是浮点数")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise AmountError(f"无法解析金额：{value!r}") from exc
    else:
        raise AmountError(f"不支持的金额类型：{type(value).__name__}")
    if not result.is_finite():
        raise AmountError("金额必须是有限数")
    return result


def to_minor(value: object, scale: int) -> int:
    """Exact conversion to minor units; raises if the value has more decimals than ``scale``."""
    amount = parse_decimal(value)
    scaled = amount.scaleb(scale)
    if scaled != scaled.to_integral_value():
        raise AmountError(f"金额 {amount} 超过 {scale} 位小数")
    return int(scaled)


def from_minor(minor: int, scale: int) -> Decimal:
    return Decimal(minor).scaleb(-scale)


def round_minor(value: Decimal, mode: str = "half_up") -> int:
    """Round a value already expressed in minor units to an integer."""
    return int(value.quantize(Decimal(1), rounding=ROUNDING_MODES[mode]))


def round_to_scale(value: Decimal, scale: int, mode: str = "half_up") -> Decimal:
    return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUNDING_MODES[mode])


def format_amount(minor: int, scale: int, symbol: str | None = None, code: str | None = None) -> str:
    """``¥1,234.50`` / ``-£3.00`` / ``12.3456 UCR``."""
    value = from_minor(abs(minor), scale)
    text = f"{value:,.{scale}f}"
    sign = "-" if minor < 0 else ""
    if symbol:
        return f"{sign}{symbol}{text}"
    return f"{sign}{text} {code}" if code else f"{sign}{text}"


@dataclass(frozen=True, order=True)
class Money:
    minor: int
    commodity: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise AmountError("minor must be int")

    def __neg__(self) -> Money:
        return Money(-self.minor, self.commodity)

    def __add__(self, other: Money) -> Money:
        if other.commodity != self.commodity:
            raise AmountError(f"不同币种不能相加：{self.commodity} 与 {other.commodity}")
        return Money(self.minor + other.minor, self.commodity)

    def __sub__(self, other: Money) -> Money:
        return self + (-other)
