"""Frankfurter (ECB reference rates) client. Network access is injected for tests."""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

DEFAULT_BASE_URL = "https://api.frankfurter.dev/v1"
Fetcher = Callable[[str], Any]


def http_get_json(url: str, timeout: float = 10.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "bookkeeper/2"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


@dataclass(frozen=True)
class FetchedRate:
    base: str
    quote: str
    rate_date: date
    rate: Decimal
    raw: dict[str, Any]


def fetch(
    base: str,
    quotes: Sequence[str],
    on: date,
    *,
    base_url: str = DEFAULT_BASE_URL,
    fetcher: Fetcher = http_get_json,
) -> list[FetchedRate]:
    """Rates base→quote for ``on`` (Frankfurter returns the latest business day ≤ on)."""
    url = f"{base_url.rstrip('/')}/{on.isoformat()}?base={base}&symbols={','.join(quotes)}"
    payload = fetcher(url)
    rate_date = date.fromisoformat(payload["date"])
    results = []
    for quote, value in payload.get("rates", {}).items():
        results.append(
            FetchedRate(
                base,
                quote,
                rate_date,
                Decimal(str(value)),
                {"url": url, "response_date": payload["date"]},
            )
        )
    return results
