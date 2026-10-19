from datetime import date
from decimal import Decimal

from bookkeeper.domain.fx import PriceRule, RateRecord, convert_minor, select_rate

D = date(2026, 10, 18)


def test_identity_and_direct() -> None:
    assert select_rate("CNY", "CNY", D, lookback_days=7, records=[]).rate == 1
    q = select_rate("GBP", "CNY", D, lookback_days=7, records=[RateRecord("GBP", "CNY", D, Decimal("9.5"), id="fxr_1")])
    assert q.rate == Decimal("9.5") and q.source == "table" and q.rate_id == "fxr_1" and not q.warnings


def test_inverse_rate() -> None:
    q = select_rate("GBP", "CNY", D, lookback_days=7, records=[RateRecord("CNY", "GBP", D, Decimal("0.1"))])
    assert q.rate == Decimal(10)


def test_lookback_marks_stale_and_respects_window() -> None:
    old = RateRecord("GBP", "CNY", date(2026, 10, 16), Decimal("9.4"))
    q = select_rate("GBP", "CNY", D, lookback_days=7, records=[old])
    assert q.warnings == ("FX_RATE_STALE:2026-10-16",)
    assert select_rate("GBP", "CNY", D, lookback_days=1, records=[old]) is None


def test_manual_beats_reference_same_day_and_newest_wins() -> None:
    records = [
        RateRecord("GBP", "CNY", D, Decimal("9.5"), "reference"),
        RateRecord("GBP", "CNY", D, Decimal("9.6"), "manual"),
        RateRecord("GBP", "CNY", date(2026, 10, 17), Decimal("9.0"), "manual"),
    ]
    assert select_rate("GBP", "CNY", D, lookback_days=7, records=records).rate == Decimal("9.6")


def test_derived_via_pivot() -> None:
    records = [RateRecord("HKD", "USD", D, Decimal("0.128")), RateRecord("USD", "CNY", D, Decimal("7.1"))]
    q = select_rate("HKD", "CNY", D, lookback_days=7, records=records)
    assert q.source == "derived" and q.via == "USD" and q.rate == Decimal("0.128") * Decimal("7.1")


def test_price_rule_for_credit_commodity() -> None:
    rule = PriceRule("UCR", "CNY", Decimal(1), date(2026, 5, 1))
    q = select_rate("UCR", "CNY", D, lookback_days=7, records=[], price_rules=[rule])
    assert q.source == "price_rule" and q.rate == 1
    assert select_rate("UCR", "CNY", date(2026, 4, 1), lookback_days=7, records=[], price_rules=[rule]) is None


def test_convert_minor_rounds_once() -> None:
    assert convert_minor(1915, 2, Decimal("9.5127"), 2, "half_up") == 18217
    assert convert_minor(12345, 4, Decimal(1), 2, "half_up") == 123
    assert convert_minor(-85, 2, Decimal("9.5127"), 2, "half_up") == -809
