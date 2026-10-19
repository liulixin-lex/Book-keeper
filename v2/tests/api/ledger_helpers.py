"""Helpers for ledger API tests."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.conftest import write_headers


def line(account: str, side: str, amount: str, commodity: str = "CNY", **extra: Any) -> dict[str, Any]:
    return {"account": account, "side": side, "amount": {"amount": amount, "commodity": commodity}} | extra


def journal(
    client: TestClient,
    book_id: str,
    csrf: str,
    lines: list[dict[str, Any]],
    *,
    effective_date: str = "2026-10-18",
    description: str = "调整 · 测试",
    expect: int = 201,
    **extra: Any,
) -> dict[str, Any]:
    body = {
        "type": "manual_journal",
        "effective_date": effective_date,
        "description": description,
        "lines": lines,
    } | extra
    response = client.post(f"/api/v1/books/{book_id}/transactions", json=body, headers=write_headers(csrf))
    assert response.status_code == expect, response.text
    return response.json()["data"] if expect < 300 else response.json()


def delete(client: TestClient, book_id: str, csrf: str, ref: str, expect: int = 200, **body: Any) -> dict[str, Any]:
    response = client.request(
        "DELETE", f"/api/v1/books/{book_id}/transactions/{ref}", json=body or None, headers=write_headers(csrf)
    )
    assert response.status_code == expect, response.text
    return response.json()["data"] if expect < 300 else response.json()


def sale(
    client: TestClient,
    book_id: str,
    csrf: str,
    gross: str = "100.00",
    fee: str = "3.00",
    date: str = "2026-10-18",
    **extra: Any,
) -> dict[str, Any]:
    from decimal import Decimal

    net = str(Decimal(gross) - Decimal(fee))
    return journal(
        client,
        book_id,
        csrf,
        [
            line("1012.01", "debit", net),
            line("5603.01", "debit", fee),
            line("5001.01", "credit", gross, dimensions={"channel": "liandong"}),
        ],
        effective_date=date,
        description="链动 · API 额度销售",
        **extra,
    )
