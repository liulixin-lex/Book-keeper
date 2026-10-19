"""Exchange-rate selection and conversion (docs/05-posting-engine.md §7.1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from bookkeeper.domain.money import round_minor

DEFAULT_PIVOTS = ("USD", "EUR")
RATE_TYPE_PRIORITY = {"manual": 0, "actual": 1, "reference": 2, "derived": 3}


@dataclass(frozen=True)
class RateRecord:
    base: str
    quote: str
    rate_date: date
    rate: Decimal
    rate_type: str = "reference"
    source: str = "manual"
    id: str | None = None


@dataclass(frozen=True)
class PriceRule:
    commodity: str
    quote: str
    rate: Decimal
    valid_from: date
    valid_to: date | None = None
    purpose: str = "conversion"
    id: str | None = None


@dataclass(frozen=True)
class FxQuote:
    base: str
    quote: str
    rate: Decimal
    source: str  # actual / table / price_rule / derived
    rate_date: date | None = None
    rate_id: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    via: str | None = None


def convert_minor(amount_minor: int, from_scale: int, rate: Decimal, to_scale: int, mode: str) -> int:
    """amount (minor, from_scale) × rate → minor units of to_scale, rounded once."""
    return round_minor(Decimal(amount_minor) * rate * Decimal(1).scaleb(to_scale - from_scale), mode)


def _direct(
    base: str, quote: str, on: date, lookback: int, records: Sequence[RateRecord]
) -> tuple[Decimal, RateRecord, bool] | None:
    """Best direct (or inverse) rate within [on - lookback, on]; returns (rate, record, inverted)."""
    earliest = on - timedelta(days=lookback)
    candidates: list[tuple[date, int, Decimal, RateRecord, bool]] = []
    for r in records:
        if not earliest <= r.rate_date <= on or r.rate <= 0:
            continue
        priority = RATE_TYPE_PRIORITY.get(r.rate_type, 9)
        if r.base == base and r.quote == quote:
            candidates.append((r.rate_date, -priority, r.rate, r, False))
        elif r.base == quote and r.quote == base:
            candidates.append((r.rate_date, -priority, Decimal(1) / r.rate, r, True))
    if not candidates:
        return None
    best = max(candidates, key=lambda c: (c[0], c[1], not c[4]))
    return best[2], best[3], best[4]


def select_rate(
    base: str,
    quote: str,
    on: date,
    *,
    lookback_days: int,
    records: Sequence[RateRecord],
    price_rules: Sequence[PriceRule] = (),
    pivots: Sequence[str] = DEFAULT_PIVOTS,
) -> FxQuote | None:
    """Rate to convert 1 unit of ``base`` into ``quote`` on date ``on``, or None if unavailable."""
    if base == quote:
        return FxQuote(base, quote, Decimal(1), "identity", on)
    for rule in price_rules:
        if rule.purpose != "conversion":
            continue
        in_range = rule.valid_from <= on and (rule.valid_to is None or on <= rule.valid_to)
        if in_range and rule.commodity == base and rule.quote == quote:
            return FxQuote(base, quote, rule.rate, "price_rule", rule.valid_from, rule.id)
        if in_range and rule.commodity == quote and rule.quote == base:
            return FxQuote(base, quote, Decimal(1) / rule.rate, "price_rule", rule.valid_from, rule.id)
    found = _direct(base, quote, on, lookback_days, records)
    if found is not None:
        rate, record, _ = found
        warnings = () if record.rate_date == on else (f"FX_RATE_STALE:{record.rate_date.isoformat()}",)
        return FxQuote(base, quote, rate, "table", record.rate_date, record.id, warnings)
    for pivot in pivots:
        if pivot in (base, quote):
            continue
        leg1 = _direct(base, pivot, on, lookback_days, records)
        leg2 = _direct(pivot, quote, on, lookback_days, records)
        if leg1 and leg2:
            older = min(leg1[1].rate_date, leg2[1].rate_date)
            return FxQuote(
                base,
                quote,
                leg1[0] * leg2[0],
                "derived",
                older,
                None,
                (f"FX_RATE_DERIVED:{pivot}",),
                via=pivot,
            )
    return None
