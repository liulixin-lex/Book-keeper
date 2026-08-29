from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.amounts import to_e12
from app.config import Settings
from app.models import FxRate
from app.services.fx import (
    FxProviderError,
    fetch_and_store_rate,
    fetch_latest_supported_rates,
    resolve_display_rate,
)


def test_frankfurter_rate_keeps_decimal_precision_and_freezes_history(
    db_session: Session,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b'{"date":"2026-08-28","base":"USD","quote":"CNY","rate":7.2345678901234}',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None)
    historical_date = datetime.now(UTC).date() - timedelta(days=1)
    first = fetch_and_store_rate(
        db_session,
        "USD",
        historical_date,
        settings=settings,
        client=client,
    )
    second = fetch_and_store_rate(
        db_session,
        "USD",
        historical_date,
        settings=settings,
        client=client,
    )
    client.close()

    assert first.id == second.id
    assert first.rate_e12 == to_e12("7.2345678901234")
    assert calls == 1


def test_latest_rate_creates_new_timestamped_snapshots(db_session: Session) -> None:
    values = iter((b'{"rate":7.1}', b'{"rate":7.2}'))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=next(values))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    first = fetch_and_store_rate(db_session, "USD", today, settings=settings, client=client)
    second = fetch_and_store_rate(db_session, "USD", today, settings=settings, client=client)
    client.close()

    assert first.id != second.id
    assert first.rate_e12 == to_e12("7.1")
    assert second.rate_e12 == to_e12("7.2")
    assert db_session.scalar(select(func.count(FxRate.id))) == 2


def test_same_day_manual_override_is_used_for_bookkeeping(db_session: Session) -> None:
    manual = FxRate(
        base_currency="USD",
        quote_currency="CNY",
        rate_e12=to_e12("7.33"),
        effective_at=datetime.now(UTC),
        source="manual",
        rate_type="manual_override",
    )
    db_session.add(manual)
    db_session.commit()

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b'{"rate":7.1}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(_env_file=None)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    selected = fetch_and_store_rate(
        db_session,
        "USD",
        today,
        settings=settings,
        client=client,
    )
    client.close()

    assert selected.id == manual.id
    assert selected.rate_e12 == to_e12("7.33")
    assert calls == 0


def test_refresh_supported_rates_uses_public_cny_reference_data(
    db_session: Session,
) -> None:
    payload = b"""[
      {"date":"2026-08-28","base":"CNY","quote":"USD","rate":0.14},
      {"date":"2026-08-28","base":"CNY","quote":"EUR","rate":0.12},
      {"date":"2026-08-28","base":"CNY","quote":"GBP","rate":0.10},
      {"date":"2026-08-28","base":"CNY","quote":"HKD","rate":1.08},
      {"date":"2026-08-28","base":"CNY","quote":"JPY","rate":20},
      {"date":"2026-08-28","base":"CNY","quote":"KRW","rate":200},
      {"date":"2026-08-28","base":"CNY","quote":"SGD","rate":0.18},
      {"date":"2026-08-28","base":"CNY","quote":"PHP","rate":9}
    ]"""

    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    )
    rates = fetch_latest_supported_rates(db_session, client=client)
    client.close()

    assert [rate.base_currency for rate in rates] == [
        "EUR",
        "GBP",
        "HKD",
        "JPY",
        "KRW",
        "PHP",
        "SGD",
        "USD",
    ]
    usd = next(rate for rate in rates if rate.base_currency == "USD")
    assert usd.rate_e12 == to_e12("7.142857142857142857142857143")
    assert usd.source == "Frankfurter"
    assert usd.rate_type == "daily_reference"


def test_display_rate_uses_fixed_cny_without_network(db_session: Session) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rate = resolve_display_rate(
        db_session,
        "CNY",
        settings=Settings(_env_file=None),
        client=client,
    )
    client.close()

    assert rate.cny_per_unit_e12 == to_e12("1")
    assert rate.is_stale is False
    assert calls == 0


def test_display_rate_uses_live_frankfurter_value(db_session: Session) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                content=b'{"date":"2026-08-29","base":"HKD","quote":"CNY","rate":0.85614}',
            )
        )
    )
    rate = resolve_display_rate(
        db_session,
        "HKD",
        settings=Settings(_env_file=None),
        client=client,
    )
    client.close()

    assert rate.currency == "HKD"
    assert rate.cny_per_unit_e12 == to_e12("0.85614")
    assert rate.source == "Frankfurter"
    assert rate.is_stale is False
    assert rate.effective_at.date() == date(2026, 8, 29)


def test_display_rate_falls_back_to_latest_cached_value(db_session: Session) -> None:
    cached = FxRate(
        base_currency="USD",
        quote_currency="CNY",
        rate_e12=to_e12("7.08"),
        effective_at=datetime.now(UTC) - timedelta(days=1),
        source="Frankfurter",
        rate_type="daily_reference",
    )
    db_session.add(cached)
    db_session.commit()
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503)))

    rate = resolve_display_rate(
        db_session,
        "USD",
        settings=Settings(_env_file=None),
        client=client,
    )
    client.close()

    assert rate.cny_per_unit_e12 == cached.rate_e12
    assert rate.effective_at == cached.effective_at
    assert rate.is_stale is True


def test_display_rate_fails_when_frankfurter_and_cache_are_unavailable(
    db_session: Session,
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(503)))
    with pytest.raises(FxProviderError):
        resolve_display_rate(
            db_session,
            "USD",
            settings=Settings(_env_file=None),
            client=client,
        )
    client.close()
