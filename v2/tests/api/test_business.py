"""Business transaction types, fee rules, refunds, edits, delete / restore / undo, repost, batch, search."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.api.conftest import login, write_headers


def money(amount: str, commodity: str = "CNY") -> dict[str, str]:
    return {"amount": amount, "commodity": commodity}


def biz(
    client: TestClient,
    book_id: str,
    csrf: str,
    type_code: str,
    inputs: dict[str, Any],
    *,
    expect: int = 201,
    effective_date: str = "2026-10-18",
    **extra: Any,
) -> dict[str, Any]:
    body = {"type": type_code, "effective_date": effective_date, "inputs": inputs} | extra
    response = client.post(f"/api/v1/books/{book_id}/transactions", json=body, headers=write_headers(csrf))
    assert response.status_code == expect, response.text
    return response.json()["data"] if expect < 300 else response.json()


def rule(client: TestClient, book_id: str, csrf: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/api/v1/books/{book_id}/fee-rules", json=body, headers=write_headers(csrf))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def lines_of(view: dict[str, Any], entry: int = -1) -> list[tuple[str, int, str]]:
    return [(l["account_code"], l["amount"]["minor"], l["line_role"]) for l in view["entries"][entry]["lines"]]


def counterparty(client: TestClient, book_id: str, csrf: str, name: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/books/{book_id}/counterparties",
        headers=write_headers(csrf),
        json={"name": name, "category": "upstream_site"} | extra,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_catalogue_describes_every_business_type(client, world) -> None:
    login(client, world.admin_email)
    items = client.get(f"/api/v1/books/{world.book_id}/transaction-types").json()["data"]
    by_code = {i["code"]: i for i in items}
    assert {"sale", "sale_refund", "credit_purchase", "expense", "purchase_refund", "transfer"} <= set(by_code)
    sale = by_code["sale"]
    assert sale["input_mode"] == "inputs" and sale["fee_rules_apply"]
    assert set(sale["input_schema"]["required"]) == {"gross"}  # channel may come from the counterparty
    assert sale["default_accounts"]["settle_account"].startswith("1012.01")
    assert by_code["manual_journal"]["input_mode"] == "lines"
    assert "fx_revaluation" not in by_code


def test_sale_uses_fee_rule_and_versions(client, world) -> None:
    csrf = login(client, world.admin_email)
    created = rule(
        client,
        world.book_id,
        csrf,
        code="liandong",
        rate="0.03",
        transaction_types=["sale"],
        channels=["liandong"],
        valid_from="2026-01-01",
    )
    assert created["method"] == "percentage" and created["version"] == 1
    evaluated = client.get(
        f"/api/v1/books/{world.book_id}/fee-rules:evaluate",
        params={"type": "sale", "amount": "100", "on": "2026-10-18", "channel": "liandong"},
    ).json()["data"]
    assert evaluated["fee_minor"] == 300 and evaluated["rule"]["code"] == "liandong"

    sale = biz(client, world.book_id, csrf, "sale", {"gross": money("100.00"), "channel": "liandong"}, order_no="LD1")
    assert sale["status"] == "posted"
    assert sale["description"] == "链动 · API 额度销售 · LD1"
    assert sale["amount"]["display"] == "¥100.00"
    assert lines_of(sale) == [("1012.01", 9700, "net"), ("5603.01", 300, "fee"), ("5001.01", -10000, "gross")]
    assert sale["entries"][0]["lines"][0]["dimensions"] == {"liandong": "链动"}
    assert sale["computed"]["fee_rule"]["code"] == "liandong"

    deviating = biz(
        client, world.book_id, csrf, "sale", {"gross": money("100.00"), "fee": money("5.00"), "channel": "liandong"}
    )
    assert deviating["warnings"][0]["code"] == "FEE_DEVIATION"
    assert lines_of(deviating)[1] == ("5603.01", 500, "fee")

    # new version from 11-01: older postings keep 3 %, newer ones use 2.5 %
    v2 = rule(
        client,
        world.book_id,
        csrf,
        code="liandong",
        rate="0.025",
        transaction_types=["sale"],
        channels=["liandong"],
        valid_from="2026-11-01",
    )
    assert v2["version"] == 2
    later = biz(
        client,
        world.book_id,
        csrf,
        "sale",
        {"gross": money("200.00"), "channel": "liandong"},
        effective_date="2026-11-02",
    )
    assert lines_of(later)[1] == ("5603.01", 500, "fee")
    listed = client.get(f"/api/v1/books/{world.book_id}/fee-rules").json()["data"]
    assert [(r["version"], r["valid_to"]) for r in listed] == [(1, "2026-10-31"), (2, None)]
    explained = client.get(f"/api/v1/books/{world.book_id}/transactions/{sale['number']}/explain").json()["data"]
    assert explained["inputs"] == {"gross": "¥100.00", "channel": "链动"}
    assert explained["fee"]["rule"] == "liandong@1" and explained["fee"]["source"] == "rule"
    assert [c["reason"] for c in explained["fee"]["candidates"]] == ["命中", "2026-11-01 起生效"]
    assert [l["line_role"] for l in explained["lines"]] == ["net", "fee", "gross"]


def test_combined_rule_and_missing_channel(client, world) -> None:
    csrf = login(client, world.admin_email)
    rule(
        client,
        world.book_id,
        csrf,
        code="stripe",
        rate="0.029",
        fixed="0.30",
        commodity="CNY",
        transaction_types=["sale"],
        channels=["stripe"],
        valid_from="2026-01-01",
        is_estimate=True,
    )
    sale = biz(client, world.book_id, csrf, "sale", {"gross": money("100.00"), "channel": "stripe"})
    assert lines_of(sale)[1] == ("5603.01", 320, "fee")
    assert sale["is_estimate"] is True
    missing = biz(client, world.book_id, csrf, "sale", {"gross": money("1.00")}, expect=422)
    assert missing["errors"][0]["path"] == "inputs.channel" and "默认渠道" in missing["detail"]
    floaty = biz(client, world.book_id, csrf, "sale", {"gross": {"amount": 1.5}, "channel": "stripe"}, expect=422)
    assert floaty["code"] == "INPUT_INVALID"


def test_refund_inherits_links_and_is_capped(client, world) -> None:
    csrf = login(client, world.admin_email)
    sale = biz(
        client, world.book_id, csrf, "sale", {"gross": money("100.00"), "fee": money("3.00"), "channel": "yunmao"}
    )
    refund = biz(
        client,
        world.book_id,
        csrf,
        "sale_refund",
        {"original": sale["number"], "amount": money("60.00"), "fee_refunded": money("1.80")},
        effective_date="2026-10-19",
    )
    assert refund["channel"]["code"] == "yunmao"
    assert refund["description"] == "云猫 · 销售退款"
    assert lines_of(refund) == [("5001.01", 6000, "gross"), ("5603.01", -180, "fee"), ("1012.01", -5820, "net")]
    assert refund["links"][0]["kind"] == "refund_of" and refund["links"][0]["transaction"]["id"] == sale["id"]
    original = client.get(f"/api/v1/books/{world.book_id}/transactions/{sale['id']}").json()["data"]
    assert original["links"][0]["label"] == "退款" and original["links"][0]["transaction"]["id"] == refund["id"]
    too_much = biz(
        client, world.book_id, csrf, "sale_refund", {"original": sale["id"], "amount": money("40.01")}, expect=422
    )
    assert "累计退款" in too_much["detail"] and too_much["refundable"] == 4000
    wrong = biz(
        client, world.book_id, csrf, "purchase_refund", {"original": sale["id"], "amount": money("1")}, expect=422
    )
    assert wrong["errors"][0]["path"] == "inputs.original"


def test_credit_purchase_variants(client, world) -> None:
    csrf = login(client, world.admin_email)
    site = counterparty(client, world.book_id, csrf, "api.relay-a.example", domains=["api.relay-a.example"])
    both = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"face": money("50.00"), "total": money("51.50"), "credit_quantity": "55", "channel": "direct"},
        counterparty="api.relay-a.example",
    )
    assert both["description"] == "api.relay-a.example · 额度采购 · 面值 ¥50 · 官网直付"
    assert lines_of(both) == [("5401.01", 5000, "cost"), ("5603.01", 150, "fee"), ("1012.01", -5150, "pay")]
    assert both["entries"][0]["lines"][0]["quantity"] == "55.00000000"
    assert both["counterparty"]["id"] == site["id"]

    rule(
        client,
        world.book_id,
        csrf,
        code="xorpay",
        rate="0.03",
        transaction_types=["credit_purchase"],
        channels=["xorpay"],
        valid_from="2026-01-01",
    )
    face_only = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"face": money("100"), "channel": "xorpay"},
        counterparty="api.relay-a.example",
    )
    assert lines_of(face_only)[1:] == [("5603.01", 300, "fee"), ("1012.01", -10300, "pay")]
    total_only = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"total": money("103"), "channel": "xorpay"},
        counterparty="api.relay-a.example",
    )
    assert lines_of(total_only)[0] == ("5401.01", 10000, "cost")

    no_site = biz(client, world.book_id, csrf, "credit_purchase", {"face": money("1"), "channel": "direct"}, expect=422)
    assert no_site["errors"][0]["path"] == "counterparty"
    fuzzy = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"face": money("1"), "channel": "direct"},
        counterparty="https://api.relay-a.example/v1",
        expect=404,
    )
    assert fuzzy["candidates"][0]["name"] == "api.relay-a.example"
    other_site = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"face": money("1"), "channel": "direct"},
        counterparty="x.relay-a.example",
        expect=404,
    )
    assert not other_site.get("candidates")  # another host under the same domain is another site


def test_rename_carries_over_to_automatic_descriptions(client, world) -> None:
    csrf = login(client, world.admin_email)
    site = counterparty(client, world.book_id, csrf, "api.relay-a.example")
    inputs = {"face": money("10"), "channel": "direct"}
    auto = biz(client, world.book_id, csrf, "credit_purchase", inputs, counterparty="api.relay-a.example")
    typed = biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        inputs,
        counterparty="api.relay-a.example",
        description="api.relay-a.example · 自己写的摘要",
    )
    renamed = client.patch(
        f"/api/v1/books/{world.book_id}/counterparties/{site['id']}",
        headers=write_headers(csrf),
        json={"name": "api2.relay-a.example", "expected_version": site["version"]},
    )
    assert renamed.status_code == 200, renamed.text

    def described(number: str) -> str:
        return client.get(f"/api/v1/books/{world.book_id}/transactions/{number}").json()["data"]["description"]

    assert described(auto["number"]) == "api2.relay-a.example · 额度采购 · 面值 ¥10 · 官网直付"
    assert described(typed["number"]) == "api.relay-a.example · 自己写的摘要"  # written by hand: left alone


def test_channel_rename_carries_over_to_automatic_descriptions(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "api.relay-a.example")
    sale = biz(client, b, csrf, "sale", {"gross": money("10"), "channel": "liandong"})
    typed = biz(client, b, csrf, "sale", {"gross": money("10"), "channel": "liandong"}, description="链动 · 手写的")
    inputs = {"face": money("10"), "channel": "liandong"}
    bought = biz(client, b, csrf, "credit_purchase", inputs, counterparty="api.relay-a.example")
    assert sale["description"] == "链动 · API 额度销售"
    assert bought["description"] == "api.relay-a.example · 额度采购 · 面值 ¥10 · 链动"
    dimensions = client.get(f"/api/v1/books/{b}/dimensions").json()["data"]
    channel = next(
        v for d in dimensions for v in d["values"] if v["type_code"] == "channel" and v["code"] == "liandong"
    )
    renamed = client.patch(
        f"/api/v1/books/{b}/dimension-values/{channel['id']}",
        headers=write_headers(csrf),
        json={"name": "链动小铺", "expected_version": channel["version"]},
    )
    assert renamed.status_code == 200, renamed.text

    def described(number: str) -> str:
        return client.get(f"/api/v1/books/{b}/transactions/{number}").json()["data"]["description"]

    assert described(sale["number"]) == "链动小铺 · API 额度销售"
    assert described(bought["number"]) == "api.relay-a.example · 额度采购 · 面值 ¥10 · 链动小铺"
    assert described(typed["number"]) == "链动 · 手写的"  # written by hand: left alone


def test_expense_and_purchase_refund(client, world) -> None:
    csrf = login(client, world.admin_email)
    counterparty(client, world.book_id, csrf, "Vultr", category="cloud_vendor")
    expense = biz(
        client,
        world.book_id,
        csrf,
        "expense",
        {"amount": money("80.00"), "category": "服务器与网络", "fee": money("0.50")},
        counterparty="Vultr",
    )
    assert expense["description"] == "Vultr · 服务器与网络"
    assert lines_of(expense) == [("5401.04", 8000, "cost"), ("5603.01", 50, "fee"), ("1012.01", -8050, "pay")]
    refund = biz(client, world.book_id, csrf, "purchase_refund", {"original": expense["number"], "amount": money("20")})
    assert refund["counterparty"]["name"] == "Vultr"
    assert lines_of(refund) == [("1012.01", 2000, "pay"), ("5401.04", -2000, "cost")]
    not_expense = biz(client, world.book_id, csrf, "expense", {"amount": money("1"), "category": "1012.01"}, expect=422)
    assert "不是支出分类" in not_expense["detail"]


def test_transfer_exchange_with_and_without_reference_rate(client, world) -> None:
    csrf = login(client, world.admin_email)
    biz(
        client,
        world.book_id,
        csrf,
        "transfer",
        {"from_account": "1012.01", "to_account": "1012.01", "amount_out": money("1")},
        expect=422,
    )
    implied = biz(
        client,
        world.book_id,
        csrf,
        "transfer",
        {
            "from_account": "1012.01",
            "to_account": "1012.01",
            "amount_out": money("100.00", "GBP"),
            "amount_in": money("950.00"),
            "fee": money("1.00", "GBP"),
        },
    )
    assert implied["description"] == "结汇 · GBP → CNY"
    assert implied["warnings"][0]["code"] == "FX_IMPLIED_RATE"
    assert sum(l["base_amount"] for l in implied["entries"][0]["lines"]) == 0
    assert all(l["line_role"] != "fx_realization" for l in implied["entries"][0]["lines"])

    client.post(
        f"/api/v1/books/{world.book_id}/fx-rates",
        headers=write_headers(csrf),
        json={"base": "GBP", "quote": "CNY", "rate_date": "2026-10-20", "rate": "9.6"},
    )
    quoted = biz(
        client,
        world.book_id,
        csrf,
        "transfer",
        {
            "from_account": "1012.01",
            "to_account": "1012.01",
            "amount_out": money("100.00", "GBP"),
            "amount_in": money("950.00"),
        },
        effective_date="2026-10-20",
    )
    realized = [l for l in quoted["entries"][0]["lines"] if l["line_role"] == "fx_realization"]
    assert realized and realized[0]["base_amount"] == 1000  # 960 at reference − 950 received = loss 10


def test_edit_partial_inputs_reposts_in_place(client, world) -> None:
    csrf = login(client, world.admin_email)
    rule(client, world.book_id, csrf, code="yunmao", rate="0.02", channels=["yunmao"], valid_from="2026-01-01")
    sale = biz(client, world.book_id, csrf, "sale", {"gross": money("10"), "fee": money("0"), "channel": "liandong"})
    assert sale["status"] == "posted" and sale["computed"]["entry_number"] == "记-202610-0001"
    url = f"/api/v1/books/{world.book_id}/transactions/{sale['id']}"
    patched = client.patch(
        url,
        headers=write_headers(csrf),
        json={"expected_version": sale["version"], "inputs": {"channel": "yunmao", "fee": None}},
    )
    assert patched.status_code == 200, patched.text
    data = patched.json()["data"]
    assert data["number"] == sale["number"] and data["status"] == "posted"
    assert data["inputs"]["gross"]["minor"] == 1000 and "fee" not in data["inputs"]
    assert data["description"] == "云猫 · API 额度销售"
    assert [e["kind"] for e in data["entries"]] == ["posting", "repost_reversal", "repost"]
    assert lines_of(data) == [("1012.01", 980, "net"), ("5603.01", 20, "fee"), ("5001.01", -1000, "gross")]
    stale = client.patch(url, headers=write_headers(csrf), json={"expected_version": sale["version"], "notes": "x"})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    named = client.patch(url, headers=write_headers(csrf), json={"description": "云猫 · 手写摘要", "tags": ["活动"]})
    named_data = named.json()["data"]
    assert named_data["description"] == "云猫 · 手写摘要" and named_data["tags"] == ["活动"]
    assert len(named_data["entries"]) == 3, "a header edit does not touch the books"
    same = client.patch(url, headers=write_headers(csrf), json={"inputs": {"channel": "yunmao"}}).json()["data"]
    assert len(same["entries"]) == 3, "unchanged lines are not re-posted"
    moved = client.patch(url, headers=write_headers(csrf), json={"effective_date": "2026-10-20"}).json()["data"]
    assert [e["effective_date"] for e in moved["entries"][-2:]] == ["2026-10-18", "2026-10-20"]
    wrong = client.patch(url, headers=write_headers(csrf), json={"type": "expense"})
    assert wrong.status_code == 422


def test_delete_restore_and_undo(client, world) -> None:
    csrf = login(client, world.admin_email)
    sale = biz(client, world.book_id, csrf, "sale", {"gross": money("100"), "fee": money("3"), "channel": "liandong"})
    url = f"/api/v1/books/{world.book_id}/transactions/{sale['number']}"

    def balance() -> int:
        rows = client.get(
            f"/api/v1/books/{world.book_id}/balances", params={"as_of": "2026-10-31", "accounts": ["1012.01"]}
        ).json()["data"]["balances"]
        return rows[0]["balance"]["minor"] if rows else 0

    def listed(**params: Any) -> list[str]:
        return [
            r["number"] for r in client.get(f"/api/v1/books/{world.book_id}/transactions", params=params).json()["data"]
        ]

    edited = client.patch(url, headers=write_headers(csrf), json={"inputs": {"gross": money("120")}})
    assert edited.status_code == 200, edited.text
    edit_set = edited.json()["meta"]["change_set_id"]
    assert lines_of(edited.json()["data"]) == [
        ("1012.01", 11700, "net"),
        ("5603.01", 300, "fee"),
        ("5001.01", -12000, "gross"),
    ]
    assert balance() == 11700
    deleted = client.delete(url, headers=write_headers(csrf))
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["data"]["status"] == "reversed" and balance() == 0
    assert listed() == [] and listed(status="reversed") == [sale["number"]]
    again = client.delete(url, headers=write_headers(csrf))
    assert again.status_code == 409
    blocked = client.patch(url, headers=write_headers(csrf), json={"notes": "x"})
    assert blocked.status_code == 409 and blocked.json()["next_action"]["mcp_tool"] == "restore_transaction"
    undone = client.post(
        f"/api/v1/books/{world.book_id}/change-sets/{deleted.json()['meta']['change_set_id']}:undo",
        headers=write_headers(csrf),
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["data"]["actions"][0]["action"] == "restored"
    assert balance() == 11700 and listed() == [sale["number"]]
    put_back = client.post(f"/api/v1/books/{world.book_id}/change-sets/{edit_set}:undo", headers=write_headers(csrf))
    assert put_back.status_code == 200, put_back.text
    assert put_back.json()["data"]["actions"][0]["action"] == "put_back"
    view = client.get(url).json()["data"]
    assert view["inputs"]["gross"]["minor"] == 10000 and balance() == 9700
    assert [e["kind"] for e in view["entries"]] == [
        "posting",
        "repost_reversal",
        "repost",
        "reversal",
        "posting",
        "repost_reversal",
        "repost",
    ]
    client.request("DELETE", url, headers=write_headers(csrf), json={"reason": "重复录入"})
    restored = client.post(url + ":restore", headers=write_headers(csrf))
    assert restored.status_code == 200 and restored.json()["data"]["status"] == "posted" and balance() == 9700
    run = client.post(f"/api/v1/books/{world.book_id}/checks:run", headers=write_headers(csrf), json={})
    assert run.json()["data"]["status"] == "passed", run.text


def test_repost_after_rule_change(client, world) -> None:
    csrf = login(client, world.admin_email)
    rule(
        client,
        world.book_id,
        csrf,
        code="yunmao",
        rate="0.02",
        transaction_types=["sale"],
        channels=["yunmao"],
        valid_from="2026-01-01",
    )
    estimated = biz(client, world.book_id, csrf, "sale", {"gross": money("100"), "channel": "yunmao"})
    actual = biz(client, world.book_id, csrf, "sale", {"gross": money("100"), "fee": money("2"), "channel": "yunmao"})
    rule(
        client,
        world.book_id,
        csrf,
        code="yunmao-fix",
        rate="0.04",
        transaction_types=["sale"],
        channels=["yunmao"],
        priority=10,
        valid_from="2026-01-01",
    )
    url = f"/api/v1/books/{world.book_id}/transactions:repost"
    preview = client.post(url + "?dry_run=true", headers=write_headers(csrf), json={"reason": "云猫费率更正"})
    assert preview.status_code == 200, preview.text
    summary = preview.json()["data"]
    assert (summary["checked"], summary["reposted"], summary["unchanged"]) == (2, 1, 1)
    assert summary["items"][0]["id"] == estimated["id"] and summary["items"][0]["fee_delta"] == 200
    still = client.get(f"/api/v1/books/{world.book_id}/transactions/{estimated['id']}").json()["data"]
    assert len(still["entries"]) == 1
    done = client.post(url, headers=write_headers(csrf), json={"reason": "云猫费率更正", "channels": ["yunmao"]})
    assert done.json()["data"]["reposted"] == 1
    after = client.get(f"/api/v1/books/{world.book_id}/transactions/{estimated['id']}").json()["data"]
    assert [e["kind"] for e in after["entries"]] == ["posting", "repost_reversal", "repost"]
    assert lines_of(after)[1] == ("5603.01", 400, "fee") and after["computed"]["fee"] == 400
    untouched = client.get(f"/api/v1/books/{world.book_id}/transactions/{actual['id']}").json()["data"]
    assert len(untouched["entries"]) == 1
    run = client.post(f"/api/v1/books/{world.book_id}/checks:run", headers=write_headers(csrf), json={})
    assert run.json()["data"]["status"] == "passed", run.text


def test_batch_atomic_and_partial(client, world) -> None:
    csrf = login(client, world.admin_email)
    good = {
        "type": "sale",
        "effective_date": "2026-10-18",
        "inputs": {"gross": money("10"), "fee": money("0.30"), "channel": "liandong"},
    }
    bad = {"type": "sale", "effective_date": "2026-10-18", "inputs": {"gross": money("10")}}
    url = f"/api/v1/books/{world.book_id}/transactions:batch"
    failed = client.post(url, headers=write_headers(csrf), json={"items": [good, bad]})
    assert failed.status_code == 422 and failed.json()["index"] == 1 and failed.json()["detail"].startswith("第 2 条")
    listed = client.get(f"/api/v1/books/{world.book_id}/transactions").json()["data"]
    assert listed == []
    partial = client.post(url, headers=write_headers(csrf), json={"items": [good, bad, good], "atomic": False})
    assert partial.status_code == 200, partial.text
    body = partial.json()["data"]
    assert (body["created"], body["failed"]) == (2, 1)
    assert body["results"][1]["error"]["code"] == "INPUT_INVALID"
    assert body["results"][2]["transaction"]["entry_number"] == "记-202610-0002"


def test_search_filters_connect_views(client, world) -> None:
    csrf = login(client, world.admin_email)
    counterparty(client, world.book_id, csrf, "relay-a.example")
    sale = biz(client, world.book_id, csrf, "sale", {"gross": money("100"), "fee": money("3"), "channel": "liandong"})
    biz(client, world.book_id, csrf, "sale", {"gross": money("20"), "fee": money("1"), "channel": "yunmao"})
    biz(
        client,
        world.book_id,
        csrf,
        "credit_purchase",
        {"face": money("50"), "channel": "direct"},
        counterparty="relay-a.example",
    )
    refund = biz(client, world.book_id, csrf, "sale_refund", {"original": sale["id"], "amount": money("10")})

    def find(**params: Any) -> list[str]:
        rows = client.get(f"/api/v1/books/{world.book_id}/transactions", params=params).json()["data"]
        return sorted(r["description"] for r in rows)

    assert find(channel="liandong") == ["链动 · API 额度销售", "链动 · 销售退款"]
    assert find(account="5401") == ["relay-a.example · 额度采购 · 面值 ¥50 · 官网直付"]
    assert find(account="5603.01", type="sale") == ["云猫 · API 额度销售", "链动 · API 额度销售"]
    assert find(amount_min=2000, amount_max=5000) == [
        "relay-a.example · 额度采购 · 面值 ¥50 · 官网直付",
        "云猫 · API 额度销售",
    ]
    assert find(linked_to=sale["number"]) == ["链动 · 销售退款"]
    assert find(linked_to=refund["id"]) == ["链动 · API 额度销售"]
    gbp = {"gross": money("7", "GBP"), "fee": money("0.3", "GBP"), "channel": "stripe", "fx_rate": "9.5"}
    biz(client, world.book_id, csrf, "sale", gbp)
    assert find(commodity="gbp") == ["Stripe · API 额度销售"]
    assert find(account="1012.01", commodity="GBP") == ["Stripe · API 额度销售"]
    assert len(find(account="1012.01", commodity="CNY")) == 4


def test_actual_fx_rate_input(client, world) -> None:
    csrf = login(client, world.admin_email)
    sale = biz(
        client,
        world.book_id,
        csrf,
        "sale",
        {"gross": money("20.00", "GBP"), "fee": money("0.85", "GBP"), "channel": "stripe", "fx_rate": "9.5"},
    )
    lines = sale["entries"][0]["lines"]
    assert [l["base_amount"] for l in lines if l["line_role"] != "rounding"] == [18193, 808, -19000]
    assert all(l["fx_source"] in ("manual", "actual", "input", None) or l["fx_rate"] for l in lines)
    bad = biz(
        client,
        world.book_id,
        csrf,
        "sale",
        {"gross": money("1", "GBP"), "channel": "stripe", "fx_rate": "0"},
        expect=422,
    )
    assert bad["errors"][0]["path"] == "inputs.fx_rate"


def test_duplicate_risk_check(client, world) -> None:
    csrf = login(client, world.admin_email)
    book = world.book_id

    def run() -> dict[str, Any]:
        response = client.post(
            f"/api/v1/books/{book}/checks:run", headers=write_headers(csrf), json={"codes": ["duplicate_risk"]}
        )
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()["data"]["results"][0]
        return result

    first = biz(
        client, book, csrf, "expense", {"amount": money("9.90"), "category": "5602.99"}, effective_date="2026-10-05"
    )
    biz(client, book, csrf, "expense", {"amount": money("9.90"), "category": "5602.99"}, effective_date="2026-10-06")
    assert run()["status"] == "pass"
    second = biz(
        client, book, csrf, "expense", {"amount": money("9.90"), "category": "5602.99"}, effective_date="2026-10-05"
    )
    flagged = run()
    assert flagged["status"] == "fail" and flagged["severity"] == "warning"
    assert flagged["details"][0]["transactions"] == [first["number"], second["number"]]
    for txn, order in ((first, "A-1"), (second, "A-2")):  # a genuine pair: telling them apart settles it
        tagged = client.patch(
            f"/api/v1/books/{book}/transactions/{txn['number']}", headers=write_headers(csrf), json={"order_no": order}
        )
        assert tagged.status_code == 200, tagged.text
    assert run()["status"] == "pass"
