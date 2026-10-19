from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bookkeeper.domain.canonical import chain_hash, genesis_hash
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.fx import FxQuote
from bookkeeper.domain.ledger import (
    AccountInfo,
    BuildSettings,
    LineInput,
    assert_balanced,
    build_lines,
    entry_hash_payload,
    reverse_lines,
)

D = date(2026, 10, 18)
FUNDS = AccountInfo("acc_f", "1012.01", "资金账户", "asset", "debit", "funds")
REVENUE = AccountInfo("acc_r", "5001.01", "API 额度销售", "revenue", "credit", "revenue_operating")
FEE = AccountInfo("acc_e", "5603.01", "手续费", "expense", "debit", "expense_finance_fee")
TRADING = AccountInfo("acc_t", "3901", "货币兑换", "equity", "credit", "trading", manual_entry_allowed=False)
FXGL = AccountInfo("acc_x", "5603.02", "汇兑损益", "expense", "debit", "fx_gain_loss", manual_entry_allowed=False)
ROUNDING = AccountInfo("acc_n", "5603.09", "尾差", "expense", "debit", "rounding", manual_entry_allowed=False)
GROUP = AccountInfo("acc_g", "5401", "主营业务成本", "expense", "debit", is_group=True)


def cfg(rates: dict[str, str] | None = None, **kw: object) -> BuildSettings:
    rates = rates or {}

    def quote(c: str) -> FxQuote | None:
        return FxQuote(c, "CNY", Decimal(rates[c]), "table", D, f"fxr_{c}") if c in rates else None

    base = dict(
        base_commodity="CNY",
        scales={"CNY": 2, "GBP": 2, "USD": 2},
        effective_date=D,
        trading_account=TRADING,
        fx_gain_loss_account=FXGL,
        rounding_account=ROUNDING,
        quote_for=quote,
    )
    base.update(kw)
    return BuildSettings(**base)  # type: ignore[arg-type]


def line(account: AccountInfo, side: str, amount: int, commodity: str = "CNY", **kw: object) -> LineInput:
    return LineInput(account=account, side=side, amount_minor=amount, commodity=commodity, **kw)  # type: ignore[arg-type]


def test_simple_cny_entry() -> None:
    result = build_lines([line(FUNDS, "debit", 9700), line(FEE, "debit", 300), line(REVENUE, "credit", 10000)], cfg())
    assert [(l.account_code, l.amount, l.base_amount) for l in result.lines] == [
        ("1012.01", 9700, 9700),
        ("5603.01", 300, 300),
        ("5001.01", -10000, -10000),
    ]
    assert [l.line_no for l in result.lines] == [1, 2, 3]


def test_foreign_entry_with_rounding_line() -> None:
    result = build_lines(
        [line(FUNDS, "debit", 1915, "GBP"), line(FEE, "debit", 85, "GBP"), line(REVENUE, "credit", 2000, "GBP")],
        cfg({"GBP": "9.5127"}),
    )
    bases = [l.base_amount for l in result.lines]
    assert bases[:3] == [18217, 809, -19025]
    rounding = result.lines[3]
    assert (rounding.account_code, rounding.commodity, rounding.amount, rounding.base_amount) == (
        "5603.09",
        "GBP",
        0,
        -1,
    )
    assert result.warnings[0]["code"] == "ROUNDING_APPLIED"
    assert result.fx[0]["rate"] == "9.5127"


def test_conversion_generates_trading_and_fx_lines() -> None:
    inputs = [line(FUNDS, "debit", 18850, "CNY"), line(FUNDS, "credit", 2000, "GBP")]
    with pytest.raises(DomainError) as exc:
        build_lines(inputs, cfg({"GBP": "9.5"}))
    assert exc.value.code == "NOT_BALANCED" and "allow_conversion" in exc.value.detail
    result = build_lines(inputs, cfg({"GBP": "9.5"}, allow_conversion=True))
    summary = [(l.account_code, l.commodity, l.amount, l.base_amount, l.line_role) for l in result.lines]
    assert summary == [
        ("1012.01", "CNY", 18850, 18850, "manual"),
        ("1012.01", "GBP", -2000, -19000, "manual"),
        ("3901", "CNY", -18850, -18850, "trading"),
        ("3901", "GBP", 2000, 19000, "trading"),
        ("5603.02", "GBP", 0, 150, "fx_realization"),
        ("3901", "GBP", 0, -150, "fx_realization"),
    ]


def test_validation_collects_all_errors() -> None:
    with pytest.raises(DomainError) as exc:
        build_lines(
            [line(GROUP, "debit", 100), line(TRADING, "credit", 100), line(FUNDS, "debit", 0)],
            cfg(),
        )
    codes = [e.code for e in exc.value.errors]
    assert codes.count("ACCOUNT_NOT_POSTABLE") == 2 and "INPUT_INVALID" in codes
    assert "共 3 处问题" in exc.value.detail


def test_missing_rate_and_unbalanced() -> None:
    with pytest.raises(DomainError) as exc:
        build_lines([line(FUNDS, "debit", 100, "USD"), line(REVENUE, "credit", 100, "USD")], cfg())
    assert exc.value.code == "FX_RATE_MISSING"
    with pytest.raises(DomainError) as exc:
        build_lines([line(FUNDS, "debit", 100), line(REVENUE, "credit", 99)], cfg())
    assert exc.value.code == "NOT_BALANCED" and "0.01" in exc.value.detail


def test_explicit_base_amount_sets_actual_rate() -> None:
    result = build_lines(
        [
            line(FUNDS, "debit", 2000, "GBP", base_amount_minor=18850),
            line(REVENUE, "credit", 2000, "GBP", base_amount_minor=18850),
        ],
        cfg(),
    )
    assert result.lines[0].fx_rate == Decimal("9.425") and result.lines[0].fx_source == "actual"


def test_dimension_rules() -> None:
    needs_channel = AccountInfo("acc_c", "5001.02", "x", "revenue", "credit", required_dimensions=("channel",))
    with pytest.raises(DomainError) as exc:
        build_lines([line(FUNDS, "debit", 100), line(needs_channel, "credit", 100)], cfg())
    assert exc.value.code == "DIMENSION_REQUIRED"
    ok = build_lines(
        [line(FUNDS, "debit", 100), line(needs_channel, "credit", 100, dimensions={"channel": "dmv_1"})], cfg()
    )
    assert ok.lines[1].dimensions == (("channel", "dmv_1"),)


amount = st.integers(min_value=1, max_value=10**10)


@settings(max_examples=300)
@given(
    debits=st.lists(st.tuples(amount, st.sampled_from(["CNY", "GBP", "USD"])), min_size=1, max_size=6),
    rate_gbp=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("50"), places=6),
    rate_usd=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("50"), places=6),
)
def test_property_balanced_and_reversal_nets_zero(debits, rate_gbp, rate_usd) -> None:  # type: ignore[no-untyped-def]
    """P-01 / P-04: per-commodity balanced inputs always build balanced lines; reversal nets to zero."""
    inputs = []
    for value, commodity in debits:
        inputs.append(line(FUNDS, "debit", value, commodity))
        inputs.append(line(REVENUE, "credit", value, commodity))
    result = build_lines(inputs, cfg({"GBP": str(rate_gbp), "USD": str(rate_usd)}, tolerance_per_line=10**6))
    assert_balanced(result.lines)
    reversed_lines = reverse_lines(result.lines)
    for original, reversal in zip(result.lines, reversed_lines, strict=True):
        assert original.amount + reversal.amount == 0
        assert original.base_amount + reversal.base_amount == 0


def test_hash_payload_is_sensitive_to_any_line_change() -> None:
    from datetime import UTC, datetime

    result = build_lines([line(FUNDS, "debit", 100), line(REVENUE, "credit", 100)], cfg())
    kwargs = dict(
        book_id="bk_1",
        seq=1,
        entry_id="jen_1",
        number="记-202610-0001",
        transaction_id="txn_1",
        kind="posting",
        journal_code="记",
        effective_date=D,
        recorded_at=datetime(2026, 10, 18, tzinfo=UTC),
        reverses_entry_id=None,
        template_id=None,
        fee_rule_ids=[],
    )
    g = genesis_hash("ledger", "bk_1")
    h = chain_hash(g, entry_hash_payload(lines=result.lines, **kwargs))
    tampered = (result.lines[0].__class__(**{**result.lines[0].__dict__, "memo": "x"}), result.lines[1])
    assert chain_hash(g, entry_hash_payload(lines=tampered, **kwargs)) != h
