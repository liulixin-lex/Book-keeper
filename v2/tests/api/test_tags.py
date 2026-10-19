"""Tags: set on create and on posted transactions, search, report filter, rules, undo, exports."""

from __future__ import annotations

import json

from tests.api.conftest import login, write_headers
from tests.api.test_business import biz, money


def test_tags_end_to_end(client, world) -> None:
    csrf = login(client, world.admin_email)
    book = world.book_id
    ad = biz(
        client,
        book,
        csrf,
        "expense",
        {"amount": money("120"), "category": "5601.01"},
        tags=["双十一推广", " 双十一推广 "],
    )
    assert ad["tags"] == ["双十一推广"]
    other = biz(client, book, csrf, "expense", {"amount": money("30"), "category": "5602.99"})
    patched = client.patch(
        f"/api/v1/books/{book}/transactions/{other['number']}",
        headers=write_headers(csrf),
        json={"expected_version": other["version"], "tags": ["双十一推广", "待报销"]},
    )
    assert patched.status_code == 200, patched.text  # posted transactions can be tagged
    change_set = patched.json()["meta"]["change_set_id"]

    found = client.get(f"/api/v1/books/{book}/transactions", params={"tag": "双十一推广"}).json()["data"]
    assert {t["number"] for t in found} == {ad["number"], other["number"]}
    spent = client.get(
        f"/api/v1/books/{book}/reports/query",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31", "classifications": "expense", "tags": "双十一推广"},
    ).json()["data"]
    assert spent["rows"][0]["values"]["base_amount"]["minor"] == 15000
    listed = client.get(f"/api/v1/books/{book}/tags").json()["data"]
    assert listed[0] == {"name": "双十一推广", "transactions": 2, "last_used_at": listed[0]["last_used_at"]}

    undone = client.post(
        f"/api/v1/books/{book}/change-sets/{change_set}:undo", headers=write_headers(csrf), json={"reason": "标错了"}
    )
    assert undone.status_code == 200, undone.text
    assert client.get(f"/api/v1/books/{book}/transactions/{other['number']}").json()["data"]["tags"] == []

    edited = client.patch(
        f"/api/v1/books/{book}/transactions/{ad['number']}",
        headers=write_headers(csrf),
        json={"inputs": {"amount": money("100")}},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["tags"] == ["双十一推广"]  # an edit keeps the tags

    dump = json.loads(client.get(f"/api/v1/books/{book}/exports/json").content)
    assert any(e["transaction"]["tags"] == ["双十一推广"] for e in dump["entries"])
    assert 'tags: "双十一推广"' in client.get(f"/api/v1/books/{book}/exports/beancount").text

    too_long = biz(
        client, book, csrf, "expense", {"amount": money("1"), "category": "5602.99"}, tags=["x" * 31], expect=422
    )
    assert "超过" in too_long["detail"]


def test_rule_adds_tags_on_import(client, world) -> None:
    from tests.api.test_mcp import mcp_for

    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    assert ai.call(
        "manage_import_source",
        action="create",
        source={"code": "cash", "kind": "records", "config": {}},
    )["ok"]
    rule = ai.call(
        "manage_rule",
        action="save",
        rule={
            "code": "ads",
            "name": "广告",
            "stage": "classify",
            "condition": {"field": "description", "op": "contains", "value": "广告"},
            "actions": [
                {"type": "set_transaction_type", "value": "expense"},
                {"type": "set_category", "value": "5601.01"},
                {"type": "add_tag", "value": "广告-{weekday}"},
            ],
        },
    )
    assert rule["ok"], rule
    batch = ai.call(
        "import_records",
        source="cash",
        records=[
            {"occurred_at": "2026-10-16 10:00:00", "direction": "out", "amount": "50", "description": "信息流广告"}
        ],
    )
    committed = ai.call("commit_import", batch_id=batch["data"]["id"])
    assert committed["ok"], committed
    tagged = ai.call("search_transactions", tag="广告-5")
    assert len(tagged["data"]["transactions"]) == 1
    tags = ai.call("get_reference", kind="tags")
    assert tags["data"][0]["name"] == "广告-5"
