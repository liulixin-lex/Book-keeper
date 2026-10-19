"""No hard bindings: currencies are data, channels accept names and aliases, counterparties carry
defaults, fee rules cover every fee-bearing type."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.conftest import login, write_headers
from tests.api.test_business import biz, money, rule


def post(client: TestClient, path: str, csrf: str, body: dict[str, Any], expect: int = 201) -> dict[str, Any]:
    response = client.post(path, headers=write_headers(csrf), json=body)
    assert response.status_code == expect, response.text
    data: dict[str, Any] = response.json()["data"] if expect < 300 else response.json()
    return data


def test_currencies_are_data(client, world) -> None:
    csrf = login(client, world.admin_email)
    base = f"/api/v1/books/{world.book_id}"
    jpy = post(client, f"{base}/commodities", csrf, {"code": "jpy", "name": "日元", "scale": 0, "symbol": "¥"})
    assert jpy == {"code": "JPY", "name": "日元", "kind": "fiat", "scale": 0, "symbol": "¥", "is_active": True}
    sale = biz(
        client,
        world.book_id,
        csrf,
        "sale",
        {"gross": money("1200", "JPY"), "fee": money("0", "JPY"), "channel": "stripe", "fx_rate": "0.048"},
    )
    assert sale["entries"][0]["lines"][-1]["amount"]["display"].startswith("-¥1,200")
    used = client.patch(f"{base}/commodities/JPY", headers=write_headers(csrf), json={"scale": 2})
    assert used.status_code == 409 and "小数位" in used.json()["detail"]
    post(client, f"{base}/commodities", csrf, {"code": "USDT", "name": "泰达币", "kind": "other", "scale": 2})
    fixed = client.patch(f"{base}/commodities/USDT", headers=write_headers(csrf), json={"scale": 6})
    assert fixed.status_code == 200 and fixed.json()["data"]["scale"] == 6  # unused: still adjustable
    off = client.patch(f"{base}/commodities/JPY", headers=write_headers(csrf), json={"is_active": False})
    assert off.status_code == 200
    blocked = biz(client, world.book_id, csrf, "sale", {"gross": money("100", "JPY"), "channel": "stripe"}, expect=422)
    assert "不存在或已停用" in blocked["errors"][0]["message"]
    base_off = client.patch(f"{base}/commodities/CNY", headers=write_headers(csrf), json={"is_active": False})
    assert base_off.status_code == 409 and "本位币" in base_off.json()["detail"]
    duplicate = post(client, f"{base}/commodities", csrf, {"code": "JPY", "name": "x"}, expect=409)
    assert duplicate["code"] == "CONFLICT"


def test_channels_by_name_and_alias(client, world) -> None:
    csrf = login(client, world.admin_email)
    by_name = biz(client, world.book_id, csrf, "sale", {"gross": money("10"), "channel": "链动"})
    by_alias = biz(client, world.book_id, csrf, "sale", {"gross": money("10"), "channel": "链动小铺"})
    assert by_name["channel"]["code"] == by_alias["channel"]["code"] == "liandong"
    unknown = biz(client, world.book_id, csrf, "sale", {"gross": money("10"), "channel": "淘宝"}, expect=422)
    assert "可用：" in unknown["errors"][0]["message"] and "链动（liandong）" in unknown["errors"][0]["message"]
    clash = client.post(
        f"/api/v1/books/{world.book_id}/dimension-types/channel/values",
        headers=write_headers(csrf),
        json={"code": "ld2", "name": "第二链动", "aliases": ["链动小铺"]},
    )
    assert clash.status_code == 409 and "liandong" in clash.json()["detail"]


def test_counterparty_defaults_fill_type_and_channel(client, world) -> None:
    csrf = login(client, world.admin_email)
    base = f"/api/v1/books/{world.book_id}"
    site = post(
        client,
        f"{base}/counterparties",
        csrf,
        {
            "name": "relay-b.example",
            "category": "upstream_site",
            "default_type": "credit_purchase",
            "default_channel": "链动",
        },
    )
    assert site["defaults"] == {
        "type": "credit_purchase",
        "channel": {"id": site["defaults"]["channel"]["id"], "code": "liandong", "name": "链动"},
    }
    rule(
        client,
        world.book_id,
        csrf,
        code="relay_ld",
        rate="0.03",
        transaction_types=["credit_purchase"],
        channels=["链动"],
        counterparties=["relay-b.example"],
        valid_from="2026-01-01",
    )
    details = client.get(f"{base}/counterparties/{site['id']}").json()["data"]
    assert [r["code"] for r in details["fee_rules"]] == ["relay_ld"]
    # "relay-b.example, face ¥50" is enough: type and channel come from the counterparty, the fee from its rule
    created = post(
        client,
        f"{base}/transactions",
        csrf,
        {"counterparty": "relay-b.example", "effective_date": "2026-10-18", "inputs": {"face": money("50")}},
    )
    assert created["type"] == "credit_purchase" and created["channel"]["code"] == "liandong"
    assert created["computed"]["fee"] == 150 and created["provenance"]["defaults"] == {
        "type": "counterparty",
        "channel": "counterparty",
    }
    explicit = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"face": money("50"), "channel": "云猫"},
        counterparty="relay-b.example",
    )
    assert explicit["channel"]["code"] == "yunmao" and explicit["computed"]["fee"] == 0  # explicit input wins
    missing = post(
        client,
        f"{base}/transactions",
        csrf,
        {"effective_date": "2026-10-18", "inputs": {"amount": money("1")}},
        expect=422,
    )
    assert "缺少交易类型" in missing["detail"]
    cleared = client.patch(
        f"{base}/counterparties/{site['id']}",
        headers=write_headers(csrf),
        json={"expected_version": details["version"], "default_channel": None},
    )
    assert cleared.status_code == 200 and cleared.json()["data"]["defaults"]["channel"] is None


def test_import_uses_counterparty_defaults(client, world) -> None:
    from tests.api.test_mcp import mcp_for

    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    assert ai.call(
        "upsert_reference",
        kind="counterparty",
        fields={
            "name": "relay-a.example",
            "category": "upstream_site",
            "default_type": "credit_purchase",
            "default_channel": "liandong",
        },
    )["ok"]
    assert ai.call("manage_import_source", action="create", source={"code": "wallet", "kind": "records"})["ok"]
    batch = ai.call(
        "import_records",
        source="wallet",
        records=[
            {
                "occurred_at": "2026-10-18 10:00:00",
                "direction": "out",
                "amount": "51.50",
                "counterparty": "relay-a.example",
            },
            {"occurred_at": "2026-10-18 11:00:00", "direction": "in", "amount": "5", "counterparty": "relay-a.example"},
        ],
    )
    records = {r["direction"]: r for r in batch["data"]["records"]}
    assert records["out"]["status"] == "classified"
    assert records["out"]["classification"]["type"] == "credit_purchase"
    assert records["out"]["classification"]["inputs"]["channel"] == "liandong"
    assert records["in"]["status"] == "new"  # a purchase default never classifies incoming money


def test_fee_rules_for_expenses_and_transfers(client, world) -> None:
    csrf = login(client, world.admin_email)
    rule(
        client,
        world.book_id,
        csrf,
        code="card",
        rate="0.02",
        transaction_types=["expense"],
        channels=["direct"],
        valid_from="2026-01-01",
    )
    rule(client, world.book_id, csrf, code="any_direct", rate="0.05", channels=["direct"], valid_from="2026-01-01")
    paid = biz(
        client, world.book_id, csrf, "expense", {"amount": money("100"), "category": "5401.04", "channel": "官网直付"}
    )
    assert paid["computed"]["fee"] == 200 and paid["computed"]["fee_rule"]["code"] == "card"
    sold = biz(client, world.book_id, csrf, "sale", {"gross": money("100"), "channel": "direct"})
    assert sold["computed"]["fee"] == 500  # the untyped rule still covers sales
    moved = biz(
        client,
        world.book_id,
        csrf,
        "transfer",
        {
            "from_account": "1012.01",
            "to_account": "1012.01",
            "amount_out": money("10", "GBP"),
            "amount_in": money("95"),
        },
        expect=201,
    )
    assert moved["computed"]["fee"] == 0
    evaluated = client.get(
        f"/api/v1/books/{world.book_id}/fee-rules:evaluate",
        params={"type": "expense", "amount": "100", "on": "2026-10-18", "channel": "direct"},
    ).json()["data"]
    assert evaluated["fee_minor"] == 200 and evaluated["rule"]["code"] == "card"
