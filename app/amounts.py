from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

AMOUNT_SCALE = 100_000_000
RATE_SCALE = 1_000_000_000_000


def as_decimal(value: Any) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid decimal value") from exc
    if not result.is_finite():
        raise ValueError("Decimal value must be finite")
    return result


def to_e8(value: Any) -> int:
    scaled = (as_decimal(value) * AMOUNT_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled)


def from_e8(value: int, *, min_places: int = 2) -> str:
    decimal_value = Decimal(value) / AMOUNT_SCALE
    text = f"{decimal_value:.8f}".rstrip("0").rstrip(".")
    if "." not in text:
        return f"{text}.{'0' * min_places}" if min_places else text
    current_places = len(text.rsplit(".", 1)[1])
    if current_places < min_places:
        text += "0" * (min_places - current_places)
    return text


def to_e12(value: Any) -> int:
    scaled = (as_decimal(value) * RATE_SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(scaled)


def from_e12(value: int) -> str:
    text = f"{Decimal(value) / RATE_SCALE:.12f}".rstrip("0").rstrip(".")
    return text or "0"


def convert_e8(amount_e8: int, rate_e12: int, *, decimal_places: int = 2) -> int:
    amount = Decimal(amount_e8) / AMOUNT_SCALE
    rate = Decimal(rate_e12) / RATE_SCALE
    quantizer = Decimal(1).scaleb(-decimal_places)
    converted = (amount * rate).quantize(quantizer, rounding=ROUND_HALF_UP)
    return to_e8(converted)
