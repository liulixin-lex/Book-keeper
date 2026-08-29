import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.amounts import RATE_SCALE, to_e12
from app.config import Settings, get_settings
from app.models import FxRate


class FxProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class DisplayRate:
    currency: str
    cny_per_unit_e12: int
    source: str
    effective_at: datetime
    fetched_at: datetime
    is_stale: bool


SUPPORTED_FX_CURRENCIES = (
    "USD",
    "EUR",
    "GBP",
    "HKD",
    "JPY",
    "KRW",
    "SGD",
    "PHP",
)


def validate_supported_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in SUPPORTED_FX_CURRENCIES:
        raise FxProviderError(f"暂不支持币种 {normalized}")
    return normalized


def fixed_rate(currency: str, target: str = "CNY") -> int | None:
    normalized = currency.upper()
    if normalized == target.upper() or normalized == "UPSTREAM_CREDIT":
        return RATE_SCALE
    return None


def get_cached_rate(
    session: Session, currency: str, effective_date: date, *, target: str = "CNY"
) -> FxRate | None:
    start = datetime.combine(effective_date, time.min, tzinfo=UTC)
    end = datetime.combine(effective_date, time.max, tzinfo=UTC)
    return session.scalar(
        select(FxRate)
        .where(
            FxRate.base_currency == currency.upper(),
            FxRate.quote_currency == target.upper(),
            FxRate.effective_at.between(start, end),
        )
        .order_by(FxRate.effective_at.desc(), FxRate.fetched_at.desc())
        .limit(1)
    )


def _frankfurter_rate(
    currency: str, effective_date: date, client: httpx.Client
) -> tuple[str, str, date]:
    response = client.get(
        f"https://api.frankfurter.dev/v2/rate/{currency}/CNY",
        params={"date": effective_date.isoformat()},
    )
    response.raise_for_status()
    data = json.loads(response.content, parse_float=Decimal)
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict):
        raise FxProviderError("Frankfurter response did not contain a rate")
    value = row.get("rate")
    if value is None:
        raise FxProviderError("Frankfurter response did not contain a rate")
    provider_date = date.fromisoformat(str(row.get("date") or effective_date.isoformat()))
    return format(Decimal(str(value)), "f"), "Frankfurter", provider_date


def _latest_cached_rate(session: Session, currency: str) -> FxRate | None:
    return session.scalar(
        select(FxRate)
        .where(
            FxRate.base_currency == currency,
            FxRate.quote_currency == "CNY",
        )
        .order_by(FxRate.effective_at.desc(), FxRate.fetched_at.desc())
        .limit(1)
    )


def _same_day_manual_rate(
    session: Session, currency: str, effective_date: date, timezone: ZoneInfo
) -> FxRate | None:
    manual = session.scalar(
        select(FxRate)
        .where(
            FxRate.base_currency == currency,
            FxRate.quote_currency == "CNY",
            FxRate.rate_type == "manual_override",
        )
        .order_by(FxRate.effective_at.desc(), FxRate.fetched_at.desc())
        .limit(1)
    )
    if manual is None:
        return None
    manual_time = manual.effective_at
    if manual_time.tzinfo is None:
        manual_time = manual_time.replace(tzinfo=UTC)
    return manual if manual_time.astimezone(timezone).date() == effective_date else None


def resolve_display_rate(
    session: Session,
    currency: str,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> DisplayRate:
    current = settings or get_settings()
    normalized = currency.strip().upper()
    now = datetime.now(UTC)
    if normalized == "CNY":
        return DisplayRate(
            currency="CNY",
            cny_per_unit_e12=RATE_SCALE,
            source="fixed-rule",
            effective_at=now,
            fetched_at=now,
            is_stale=False,
        )
    normalized = validate_supported_currency(normalized)
    local_timezone = ZoneInfo(current.timezone)
    today = now.astimezone(local_timezone).date()
    manual = _same_day_manual_rate(session, normalized, today, local_timezone)
    if manual is not None:
        return DisplayRate(
            currency=normalized,
            cny_per_unit_e12=manual.rate_e12,
            source=manual.source,
            effective_at=manual.effective_at,
            fetched_at=manual.fetched_at,
            is_stale=False,
        )

    own_client = client is None
    http_client = client or httpx.Client(timeout=20)
    try:
        rate_text, source, provider_date = _frankfurter_rate(normalized, today, http_client)
        return DisplayRate(
            currency=normalized,
            cny_per_unit_e12=to_e12(rate_text),
            source=source,
            effective_at=datetime.combine(provider_date, time.min, tzinfo=UTC),
            fetched_at=now,
            is_stale=False,
        )
    except (
        FxProviderError,
        httpx.HTTPError,
        InvalidOperation,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
    ) as exc:
        cached = _latest_cached_rate(session, normalized)
        if cached is None:
            if isinstance(exc, FxProviderError):
                raise
            raise FxProviderError(str(exc)) from exc
        return DisplayRate(
            currency=normalized,
            cny_per_unit_e12=cached.rate_e12,
            source=cached.source,
            effective_at=cached.effective_at,
            fetched_at=cached.fetched_at,
            is_stale=True,
        )
    finally:
        if own_client:
            http_client.close()


def fetch_and_store_rate(
    session: Session,
    currency: str,
    effective_date: date,
    *,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> FxRate:
    current = settings or get_settings()
    normalized = currency.upper()
    if normalized != "CNY":
        normalized = validate_supported_currency(normalized)
    local_timezone = ZoneInfo(current.timezone)
    today = datetime.now(local_timezone).date()
    manual = _same_day_manual_rate(session, normalized, effective_date, local_timezone)
    if manual is not None:
        return manual
    cached = get_cached_rate(session, normalized, effective_date)
    if cached is not None and (effective_date < today or cached.rate_type == "manual_override"):
        return cached
    fixed = fixed_rate(normalized)
    if fixed is not None:
        cached = get_cached_rate(session, normalized, effective_date)
        if cached is not None:
            return cached
        rate = FxRate(
            base_currency=normalized,
            quote_currency="CNY",
            rate_e12=fixed,
            effective_at=datetime.combine(effective_date, time.min, tzinfo=UTC),
            source="fixed-rule",
            rate_type="fixed",
        )
        session.add(rate)
        session.commit()
        session.refresh(rate)
        return rate

    own_client = client is None
    http_client = client or httpx.Client(timeout=20)
    try:
        rate_text, source, _provider_date = _frankfurter_rate(
            normalized, effective_date, http_client
        )
        rate_type = "daily_reference"
    except (
        FxProviderError,
        httpx.HTTPError,
        InvalidOperation,
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
    ) as exc:
        if isinstance(exc, FxProviderError):
            raise
        raise FxProviderError(str(exc)) from exc
    finally:
        if own_client:
            http_client.close()

    effective_at = (
        datetime.now(UTC)
        if effective_date == today
        else datetime.combine(effective_date, time.min, tzinfo=UTC)
    )
    while session.scalar(
        select(FxRate.id).where(
            FxRate.base_currency == normalized,
            FxRate.quote_currency == "CNY",
            FxRate.effective_at == effective_at,
            FxRate.source == source,
            FxRate.rate_type == rate_type,
        )
    ):
        effective_at += timedelta(microseconds=1)
    rate = FxRate(
        base_currency=normalized,
        quote_currency="CNY",
        rate_e12=to_e12(rate_text),
        effective_at=effective_at,
        source=source,
        rate_type=rate_type,
    )
    session.add(rate)
    session.commit()
    session.refresh(rate)
    return rate


def fetch_latest_supported_rates(
    session: Session, *, client: httpx.Client | None = None
) -> list[FxRate]:
    own_client = client is None
    http_client = client or httpx.Client(timeout=20)
    try:
        response = http_client.get(
            "https://api.frankfurter.dev/v2/rates",
            params={"base": "CNY", "quotes": ",".join(SUPPORTED_FX_CURRENCIES)},
        )
        response.raise_for_status()
        rows = json.loads(response.content, parse_float=Decimal)
        if not isinstance(rows, list):
            raise FxProviderError("Frankfurter response was not a rate list")

        refreshed: list[FxRate] = []
        now = datetime.now(UTC)
        for row in rows:
            currency = validate_supported_currency(str(row.get("quote", "")))
            source_rate = Decimal(str(row.get("rate")))
            if source_rate <= 0:
                raise FxProviderError(f"Currency {currency} returned an invalid rate")
            effective_date = date.fromisoformat(str(row.get("date")))
            effective_at = datetime.combine(effective_date, time.min, tzinfo=UTC)
            rate_e12 = to_e12(format(Decimal(1) / source_rate, "f"))
            rate = session.scalar(
                select(FxRate).where(
                    FxRate.base_currency == currency,
                    FxRate.quote_currency == "CNY",
                    FxRate.effective_at == effective_at,
                    FxRate.source == "Frankfurter",
                    FxRate.rate_type == "daily_reference",
                )
            )
            if rate is None:
                rate = FxRate(
                    base_currency=currency,
                    quote_currency="CNY",
                    rate_e12=rate_e12,
                    effective_at=effective_at,
                    source="Frankfurter",
                    rate_type="daily_reference",
                )
                session.add(rate)
            else:
                rate.rate_e12 = rate_e12
                rate.fetched_at = now
            refreshed.append(rate)
        session.commit()
        for rate in refreshed:
            session.refresh(rate)
        return sorted(refreshed, key=lambda item: item.base_currency)
    except (
        FxProviderError,
        httpx.HTTPError,
        InvalidOperation,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        session.rollback()
        if isinstance(exc, FxProviderError):
            raise
        raise FxProviderError(str(exc)) from exc
    finally:
        if own_client:
            http_client.close()
