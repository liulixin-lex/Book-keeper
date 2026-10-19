from decimal import Decimal

import pytest

from bookkeeper.domain.expressions import Amount, EvalContext, ExpressionError, Namespace, compile_expr, evaluate

SCALES = {"CNY": 2, "GBP": 2, "UCR": 4}


def ev(src: str, **variables: object) -> object:
    return evaluate(src, EvalContext(variables=variables, scales=SCALES))


def test_decimal_literals_exact() -> None:
    assert ev("0.1 + 0.2") == Decimal("0.3")
    assert ev("51.50 / 1.03") == Decimal("51.50") / Decimal("1.03")


def test_amount_arithmetic_and_rounding() -> None:
    gross = Amount(Decimal("100.00"), "CNY")
    assert ev("round(gross * 0.03)", gross=gross) == Amount(Decimal("3.00"), "CNY")
    assert ev("gross - round(pct(gross, 0.018))", gross=gross) == Amount(Decimal("98.20"), "CNY")
    assert ev("round(money('51.50', 'CNY') / 1.03)") == Amount(Decimal("50.00"), "CNY")
    assert ev("3 * gross", gross=gross) == Amount(Decimal("300.00"), "CNY")


def test_commodity_mismatch() -> None:
    with pytest.raises(ExpressionError, match="COMMODITY_MISMATCH"):
        ev("a + b", a=Amount(Decimal(1), "CNY"), b=Amount(Decimal(1), "GBP"))
    with pytest.raises(ExpressionError, match="数值不能"):
        ev("1 + a", a=Amount(Decimal(1), "CNY"))


def test_conditionals_namespaces_functions() -> None:
    fees = Namespace({"channel_fee": Amount(Decimal("1.50"), "CNY")})
    assert ev("fees.channel_fee > 0", fees=fees) is True
    assert ev("coalesce(missing, 5)", missing=None) == 5
    assert ev("'A' if x >= 10 else 'B'", x=Decimal(3)) == "B"
    assert ev("concat('链动', ' · ', order)", order="LD1") == "链动 · LD1"
    assert ev("regex_extract('100R 兑换码', r'(?P<face>\\d+)R', 'face')") == "100"
    with pytest.raises(ExpressionError, match="r'"):
        ev("regex_extract('100R', '(\\d+)R')")
    assert ev("x in ('a', 'b')", x="b") is True
    assert ev("max(1, 3, 2)") == 3


@pytest.mark.parametrize(
    "src",
    [
        "__import__('os')",
        "x.__class__",
        "[a for a in b]",
        "lambda: 1",
        "a[0]",
        "2 ** 10",
        "open('f')",
        "(1).real",
    ],
)
def test_rejects_unsafe(src: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate(src, EvalContext(variables={"a": (1,), "b": (1,), "x": 1}, scales=SCALES))


def test_limits_and_errors() -> None:
    with pytest.raises(ExpressionError, match="字符"):
        compile_expr("1+" * 1500 + "1")
    with pytest.raises(ExpressionError, match="除数"):
        ev("1 / 0")
    with pytest.raises(ExpressionError, match="未定义"):
        ev("nope")
    with pytest.raises(ExpressionError, match="未知函数"):
        ev("eval('1')")
    assert compile_expr("a + b.c").names == {"a", "b"}
