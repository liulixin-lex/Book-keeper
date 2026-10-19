from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bookkeeper.domain import business
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.fees import FeeRule, fee_on, select_rule, split_total
from bookkeeper.domain.ledger import AccountInfo

FUNDS = AccountInfo("acc_f", "1012.01", "资金账户", "asset", "debit", "funds")
REVENUE = AccountInfo("acc_r", "5001.01", "API 额度销售", "revenue", "credit", "revenue_operating")
COST = AccountInfo("acc_c", "5401.01", "上游额度", "expense", "debit", "cost_operating")
FEE = AccountInfo("acc_x", "5603.01", "手续费", "expense", "debit", "expense_finance_fee")
ON = date(2026, 10, 18)


def rule(**kw) -> FeeRule:  # type: ignore[no-untyped-def]
    return FeeRule(id=kw.pop("id", "fee_1"), code=kw.pop("code", "r"), version=1, **kw)


def ctx(found: FeeRule | None = None, channel: str | None = "ch", counterparty: str | None = "cp") -> business.Context:
    return business.Context("sale", channel, counterparty, ON, lambda _c: found, FEE)


def test_fee_methods_and_bounds() -> None:
    assert fee_on(rule(rate=Decimal("0.03")), 10_000) == 300
    assert fee_on(rule(fixed_minor=100, commodity="CNY"), 10_000) == 100
    assert fee_on(rule(rate=Decimal("0.029"), fixed_minor=30, commodity="USD"), 10_000) == 320
    assert fee_on(rule(rate=Decimal("0.01"), min_minor=50, commodity="CNY"), 1_000) == 50
    assert fee_on(rule(rate=Decimal("0.01"), max_minor=500, commodity="CNY"), 100_000) == 500
    assert rule(rate=Decimal("0.029"), fixed_minor=30).method == "percentage_plus_fixed"
    assert split_total(rule(rate=Decimal("0.03")), 10_300) == (10_000, 300)
    assert split_total(rule(fixed_minor=100, commodity="CNY"), 5_100) == (5_000, 100)


@given(st.integers(min_value=1, max_value=10**10), st.integers(min_value=0, max_value=999), st.integers(0, 500))
def test_split_total_is_consistent_with_fee_on(total: int, permille: int, fixed: int) -> None:
    r = rule(rate=Decimal(permille) / 10_000, fixed_minor=fixed or None, commodity="CNY")
    base, fee = split_total(r, total)
    assert base + fee == total
    assert abs(fee - fee_on(r, base)) <= 1


def test_selection_priority_specificity_validity_and_ties() -> None:
    general = rule(id="a", code="general", rate=Decimal("0.05"))
    channel = rule(id="b", code="channel", rate=Decimal("0.03"), channels=("ch",))
    later = rule(id="c", code="later", rate=Decimal("0.01"), channels=("ch",), priority=5, valid_from=date(2027, 1, 1))
    usd_only = rule(id="d", code="usd", fixed_minor=30, commodity="USD", channels=("ch",), priority=9)
    assert select_rule([general, channel, later, usd_only], "sale", "ch", None, ON, "CNY") is channel
    assert select_rule([general, channel, usd_only], "sale", "ch", None, ON, "USD") is usd_only
    assert select_rule([general, channel], "sale", "other", None, ON) is general
    assert select_rule([channel], "sale", None, None, ON) is None
    twin = rule(id="e", code="twin", rate=Decimal("0.02"), channels=("ch",))
    with pytest.raises(DomainError) as exc:
        select_rule([channel, twin], "sale", "ch", None, ON)
    assert exc.value.code == "FEE_RULE_AMBIGUOUS"


@given(st.integers(min_value=1, max_value=10**9), st.integers(min_value=0, max_value=999))
def test_sale_lines_always_balance(gross: int, permille: int) -> None:
    built = business.sale(
        {"gross": business.Amount(gross, "CNY"), "settle_account": FUNDS, "revenue_account": REVENUE},
        ctx(rule(rate=Decimal(permille) / 1000)),
    )
    signed = sum(line.amount_minor if line.side == "debit" else -line.amount_minor for line in built.lines)
    assert signed == 0
    assert built.computed["net"] + built.computed["fee"] == gross


def test_credit_purchase_requires_site_and_validates_amounts() -> None:
    inputs = {
        "face": business.Amount(5000, "CNY"),
        "total": business.Amount(4000, "CNY"),
        "cost_account": COST,
        "pay_account": FUNDS,
    }
    with pytest.raises(DomainError) as exc:
        business.credit_purchase(inputs, ctx(counterparty=None))
    paths = {e.path for e in exc.value.errors}
    assert paths == {"inputs.total", "counterparty"}


def test_transfer_same_commodity_must_add_up() -> None:
    other = AccountInfo("acc_o", "1012.02", "其他", "asset", "debit")
    good = business.transfer(
        {
            "from_account": FUNDS,
            "to_account": other,
            "amount_out": business.Amount(1000, "CNY"),
            "fee": business.Amount(10, "CNY"),
        },
        ctx(),
    )
    assert [(l.account.code, l.side, l.amount_minor, dict(l.dimensions)) for l in good.lines] == [
        ("1012.01", "credit", 1000, {}),
        ("1012.02", "debit", 990, {}),
        ("5603.01", "debit", 10, {}),
    ]
    derived = business.transfer(  # both amounts, no fee: the difference is the fee
        {
            "from_account": FUNDS,
            "to_account": other,
            "amount_out": business.Amount(1000, "CNY"),
            "amount_in": business.Amount(999, "CNY"),
        },
        ctx(),
    )
    assert derived.computed["fee"] == 1
    with pytest.raises(DomainError):
        business.transfer(
            {
                "from_account": FUNDS,
                "to_account": other,
                "amount_out": business.Amount(1000, "CNY"),
                "amount_in": business.Amount(999, "CNY"),
                "fee": business.Amount(5, "CNY"),
            },
            ctx(),
        )


def test_fee_rules_for_expense_refund_and_transfer() -> None:
    three = rule(rate=Decimal("0.03"), transaction_types=("expense", "transfer", "sale_refund"))
    spent = business.expense(
        {"amount": business.Amount(10_000, "CNY"), "category": COST, "pay_account": FUNDS}, ctx(three)
    )
    assert spent.computed["fee"] == 300 and spent.fee_rule is three
    typed = business.expense(
        {
            "amount": business.Amount(10_000, "CNY"),
            "category": COST,
            "pay_account": FUNDS,
            "fee": business.Amount(500, "CNY"),
        },
        ctx(three),
    )
    assert typed.computed["fee"] == 500 and typed.warnings[0]["code"] == "FEE_DEVIATION"
    refund = business.sale_refund(
        {"amount": business.Amount(2_000, "CNY"), "revenue_account": REVENUE, "settle_account": FUNDS}, ctx(three)
    )
    assert refund.computed["fee_refunded"] == 60
    assert [(l.account.code, l.side, l.amount_minor) for l in refund.lines] == [
        ("5001.01", "debit", 2_000),
        ("5603.01", "credit", 60),
        ("1012.01", "credit", 1_940),
    ]
    other = AccountInfo("acc_o", "1012.02", "其他", "asset", "debit")
    moved = business.transfer(
        {"from_account": FUNDS, "to_account": other, "amount_out": business.Amount(1_000, "CNY")}, ctx(three)
    )
    assert moved.computed["fee"] == 30 and moved.computed["amount_in"] == 970


def test_untyped_rules_keep_their_old_scope() -> None:
    untyped = rule(rate=Decimal("0.03"))
    assert untyped.matches("sale", None, None, ON) and untyped.matches("credit_purchase", None, None, ON)
    assert not untyped.matches("expense", None, None, ON)
    assert untyped.mismatch("transfer", None, None, ON) == "未列出交易类型的规则只适用于销售收入与额度采购"


def test_type_examples_are_valid_requests() -> None:
    """The examples GET transaction-types hands to AI clients must be accepted as written."""
    from bookkeeper.services.business import EXAMPLES, INPUT_MODELS
    from bookkeeper.services.inputs import TransactionIn

    for code, example in EXAMPLES.items():
        body = TransactionIn.model_validate(example)
        INPUT_MODELS[code].model_validate(body.inputs)
