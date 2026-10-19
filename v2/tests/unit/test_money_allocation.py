from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bookkeeper.domain.allocation import allocate
from bookkeeper.domain.money import AmountError, Money, format_amount, from_minor, parse_decimal, to_minor


def test_to_minor_exact() -> None:
    assert to_minor("51.50", 2) == 5150
    assert to_minor("1,234.5", 2) == 123450
    assert to_minor(3, 2) == 300
    assert to_minor("0.0001", 4) == 1
    assert from_minor(5150, 2) == Decimal("51.50")


@pytest.mark.parametrize("value", ["1.001", 1.5, "abc", "NaN", "Infinity", True, None])
def test_to_minor_rejects(value: object) -> None:
    with pytest.raises(AmountError):
        to_minor(value, 2)


def test_parse_decimal_rejects_float() -> None:
    with pytest.raises(AmountError, match="浮点"):
        parse_decimal(0.1)


def test_format_amount() -> None:
    assert format_amount(123450, 2, "¥") == "¥1,234.50"
    assert format_amount(-300, 2, "£") == "-£3.00"
    assert format_amount(1234567, 4, code="UCR") == "123.4567 UCR"


def test_money_arithmetic() -> None:
    assert Money(100, "CNY") + Money(50, "CNY") == Money(150, "CNY")
    with pytest.raises(AmountError, match="不同币种"):
        Money(1, "CNY") + Money(1, "USD")


def test_allocate_examples() -> None:
    assert allocate(100, [1, 1, 1]) == [34, 33, 33]
    assert allocate(-100, [1, 1, 1]) == [-34, -33, -33]
    assert allocate(10, [Decimal("0.6"), Decimal("0.4")]) == [6, 4]
    assert allocate(5, [0, 1]) == [0, 5]


@given(
    st.integers(min_value=-(10**12), max_value=10**12),
    st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=8).filter(any),
)
def test_allocate_conserves_total(total: int, weights: list[int]) -> None:
    parts = allocate(total, weights)
    assert sum(parts) == total
    weight_sum = sum(weights)
    for part, weight in zip(parts, weights, strict=True):
        exact = Decimal(total) * weight / weight_sum
        assert abs(Decimal(part) - exact) < 1
