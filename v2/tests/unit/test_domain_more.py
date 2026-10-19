"""Edge cases for the pure domain layer."""

from datetime import date
from decimal import Decimal

import pytest

from bookkeeper.domain.allocation import allocate
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.expressions import Amount, EvalContext, ExpressionError, Namespace, evaluate
from bookkeeper.domain.fx import FxQuote
from bookkeeper.domain.ledger import (
    AccountInfo,
    BuildSettings,
    LineInput,
    build_lines,
    quantize_rate,
)
from bookkeeper.domain.money import AmountError, Money, parse_decimal, round_to_scale, to_minor

SCALES = {"CNY": 2, "GBP": 2}
D = date(2026, 10, 18)


def ev(src: str, **variables: object) -> object:
    return evaluate(src, EvalContext(variables=variables, scales=SCALES))


CNY = lambda v: Amount(Decimal(v), "CNY")  # noqa: E731


def test_amount_operators() -> None:
    a, b = CNY("10.00"), CNY("4.00")
    assert ev("a - b", a=a, b=b) == CNY("6.00")
    assert ev("a / 4", a=a) == CNY("2.5")
    assert ev("a / b", a=a, b=b) == Decimal("2.5")
    assert ev("-a", a=a) == CNY("-10.00")
    assert ev("+a", a=a) == a
    assert ev("a >= b and b <= a and a != b and not (a < b)", a=a, b=b) is True
    assert ev("abs(-a)", a=a) == a
    assert ev("units(a)", a=a) == Decimal("10.00")
    assert ev("zero(a)", a=a) == CNY("0")
    assert ev("round(a / 3, 4)", a=a) == CNY("3.3333")
    assert ev("round(10 / 3)") == Decimal(3)
    assert ev("round(2.5, 0, 'half_even')") == Decimal(2)
    assert ev("pct(200, 0.015)") == Decimal("3.000")


@pytest.mark.parametrize(
    ("src", "message"),
    [
        ("a * b", "金额不能与金额相乘"),
        ("a + 1", "同币种金额相加"),
        ("a - 1", "同币种金额相减"),
        ("'x' + 'y'", "concat"),
        ("true + 1", "布尔值"),
        ("a.b", "不能访问属性"),
        ("ns.missing", "未定义的属性"),
        ("zero(1)", "zero()"),
        ("units(1)", "units()"),
        ("money('1', 'XXX')", "未知币种"),
        ("round(a, mode='odd')", "未知舍入方式"),
        ("regex_extract('a', '(')", "正则表达式错误"),
        ("1 +", "语法错误"),
    ],
)
def test_expression_errors(src: str, message: str) -> None:
    with pytest.raises(ExpressionError, match=message):
        ev(src, a=CNY("1"), b=CNY("2"), ns=Namespace({"x": 1}))


def test_expression_misc() -> None:
    ns = Namespace({"x": Decimal(1), "none": None})
    assert len(ns) == 2 and list(ns) == ["x", "none"]
    assert ev("ns.x", ns=ns) == 1
    assert ev("missing.x", missing=None) is None
    assert ev("true or false") is True
    assert ev("null is None" if False else "coalesce(null, 'd')") == "d"
    assert ev("0 or ''") == ""
    assert ev("1 and 0") == 0
    assert ev("lower('AbC') + ''" if False else "concat(lower('AbC'), upper('d'), null, 1.50)") == "abcD1.50"
    assert ev("concat(a)", a=CNY("1.5")) == "1.5 CNY"
    assert ev("regex_extract(null, 'x')") is None
    assert ev("regex_extract('abc', 'z')") is None
    assert ev("days_between(d1, d2)", d1=date(2026, 1, 1), d2=date(2026, 1, 31)) == 30
    assert ev("min(3, 1)") == 1


def test_allocation_and_money_edges() -> None:
    with pytest.raises(ValueError, match="empty"):
        allocate(1, [])
    with pytest.raises(ValueError, match="non-negative"):
        allocate(1, [-1, 2])
    with pytest.raises(ValueError, match="zero"):
        allocate(1, [0, 0])
    with pytest.raises(AmountError, match="类型"):
        parse_decimal([1])
    assert round_to_scale(Decimal("1.005"), 2) == Decimal("1.01")
    assert to_minor(Decimal("2.50"), 2) == 250
    with pytest.raises(AmountError):
        Money(1.5, "CNY")  # type: ignore[arg-type]
    assert Money(5, "CNY") - Money(2, "CNY") == Money(3, "CNY")


ACC = AccountInfo("acc_1", "1012.01", "资金账户", "asset", "debit", "funds")
REV = AccountInfo("acc_2", "5001.01", "收入", "revenue", "credit")
OFFSET = AccountInfo("acc_o", "3902", "期初余额调整", "equity", "credit", "opening_balance")


def settings(**kw: object) -> BuildSettings:
    base = dict(base_commodity="CNY", scales=SCALES, effective_date=D)
    base.update(kw)
    return BuildSettings(**base)  # type: ignore[arg-type]


def li(account: AccountInfo, side: str, amount: int, commodity: str = "CNY", **kw: object) -> LineInput:
    return LineInput(account=account, side=side, amount_minor=amount, commodity=commodity, **kw)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("account", "line_kw", "fragment"),
    [
        (AccountInfo("a", "1", "x", "asset", "debit", is_active=False), {}, "已停用"),
        (AccountInfo("a", "1", "x", "asset", "debit", allowed_commodities=("GBP",)), {}, "只允许 GBP"),
        (AccountInfo("a", "1", "x", "asset", "debit", open_date=date(2026, 11, 1)), {}, "开户"),
        (AccountInfo("a", "1", "x", "asset", "debit", close_date=date(2026, 1, 1)), {}, "销户"),
        (
            AccountInfo("a", "1", "x", "asset", "debit", forbidden_dimensions=("channel",)),
            {"dimensions": {"channel": "v"}},
            "不允许维度",
        ),
        (ACC, {"quantity": Decimal("1.123456789"), "quantity_unit": "UCR"}, "8 位小数"),
        (ACC, {"quantity": Decimal("1")}, "同时填写"),
        (ACC, {"fx_rate": Decimal("1")}, "本位币行不能指定汇率"),
        (ACC, {"side": "both"}, "debit 或 credit"),
    ],
)
def test_line_validation_branches(account: AccountInfo, line_kw: dict, fragment: str) -> None:  # type: ignore[type-arg]
    side = line_kw.pop("side", "debit")
    with pytest.raises(DomainError) as exc:
        build_lines([li(account, side, 100, **line_kw), li(REV, "credit", 100)], settings())
    assert fragment in str([e.message for e in exc.value.errors])


def test_unknown_commodity_and_single_line() -> None:
    with pytest.raises(DomainError) as exc:
        build_lines([li(ACC, "debit", 1, "XYZ")], settings())
    messages = " ".join(e.message for e in exc.value.errors)
    assert "至少需要两行" in messages and "未知币种" in messages


def test_offset_account_balances_foreign_opening() -> None:
    quote = FxQuote("GBP", "CNY", Decimal("9.5"), "table", D, "fxr_1", ("FX_RATE_STALE:2026-10-17",))
    result = build_lines([li(ACC, "debit", 1000, "GBP")], settings(offset_account=OFFSET, quote_for=lambda c: quote))
    assert [(l.account_code, l.amount, l.base_amount, l.line_role) for l in result.lines] == [
        ("1012.01", 1000, 9500, "manual"),
        ("3902", -1000, -9500, "opening_offset"),
    ]
    assert result.warnings[0]["code"] == "FX_RATE_STALE"


def test_conversion_defer_leaves_difference_in_trading() -> None:
    trading = AccountInfo("acc_t", "3901", "货币兑换", "equity", "credit", "trading")
    result = build_lines(
        [li(ACC, "debit", 18850), li(ACC, "credit", 2000, "GBP", fx_rate=Decimal("9.5"))],
        settings(allow_conversion=True, fx_realization="defer", trading_account=trading),
    )
    assert [l.line_role for l in result.lines] == ["manual", "manual", "trading", "trading"]


def test_missing_system_accounts_reported() -> None:
    with pytest.raises(DomainError, match="货币兑换"):
        build_lines(
            [li(ACC, "debit", 100), li(ACC, "credit", 10, "GBP", fx_rate=Decimal(10))], settings(allow_conversion=True)
        )
    with pytest.raises(DomainError, match="尾差"):
        build_lines(
            [
                li(ACC, "debit", 101, "GBP", fx_rate=Decimal("0.5")),
                li(REV, "credit", 101, "GBP", fx_rate=Decimal("0.49")),
            ],
            settings(),
        )


def test_rate_quantization_bounds() -> None:
    assert quantize_rate(Decimal(1) / Decimal(3)) == Decimal("0.333333333333")
    with pytest.raises(DomainError):
        quantize_rate(Decimal(0))
