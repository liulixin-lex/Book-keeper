from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.amounts import to_e12
from app.config import Settings
from app.models import FxRate
from app.services.fx import fetch_and_store_rate, fetch_latest_supported_rates


def test_open_exchange_rate_keeps_decimal_precision_and_freezes_history(
    db_session: Session,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=b'{"rates":{"USD":1,"CNY":7.2345678901234}}',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = Settings(openexchangerates_app_id="test-app-id", _env_file=None)
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
    settings = Settings(openexchangerates_app_id=None, _env_file=None)
    today = date.today()
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
    selected = fetch_and_store_rate(
        db_session,
        "USD",
        date.today(),
        settings=Settings(openexchangerates_app_id=None, _env_file=None),
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
