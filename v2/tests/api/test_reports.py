"""Business reports over a small but complete month of activity."""

from __future__ import annotations

from typing import Any

import pytest

from tests.api.conftest import login, write_headers
from tests.api.test_business import biz, counterparty, money, rule


@pytest.fixture
def month(client, world) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    csrf = login(client, world.admin_email)
    b = world.book_id
    rule(
        client,
        b,
        csrf,
        code="liandong",
        rate="0.03",
        transaction_types=["sale"],
        channels=["liandong"],
        valid_from="2026-01-01",
    )
    counterparty(client, b, csrf, "relay-a.example")
    counterparty(client, b, csrf, "Vultr", category="cloud_vendor")
    sale = biz(client, b, csrf, "sale", {"gross": money("100"), "channel": "liandong"}, effective_date="2026-10-01")
    biz(
        client,
        b,
        csrf,
        "sale",
        {"gross": money("50"), "fee": money("1"), "channel": "yunmao"},
        effective_date="2026-10-02",
    )
    biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("50"), "total": money("51.50"), "credit_quantity": "55", "channel": "direct"},
        counterparty="relay-a.example",
        effective_date="2026-10-02",
    )
    biz(
        client,
        b,
        csrf,
        "sale_refund",
        {"original": sale["id"], "amount": money("20"), "fee_refunded": money("0.60")},
        effective_date="2026-10-03",
    )
    biz(
        client,
        b,
        csrf,
        "expense",
        {"amount": money("80"), "category": "5401.04"},
        counterparty="Vultr",
        effective_date="2026-10-05",
    )
    biz(client, b, csrf, "expense", {"amount": money("30"), "category": "广告推广费"}, effective_date="2026-10-06")
    return {"csrf": csrf, "sale": sale}


def get(client, world, path: str, **params: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    response = client.get(f"/api/v1/books/{world.book_id}/reports/{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


OCT = {"date_from": "2026-10-01", "date_to": "2026-10-31"}


def test_income_statement(client, world, month) -> None:
    pnl = get(client, world, "income-statement", **OCT)
    s = {k: v["minor"] for k, v in pnl["summary"].items()}
    assert (s["revenue"], s["cost"], s["gross_profit"]) == (13000, 13000, 0)
    assert (s["selling"], s["finance"], s["operating_profit"], s["net_profit"]) == (3000, 490, -3490, -3490)
    codes = [line["code"] for line in pnl["lines"]]
    assert codes.index("revenue") < codes.index("5001.01") < codes.index("cost") < codes.index("gross_profit")
    assert codes[-1] == "net_profit"
    fee_line = next(line for line in pnl["lines"] if line["code"] == "5603.01")
    assert fee_line["drilldown"]["transactions"]["account"] == "5603.01"

    by_month = get(client, world, "income-statement", date_from="2026-09-01", date_to="2026-10-31", columns="month")
    assert by_month["columns"] == ["2026-10"]
    assert by_month["lines"][-1]["columns"]["2026-10"]["minor"] == -3490


def test_operations_sales_fees_and_credit_purchases(client, world, month) -> None:
    ops = get(client, world, "operations", **OCT)
    first = ops["rows"][0]
    assert first["period"] == "2026-10-01"
    assert {k: first["values"][k]["minor"] for k in ("sales", "fees", "profit")} == {
        "sales": 10000,
        "fees": 300,
        "profit": 9700,
    }
    assert first["counts"] == {"sale": 1}
    assert first["drilldown"]["transactions"]["date_to"] == "2026-10-01"
    assert ops["totals"]["profit"]["minor"] == -3490
    monthly = get(client, world, "operations", period="month", **OCT)
    assert monthly["rows"][0]["values"]["credit_cost"]["minor"] == 5000
    assert monthly["rows"][0]["values"]["other_cost"]["minor"] == 8000

    sales = get(client, world, "sales", **OCT)
    liandong = sales["rows"][0]
    assert liandong["channel"]["code"] == "liandong"
    assert (liandong["orders"], liandong["refund_count"]) == (1, 1)
    assert [liandong[k]["minor"] for k in ("gross", "refunds", "net_sales", "fees", "net_received")] == [
        10000,
        2000,
        8000,
        240,
        7760,
    ]
    assert liandong["fee_rate"] == "0.0300"
    assert sales["totals"]["net_sales"]["minor"] == 13000

    fees = get(client, world, "fees", **OCT)
    rates = {(r["channel"]["code"], r["transaction_type"]["code"]): r["effective_rate"] for r in fees["rows"]}
    assert rates == {
        ("liandong", "sale"): "0.0300",
        ("liandong", "sale_refund"): "0.0300",
        ("yunmao", "sale"): "0.0200",
        ("direct", "credit_purchase"): "0.0300",
    }
    assert fees["totals"]["fee"]["minor"] == 490

    credit = get(client, world, "credit-purchases", **OCT)
    site = credit["rows"][0]
    assert site["site"]["name"] == "relay-a.example"
    assert (site["purchases"], site["face"]["minor"], site["fees"]["minor"], site["total_paid"]["minor"]) == (
        1,
        5000,
        150,
        5150,
    )
    assert (site["credit_quantity"], site["cost_per_credit"]) == ("55", "0.9364")
    listed = client.get(f"/api/v1/books/{world.book_id}/transactions", params=site["drilldown"]["transactions"]).json()[
        "data"
    ]
    assert [t["type"] for t in listed] == ["credit_purchase"]


def test_generic_query_groups_and_drilldown(client, world, month) -> None:
    data = get(client, world, "query", classifications="expense", group_by="account", **OCT)
    amounts = {r["keys"]["account"]["code"]: r["values"]["base_amount"]["minor"] for r in data["rows"]}
    assert amounts == {"5401.01": 5000, "5401.04": 8000, "5601.01": 3000, "5603.01": 490}
    assert data["totals"]["base_amount"]["minor"] == 16490
    row = next(r for r in data["rows"] if r["keys"]["account"]["code"] == "5401.04")
    listed = client.get(f"/api/v1/books/{world.book_id}/transactions", params=row["drilldown"]["transactions"])
    assert [t["description"] for t in listed.json()["data"]] == ["Vultr · 服务器与网络"]

    channels = get(client, world, "query", accounts="5001", group_by=["month", "channel"], **OCT)
    assert [
        (r["keys"]["month"], r["keys"]["channel"]["code"], r["values"]["base_amount"]["minor"])
        for r in channels["rows"]
    ] == [("2026-10", "liandong", 8000), ("2026-10", "yunmao", 5000)]
    assert channels["rows"][0]["drilldown"]["transactions"]["channel"] == "liandong"

    native = get(client, world, "query", accounts="1012.01", measures="amount,debit,credit", **OCT)
    assert native["rows"][0]["keys"]["commodity"] == "CNY"
    assert native["rows"][0]["values"]["amount"]["minor"] == -3490

    bad = client.get(f"/api/v1/books/{world.book_id}/reports/query", params={"group_by": "colour", **OCT})
    assert bad.status_code == 422 and "colour" in bad.json()["detail"]


def test_summary_and_catalogue(client, world, month) -> None:
    summary = get(client, world, "summary", **OCT)
    assert summary["profit"]["net_profit"]["minor"] == -3490
    assert summary["funds"] == [
        {"commodity": "CNY", "amount": summary["funds"][0]["amount"], "base": summary["funds"][0]["base"]}
    ]
    assert summary["funds"][0]["amount"]["minor"] == -3490
    assert summary["top_channels"][0]["channel"]["code"] == "liandong"
    assert summary["top_sites"][0]["site"]["name"] == "relay-a.example"
    assert summary["attention"] == {"estimated": 0, "suspense_balance": summary["attention"]["suspense_balance"]}
    assert summary["attention"]["suspense_balance"]["minor"] == 0
    catalogue = client.get(f"/api/v1/books/{world.book_id}/reports").json()["data"]
    assert {c["path"] for c in catalogue} == {
        "reports/summary",
        "reports/income-statement",
        "reports/operations",
        "reports/sales",
        "reports/fees",
        "reports/credit-purchases",
        "reports/trial-balance",
        "reports/query",
    }


def test_edits_and_deletes_net_out_in_reports(client, world, month) -> None:
    csrf = month["csrf"]
    response = client.patch(
        f"/api/v1/books/{world.book_id}/transactions/{month['sale']['id']}",
        headers=write_headers(csrf),
        json={"inputs": {"gross": money("110")}},
    )
    assert response.status_code == 200, response.text
    pnl = get(client, world, "income-statement", **OCT)
    assert pnl["summary"]["revenue"]["minor"] == 14000
    credit = get(client, world, "query", accounts="5401.01", measures="base_amount,quantity", **OCT)
    assert credit["rows"][0]["values"]["quantity"] == "55"
    vultr = client.get(f"/api/v1/books/{world.book_id}/transactions", params={"q": "Vultr"}).json()["data"][0]
    deleted = client.delete(
        f"/api/v1/books/{world.book_id}/transactions/{vultr['number']}", headers=write_headers(csrf)
    )
    assert deleted.status_code == 200, deleted.text
    expenses = get(client, world, "query", classifications="expense", group_by="account", **OCT)
    assert "5401.04" not in {r["keys"]["account"]["code"] for r in expenses["rows"]}
    ops = get(client, world, "operations", period="month", **OCT)
    assert ops["rows"][0]["values"]["other_cost"]["minor"] == 0
