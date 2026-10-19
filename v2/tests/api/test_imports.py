"""Import pipeline: parsers, dedupe, rules, matching, pairing with estimate replacement, commit / revert."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.api.conftest import login, write_headers
from tests.api.test_business import biz, counterparty, money, rule

WECHAT = (
    "微信支付账单明细,,,,,,,,,,\n"
    "微信昵称：[测试],,,,,,,,,,\n"
    "起始时间：[2026-10-01 00:00:00] 终止时间：[2026-10-31 23:59:59],,,,,,,,,,\n"
    "共4笔记录,,,,,,,,,,\n"
    "收入：2笔 27.00元,,,,,,,,,,\n"
    "支出：3笔 99.00元,,,,,,,,,,\n"
    "----------------------微信支付账单明细列表--------------------,,,,,,,,,,\n"
    "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
    "2026-10-05 12:00:00,商户消费,Vultr,服务器,支出,¥80.00,零钱,支付成功,4200001\t,M001\t,/\n"
    "2026-10-06 09:30:00,扫二维码付款,某推广,推广,支出,¥12.00,零钱,支付成功,4200002\t,/,/\n"
    "2026-10-07 18:00:00,转账,张三,/,收入,¥20.00,/,已存入零钱,4200003\t,/,/\n"
    "2026-10-08 08:00:00,商户消费,失败商户,x,支出,¥5.00,零钱,支付失败,4200004\t,/,/\n"
    "2026-10-09 08:00:00,商户消费,退款商户,y,支出,¥7.00,零钱,已全额退款,4200005\t,/,/\n"
    "2026-10-09 09:00:00,商户消费-退款,退款商户,y,收入,¥7.00,零钱,已全额退款,4200006\t,/,/\n"
)


def post(client: TestClient, book_id: str, csrf: str, path: str, body: dict[str, Any], expect: int = 200) -> Any:
    response = client.post(f"/api/v1/books/{book_id}/{path}", headers=write_headers(csrf), json=body)
    assert response.status_code == expect, response.text
    return response.json()["data"] if expect < 300 else response.json()


def source(client: TestClient, book_id: str, csrf: str, code: str, kind: str, **config: Any) -> dict[str, Any]:
    return post(client, book_id, csrf, "import-sources", {"code": code, "kind": kind, "config": config}, 201)


def upload(
    client: TestClient, book_id: str, csrf: str, src: str, name: str, content: bytes, mime: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/books/{book_id}/import-batches:upload",
        headers=write_headers(csrf),
        data={"source": src},
        files={"file": (name, io.BytesIO(content), mime)},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def records(client: TestClient, book_id: str, csrf: str, src: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return post(client, book_id, csrf, "import-batches", {"source": src, "records": items}, 201)


def by_status(batch: dict[str, Any]) -> dict[str, int]:
    return dict(batch["summary"]["by_status"])


def test_wechat_bill_rules_commit_dedupe_and_revert(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "Vultr", category="cloud_vendor")
    source(
        client,
        b,
        csrf,
        "wechat",
        "wechat_bill",
        defaults={"out": {"type": "expense"}, "in": {"ignore": "personal_transfer"}},
    )
    post(
        client,
        b,
        csrf,
        "rules",
        {
            "code": "vultr",
            "condition": {"field": "counterparty_text", "op": "eq", "value": "Vultr"},
            "actions": [{"type": "set_category", "value": "5401.04"}, {"type": "set_counterparty", "value": "Vultr"}],
        },
        201,
    )
    batch = upload(client, b, csrf, "wechat", "wechat.csv", WECHAT.encode(), "text/csv")
    assert batch["parser"] == "wechat_bill@1.0.0"
    assert by_status(batch) == {"classified": 1, "new": 1, "ignored": 3}
    assert batch["summary"]["skipped"] == 1 and batch["summary"]["blocking"] == []
    assert {c["code"]: c["ok"] for c in batch["summary"]["checks"]}["totals_match"] is True
    vultr = next(r for r in batch["records"] if r["counterparty_text"] == "Vultr")
    assert vultr["classification"]["inputs"]["category"] == "5401.04" and vultr["rule_trace"][0]["rule"] == "vultr"
    ad = next(r for r in batch["records"] if r["counterparty_text"] == "某推广")
    assert ad["classification"]["missing"] == ["inputs.category"]

    fixed = client.patch(
        f"/api/v1/books/{b}/source-records/{ad['id']}",
        headers=write_headers(csrf),
        json={"inputs": {"category": "广告推广费"}},
    )
    assert fixed.status_code == 200 and fixed.json()["data"]["status"] == "classified"

    done = post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    assert done["counts"] == {"booked": 2, "ignored": 3, "settled_pairs": 0}
    vultr_txn = client.get(f"/api/v1/books/{b}/transactions", params={"q": "Vultr"}).json()["data"][0]
    detail = client.get(f"/api/v1/books/{b}/transactions/{vultr_txn['id']}").json()["data"]
    assert detail["sources"][0]["role"] == "primary" and detail["sources"][0]["source"] == "wechat"
    assert detail["external_ref"] == "wechat:4200001"

    again = upload(client, b, csrf, "wechat", "wechat-copy.csv", (WECHAT + "\n").encode(), "text/csv")
    assert by_status(again) == {"duplicate": 5}
    assert any(c["code"] == "all_duplicates" for c in again["summary"]["checks"])

    reverted = post(client, b, csrf, f"import-batches/{batch['id']}:revert", {"reason": "重新导入"})
    assert reverted["counts"]["deleted"] == 2
    third = upload(client, b, csrf, "wechat", "wechat-3.csv", (WECHAT + "\n\n").encode(), "text/csv")
    assert by_status(third)["classified"] == 1  # reverted records released their identity
    post(client, b, csrf, f"import-batches/{third['id']}:commit", {})
    run = post(client, b, csrf, "checks:run", {})
    assert run["status"] == "passed", run


def test_orders_pair_with_redemptions_and_replace_estimates(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-b.example")
    rule(
        client,
        b,
        csrf,
        code="relay-b-fallback",
        rate="0.03",
        transaction_types=["credit_purchase"],
        counterparties=["relay-b.example"],
        channels=["direct"],
        valid_from="2026-01-01",
        is_estimate=True,
    )
    source(
        client,
        b,
        csrf,
        "ld_orders",
        "card_shop_orders",
        shop="liandong",
        defaults={"out": {"type": "credit_purchase", "channel": "liandong"}},
    )
    source(
        client,
        b,
        csrf,
        "relay_log",
        "upstream_usage_log",
        counterparty="relay-b.example",
        defaults={"in": {"type": "credit_purchase", "channel": "direct", "counterparty": "relay-b.example"}},
    )
    post(
        client,
        b,
        csrf,
        "rules",
        {
            "code": "relay-b-codes",
            "condition": {
                "all": [
                    {"field": "source", "op": "eq", "value": "ld_orders"},
                    {"field": "description", "op": "contains", "value": "R兑换码"},
                ]
            },
            "actions": [{"type": "set_counterparty", "value": "relay-b.example"}],
        },
        201,
    )
    post(
        client,
        b,
        csrf,
        "pairing-rules",
        {"code": "ld-relay", "config": {"left": {"sources": ["ld_orders"]}, "right": {"sources": ["relay_log"]}}},
        201,
    )

    orders_json = (
        '[{"order":"LD1","name":"100R兑换码","amount":"103","status":"已完成","time":"2026-10-10 10:00:00","qty":1},'
        '{"order":"LD9","name":"100R兑换码","amount":"103","status":"已退款","time":"2026-10-10 11:00:00","qty":1}]'
    )
    orders = upload(client, b, csrf, "ld_orders", "ld.json", orders_json.encode(), "application/json")
    assert by_status(orders) == {"classified": 1} and orders["summary"]["skipped"] == 1
    assert orders["records"][0]["extracted"]["face"] == "100"
    post(client, b, csrf, f"import-batches/{orders['id']}:commit", {})

    log = records(
        client,
        b,
        csrf,
        "relay_log",
        [
            {
                "occurred_at": "2026-10-10 10:20:00",
                "direction": "in",
                "amount": "100",
                "commodity": "UCR",
                "external_id": "R1",
                "extracted": {"face": "100", "account": "A", "code": "SECRETCODE1234"},
            },
            {
                "occurred_at": "2026-10-11 09:00:00",
                "direction": "in",
                "amount": "50",
                "commodity": "UCR",
                "external_id": "R2",
                "extracted": {"face": "50", "account": "A"},
            },
        ],
    )
    assert by_status(log) == {"matched": 1, "classified": 1}
    paired = next(r for r in log["records"] if r["external_id"] == "R1")
    assert paired["paired_with"] == orders["records"][0]["id"]
    assert paired["extracted"]["code"]["last4"] == "1234" and "SECRET" not in str(paired)
    committed = post(client, b, csrf, f"import-batches/{log['id']}:commit", {})
    assert committed["counts"]["paired"] == 1 and committed["counts"]["booked"] == 1

    estimate = client.get(f"/api/v1/books/{b}/transactions", params={"is_estimate": True}).json()["data"]
    assert len(estimate) == 1 and estimate[0]["description"] == "relay-b.example · 额度采购 · 面值 ¥50 · 官网直付"
    order_txn = client.get(
        f"/api/v1/books/{b}/transactions", params={"type": "credit_purchase", "is_estimate": False}
    ).json()["data"][0]
    detail = client.get(f"/api/v1/books/{b}/transactions/{order_txn['id']}").json()["data"]
    assert sorted(s["role"] for s in detail["sources"]) == ["evidence", "primary"]
    assert [(l["account_code"], l["amount"]["minor"]) for l in detail["entries"][0]["lines"]] == [
        ("5401.01", 10000),
        ("5603.01", 300),
        ("1012.01", -10300),
    ]

    late_order = '[{"order":"LD2","name":"50R兑换码","amount":"51.5","status":"已完成","time":"2026-10-11 08:50:00"}]'
    late = upload(client, b, csrf, "ld_orders", "ld2.json", late_order.encode(), "application/json")
    suggestion = client.get(f"/api/v1/books/{b}/match-suggestions").json()["data"]
    assert suggestion == []  # 10-minute gap: auto-accepted
    settled = post(client, b, csrf, f"import-batches/{late['id']}:commit", {})
    assert settled["counts"]["settled_pairs"] == 1
    assert (
        client.get(f"/api/v1/books/{b}/transactions", params={"is_estimate": True, "status": "posted"}).json()["data"]
        == []
    )
    funds = client.get(f"/api/v1/books/{b}/balances", params={"as_of": "2026-10-31", "accounts": ["1012.01"]}).json()
    assert funds["data"]["balances"][0]["balance"]["minor"] == -15450  # 103 + 51.50, no estimate left
    credits = client.get(
        f"/api/v1/books/{b}/reports/credit-purchases", params={"date_from": "2026-10-01", "date_to": "2026-10-31"}
    ).json()["data"]
    assert credits["rows"][0]["purchases"] == 2 and credits["rows"][0]["total_paid"]["minor"] == 15450


def test_wide_daily_income_and_matching_existing(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    client.post(
        f"/api/v1/books/{b}/fx-rates",
        headers=write_headers(csrf),
        json={"base": "GBP", "quote": "CNY", "rate_date": "2026-09-21", "rate": "9.5"},
    )
    source(
        client,
        b,
        csrf,
        "daily_income",
        "generic_tabular",
        wide={
            "date": "日期",
            "direction": "in",
            "columns": {
                "链动": {"channel": "liandong"},
                "云猫": {"channel": "yunmao"},
                "stripe": {"channel": "stripe", "commodity": "GBP", "fee": "stripe手续费"},
            },
        },
        defaults={"in": {"type": "sale"}},
    )
    post(
        client,
        b,
        csrf,
        "rules",
        {
            "code": "channel-from-column",
            "condition": {"field": "extracted.channel", "op": "not_null"},
            "actions": [{"type": "set_channel", "value": "{extracted.channel}"}],
        },
        201,
    )
    csv = "日期,链动,云猫,stripe,stripe手续费\n46286,23,344,258.14,17.53\n46287,0,502,357.59,20.92\n"
    batch = upload(client, b, csrf, "daily_income", "income.csv", csv.encode(), "text/csv")
    assert by_status(batch) == {"classified": 5}
    stripe_rec = next(r for r in batch["records"] if r["extracted"]["column"] == "stripe")
    assert (
        stripe_rec["effective_date"] == "2026-09-21"
        and stripe_rec["classification"]["inputs"]["fee"]["amount"] == "17.53"
    )
    post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    sales = client.get(
        f"/api/v1/books/{b}/reports/sales", params={"date_from": "2026-09-01", "date_to": "2026-09-30"}
    ).json()["data"]
    assert {r["channel"]["code"]: r["orders"] for r in sales["rows"]} == {"stripe": 2, "yunmao": 2, "liandong": 1}

    biz(
        client,
        b,
        csrf,
        "sale",
        {"gross": money("88"), "fee": money("0"), "channel": "liandong"},
        effective_date="2026-10-02",
    )
    source(client, b, csrf, "bank", "records", defaults={"in": {"type": "sale", "channel": "liandong"}})
    pending = records(
        client,
        b,
        csrf,
        "bank",
        [
            {
                "occurred_at": "2026-10-03 10:00:00",
                "direction": "in",
                "amount": "88",
                "external_id": "B1",
                "description": "链动结算",
            }
        ],
    )
    assert pending["summary"]["pending_suggestions"] == 1
    held = post(client, b, csrf, f"import-batches/{pending['id']}:commit", {})
    assert held["counts"] == {"pending_match": 1, "settled_pairs": 0}
    suggestion = client.get(f"/api/v1/books/{b}/match-suggestions").json()["data"][0]
    assert suggestion["components"]["days"] == 1
    accepted = post(client, b, csrf, f"match-suggestions/{suggestion['id']}:accept", {})
    assert accepted["status"] == "accepted"
    linked = client.get(f"/api/v1/books/{b}/transactions/{suggestion['transaction_id']}").json()["data"]
    assert linked["sources"][0]["role"] == "evidence"


def test_suspense_policy_rules_test_and_apply(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    source(client, b, csrf, "alipay_like", "records", unclassified_policy="suspense")
    batch = records(
        client,
        b,
        csrf,
        "alipay_like",
        [
            {
                "occurred_at": "2026-10-04 08:00:00",
                "direction": "out",
                "amount": "15",
                "counterparty": "未知商户",
                "external_id": "A1",
                "balance_after": "85",
            },
            {
                "occurred_at": "2026-10-05 08:00:00",
                "direction": "in",
                "amount": "100",
                "counterparty": "客户",
                "external_id": "A0",
                "balance_after": "185",
            },
        ],
    )
    assert by_status(batch) == {"new": 2}
    assert {c["code"]: c["ok"] for c in batch["summary"]["checks"]}["balance_continuity"] is True
    preview = post(
        client,
        b,
        csrf,
        "rules:test",
        {
            "rule": {
                "code": "draft",
                "condition": {"field": "counterparty_text", "op": "contains", "value": "未知"},
                "actions": [
                    {"type": "set_transaction_type", "value": "expense"},
                    {"type": "set_category", "value": "5602.99"},
                ],
            }
        },
    )
    assert preview["hits"] == 1 and preview["samples"][0]["changes"][0]["value"] == "expense"
    post(
        client,
        b,
        csrf,
        "rules",
        preview_rule := {
            "code": "unknown-merchant",
            "condition": {"field": "counterparty_text", "op": "contains", "value": "未知"},
            "actions": [
                {"type": "set_transaction_type", "value": "expense"},
                {"type": "set_category", "value": "5602.99"},
            ],
        },
        201,
    )
    applied = post(client, b, csrf, "rules:apply", {"batch_id": batch["id"]})
    assert applied["reclassified"] == 2 and preview_rule["code"] == "unknown-merchant"
    done = post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    assert done["counts"] == {"booked": 1, "suspense": 1, "settled_pairs": 0}
    work = client.get(f"/api/v1/books/{b}/work-items/summary").json()["data"]["summary"]
    assert work["suspense"]["count"] == 1


def test_records_left_by_a_finished_import_book_when_completed(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "Vultr", category="cloud_vendor")
    source(
        client,
        b,
        csrf,
        "wechat",
        "wechat_bill",
        defaults={"out": {"type": "expense"}, "in": {"ignore": "personal_transfer"}},
    )
    batch = upload(client, b, csrf, "wechat", "wechat.csv", WECHAT.encode(), "text/csv")
    ad = next(r for r in batch["records"] if r["counterparty_text"] == "某推广")
    done = post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    assert done["counts"]["left_unbooked"] == 2  # Vultr and 某推广 still lack a category

    def waiting() -> tuple[int, int]:
        listed = client.get(f"/api/v1/books/{b}/import-batches").json()["data"]
        mine = next(x for x in listed if x["id"] == batch["id"])
        work = client.get(f"/api/v1/books/{b}/work-items/summary").json()["data"]["summary"]
        return mine["open_records"], work["unprocessed_records"]["count"]

    assert waiting() == (2, 2)
    fixed = client.patch(
        f"/api/v1/books/{b}/source-records/{ad['id']}",
        headers=write_headers(csrf),
        json={"inputs": {"category": "5601.01"}},
    )
    assert fixed.status_code == 200, fixed.text
    record = fixed.json()["data"]
    assert record["status"] == "booked" and record["transaction_id"]
    txn = client.get(f"/api/v1/books/{b}/transactions/{record['transaction_id']}").json()["data"]
    assert txn["status"] == "posted" and txn["type"] == "expense"
    assert waiting() == (1, 1)


def test_redeem_pages_link_to_what_the_books_already_hold(client, world) -> None:
    """Printed redeem pages: two copies in one upload are read once; top-ups the books keep as one daily total
    link to it as evidence; a top-up beside a booking it doesn't explain waits for a yes / no (finishing the
    import leaves it alone), and "not the same" books it at once."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-demo.example", domains=["relay-demo.example"])
    daily = biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("150.00"), "total": money("150.00"), "channel": "direct"},
        counterparty="relay-demo.example",
        effective_date="2026-09-25",
    )
    other = biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("30.00"), "total": money("30.00"), "channel": "direct"},
        counterparty="relay-demo.example",
        effective_date="2026-09-26",
    )
    source(client, b, csrf, "relay", "redeem_page", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    pdf = (Path(__file__).parent.parent / "fixtures" / "redeem_page.pdf").read_bytes()
    response = client.post(
        f"/api/v1/books/{b}/import-batches:upload",
        headers=write_headers(csrf),
        data={"source": "relay"},
        files=[("file", ("a.pdf", pdf, "application/pdf")), ("file", ("b.pdf", pdf, "application/pdf"))],
    )
    assert response.status_code == 201, response.text
    batch = response.json()["data"]
    assert by_status(batch) == {"matched": 2, "classified": 2, "duplicate": 4}
    by_day = {r["effective_date"] + r["amount"]["display"]: r for r in batch["records"] if r["status"] != "duplicate"}
    linked = [r["match"] for r in by_day.values() if r["status"] == "matched"]
    assert {(m["method"], m["status"], m["transaction"]["number"]) for m in linked} == {
        ("daily_total", "auto_accepted", daily["number"])
    }
    unsure = next(r for r in by_day.values() if r["effective_date"] == "2026-09-26")
    assert (unsure["match"]["status"], unsure["match"]["transaction"]["number"]) == ("pending", other["number"])
    assert next(r for r in by_day.values() if r["effective_date"] == "2026-09-24")["match"] is None

    done = post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    assert done["counts"] == {"linked": 2, "booked": 1, "pending_match": 1, "duplicate": 4, "settled_pairs": 0}
    post(client, b, csrf, f"match-suggestions/{unsure['match']['suggestion_id']}:reject", {})
    after = client.get(f"/api/v1/books/{b}/source-records", params={"batch_id": batch["id"], "status": "booked"})
    assert {r["effective_date"] for r in after.json()["data"]} == {"2026-09-24", "2026-09-26"}


def test_a_statement_already_in_the_books_matches_instead_of_doubling(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    wide = {
        "date": "日期",
        "direction": "in",
        "columns": {"链动": {"channel": "liandong"}, "云猫": {"channel": "yunmao"}},
    }
    for code in ("income_a", "income_b"):
        source(client, b, csrf, code, "generic_tabular", wide=wide, defaults={"in": {"type": "sale"}})
    post(
        client,
        b,
        csrf,
        "rules",
        {
            "code": "income-channel",
            "condition": {"field": "extracted.channel", "op": "not_null"},
            "actions": [{"type": "set_channel", "value": "{extracted.channel}"}],
        },
        201,
    )
    csv = "日期,链动,云猫\n46286,23,344\n46287,0,502\n".encode()
    first = upload(client, b, csrf, "income_a", "income.csv", csv, "text/csv")
    post(client, b, csrf, f"import-batches/{first['id']}:commit", {})
    again = upload(client, b, csrf, "income_b", "income.csv", csv, "text/csv")
    assert by_status(again) == {"matched": 3}
    assert {r["match"]["method"] for r in again["records"]} == {"same_day"}
    done = post(client, b, csrf, f"import-batches/{again['id']}:commit", {})
    assert done["counts"] == {"linked": 3, "settled_pairs": 0}


def test_source_preview_reads_a_sample_without_storing(client, world) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    csv = "日期,链动,云猫\n46286,23,344\n46287,0,502\n".encode()
    config = {"wide": {"date": "日期", "direction": "in", "columns": {"链动": {"channel": "liandong"}}}}
    response = client.post(
        f"/api/v1/books/{b}/import-sources:preview",
        headers=write_headers(csrf),
        data={"kind": "generic_tabular", "config": json.dumps(config)},
        files={"file": ("income.csv", io.BytesIO(csv), "text/csv")},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["rows"][0] == ["日期", "链动", "云猫"] and data["total"] == 1 and data["error"] is None
    assert data["records"][0]["amount"] == "23" and data["records"][0]["extracted"]["channel"] == "liandong"
    half = client.post(
        f"/api/v1/books/{b}/import-sources:preview",
        headers=write_headers(csrf),
        data={"kind": "generic_tabular", "config": json.dumps({"columns": {"date": "日期"}})},
        files={"file": ("income.csv", io.BytesIO(csv), "text/csv")},
    ).json()["data"]
    assert half["rows"] and half["records"] == [] and "列映射" in half["error"]
    assert client.get(f"/api/v1/books/{b}/import-batches").json()["data"] == []


def test_ai_source_reads_on_the_worker_once(client, world, app, monkeypatch) -> None:
    """AI 识别 with the model stubbed: the upload returns at once with a batch 识别中; the worker reads the files
    (overlapping screenshots keep a row once, page totals are checked), and sending the same files again gives
    the same batch back without another read. A failed read shows why and can be retried."""
    from bookkeeper import config
    from bookkeeper.domain.errors import DomainError
    from bookkeeper.jobs.worker import Worker
    from bookkeeper.services import ai_extract

    calls: list[str] = []
    broken = {"on": False}
    pages = {
        "1.png": [
            ("2026-10-05 12:00:00", "80.00", "LD1", "Team 席位"),
            ("2026-10-05 13:00:00", "12.00", "LD2", "接码"),
        ],
        "2.png": [
            ("2026-10-05 13:00:00", "12.00", "LD2", "接码"),
            ("2026-10-06 09:00:00", "25.70", "LD3", "Team 席位"),
        ],
        "3.png": [("2026-10-07 09:00:00", "9.90", "LD4", "接码")],
    }
    totals = {"1.png": ["共 2 条"], "2.png": ["合计 ¥40.00"], "3.png": []}

    def fake_request(_client, _settings, name, _data, mime, hint):  # type: ignore[no-untyped-def]
        assert mime == "image/png" and "链动" in hint
        calls.append(name)
        if broken["on"]:
            raise DomainError("AI_UNAVAILABLE", "AI 服务暂时连不上，请稍后再试。")
        row = dict.fromkeys(("currency", "fee", "quantity", "face"))
        rows = [
            row
            | {
                "occurred_at": t,
                "direction": "out",
                "amount": a,
                "currency": "CNY",
                "order_no": o,
                "counterparty": "链动",
                "description": d,
                "status": "已完成",
            }
            for t, a, o, d in pages[name]
        ]
        return {
            "page_kind": "订单列表",
            "site": "链动",
            "records": rows,
            "totals": totals[name],
            "unreadable": ["最后一行被截断"] if name == "2.png" else [],
            "_usage": {"input_tokens": 1000, "output_tokens": 200},
            "_model": "claude-opus-5-5",
        }

    monkeypatch.setattr(ai_extract, "_request", fake_request)
    monkeypatch.setattr(config, "get_settings", lambda: app.state.settings)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    worker = Worker(app.state.sessionmaker)
    csrf = login(client, world.admin_email)
    b = world.book_id
    source(client, b, csrf, "ld_shots", "ai_extract", hint="链动买家订单截图", defaults={"out": {"type": "expense"}})

    def send(names: list[str], expect: int = 201, mime: str = "image/png") -> dict[str, Any]:
        files = [("file", (n, f"PNG {n}".encode(), mime)) for n in names]
        response = client.post(
            f"/api/v1/books/{b}/import-batches:upload",
            headers=write_headers(csrf),
            data={"source": "ld_shots"},
            files=files,
        )
        assert response.status_code == expect, response.text
        return response.json()["data"] if expect < 300 else response.json()

    def batch(batch_id: str) -> dict[str, Any]:
        return client.get(f"/api/v1/books/{b}/import-batches/{batch_id}").json()["data"]

    waiting = send(["1.png", "2.png"])
    assert waiting["status"] == "extracting" and len(waiting["summary"]["files"]) == 2 and calls == []
    assert worker.run_once() is not None
    read = batch(waiting["id"])
    assert read["status"] == "parsed" and read["parser"] == "ai_extract@claude-opus-5-5"
    assert read["summary"]["records"] == 3 and sorted(calls) == ["1.png", "2.png"]
    extraction = read["summary"]["extraction"]
    assert extraction["usage"] == {"input_tokens": 2000, "output_tokens": 400}
    assert extraction["unreadable"] == ["2.png：最后一行被截断"]
    checks = {c["message"]: c["ok"] for c in read["summary"]["checks"] if c["code"] == "ai_totals"}
    assert checks == {"1.png：条数与页面一致（2 条）": True, "2.png：页面合计 40.00，读到的合计 37.70": False}
    assert read["summary"]["blocking"] == []

    again = send(["1.png", "2.png"], expect=200)
    assert again["id"] == waiting["id"] and worker.run_once() is None and len(calls) == 2

    broken["on"] = True
    failing = send(["3.png"])
    worker.run_once()
    failed = batch(failing["id"])
    assert failed["status"] == "failed" and "连不上" in failed["summary"]["error"]
    broken["on"] = False
    retried = post(client, b, csrf, f"import-batches/{failing['id']}:retry", {})
    assert retried["status"] == "extracting"
    worker.run_once()
    assert batch(failing["id"])["status"] == "parsed"

    assert send(["x.heic"], expect=415, mime="image/heic")["code"] == "UNSUPPORTED_MEDIA_TYPE"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    off = send(["4.png"], expect=503)
    assert "BK_AI_API_KEY" in off["detail"]


def test_a_read_with_no_progress_times_out(client, world, app, monkeypatch) -> None:
    """With no worker running, a batch stops showing 识别中 after 10 minutes: it shows 识别失败 (识别超时) and is
    retried like any failed read. The old queued job then never reads; a slow read that outlives the timeout
    still lands instead of being thrown away."""
    from datetime import UTC, datetime, timedelta

    from bookkeeper import config
    from bookkeeper.db.models import ImportBatch
    from bookkeeper.jobs.worker import Worker
    from bookkeeper.services import ai_extract, imports

    b = world.book_id
    calls: list[str] = []
    slow: dict[str, str] = {}

    def stall(batch_id: str) -> None:
        """Eleven minutes pass, and someone opens the import page."""
        with app.state.sessionmaker() as session, session.begin():
            batch = session.get(ImportBatch, batch_id)
            assert batch is not None
            since = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
            batch.summary = {**batch.summary, "reading_since": since}
        with app.state.sessionmaker() as session, session.begin():
            imports.expire_stalled(session, b)

    def fake_request(_client, _settings, name, _data, _mime, _hint):  # type: ignore[no-untyped-def]
        calls.append(name)
        if name in slow:
            stall(slow[name])
        row = dict.fromkeys(("currency", "fee", "quantity", "face", "order_no", "status"))
        row |= {"occurred_at": "2026-10-05 12:00:00", "direction": "out", "amount": "8.00", "counterparty": "链动"}
        return {
            "page_kind": "订单列表",
            "site": None,
            "records": [row | {"description": name}],
            "totals": [],
            "unreadable": [],
            "_usage": {"input_tokens": 10, "output_tokens": 5},
            "_model": "claude-opus-5-5",
        }

    monkeypatch.setattr(ai_extract, "_request", fake_request)
    monkeypatch.setattr(config, "get_settings", lambda: app.state.settings)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    worker = Worker(app.state.sessionmaker)
    csrf = login(client, world.admin_email)
    source(client, b, csrf, "shots", "ai_extract", defaults={"out": {"type": "expense"}})

    def send(name: str) -> dict[str, Any]:
        response = client.post(
            f"/api/v1/books/{b}/import-batches:upload",
            headers=write_headers(csrf),
            data={"source": "shots"},
            files=[("file", (name, f"PNG {name}".encode(), "image/png"))],
        )
        assert response.status_code == 201, response.text
        return response.json()["data"]

    def batch(batch_id: str) -> dict[str, Any]:
        return client.get(f"/api/v1/books/{b}/import-batches/{batch_id}").json()["data"]

    waiting = send("1.png")
    with app.state.sessionmaker() as session, session.begin():
        row = session.get(ImportBatch, waiting["id"])
        assert row is not None
        row.summary = {**row.summary, "reading_since": (datetime.now(UTC) - timedelta(minutes=11)).isoformat()}
    stalled = batch(waiting["id"])
    assert stalled["status"] == "failed" and stalled["summary"]["error"].startswith("识别超时")
    listed = client.get(f"/api/v1/books/{b}/import-batches").json()["data"]
    assert next(x for x in listed if x["id"] == waiting["id"])["status"] == "failed"

    worker.run_once()  # the worker comes back: the timed-out batch's old job reads nothing
    assert calls == [] and batch(waiting["id"])["status"] == "failed"
    post(client, b, csrf, f"import-batches/{waiting['id']}:retry", {})
    worker.run_once()
    assert calls == ["1.png"] and batch(waiting["id"])["status"] == "parsed"

    late = send("2.png")
    slow["2.png"] = late["id"]
    worker.run_once()  # times out while the read runs, then the read arrives
    landed = batch(late["id"])
    assert landed["status"] == "parsed" and landed["summary"]["records"] == 1 and "error" not in landed["summary"]


def test_answer_every_maybe_booked_question_at_once(client, world) -> None:
    """Bookings that don't add up (fee inside the face value, top-ups a day apart) leave each record a yes / no;
    one call answers them all."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-demo.example", domains=["relay-demo.example"])
    booked = biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("176.00"), "total": money("176.00"), "channel": "direct"},
        counterparty="relay-demo.example",
        effective_date="2026-09-25",
    )
    source(client, b, csrf, "relay", "redeem_page", defaults={"in": {"type": "credit_purchase"}})
    pdf = (Path(__file__).parent.parent / "fixtures" / "redeem_page.pdf").read_bytes()
    batch = upload(client, b, csrf, "relay", "page.pdf", pdf, "application/pdf")
    assert {r["match"]["status"] for r in batch["records"]} == {"pending"}
    decided = post(client, b, csrf, f"import-batches/{batch['id']}:decide-matches", {"same": True})
    assert decided == {"decided": 4}
    after = client.get(f"/api/v1/books/{b}/source-records", params={"batch_id": batch["id"]}).json()["data"]
    assert {(r["status"], r["match"]["transaction"]["number"]) for r in after} == {("matched", booked["number"])}


def test_part_of_a_day_links_and_unknown_sites_never_match(client, world) -> None:
    """A booking covering only some of the day's top-ups takes exactly those; a site the books don't know is a
    new record even beside a same-day booking of the same amount through the same channel."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-demo.example", domains=["relay-demo.example"])
    hundred = biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("100.00"), "total": money("100.00"), "channel": "direct"},
        counterparty="relay-demo.example",
        effective_date="2026-09-25",
    )
    source(client, b, csrf, "relay", "redeem_page", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    pdf = (Path(__file__).parent.parent / "fixtures" / "redeem_page.pdf").read_bytes()
    batch = upload(client, b, csrf, "relay", "page.pdf", pdf, "application/pdf")
    by_amount = {r["amount"]["display"]: r for r in batch["records"]}
    assert by_amount["100.0000 UCR"]["match"]["transaction"]["number"] == hundred["number"]
    assert by_amount["50.0000 UCR"]["status"] == "classified" and by_amount["50.0000 UCR"]["match"] is None

    counterparty(client, b, csrf, "known-site.example")
    biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("10.00"), "total": money("10.00"), "channel": "direct"},
        counterparty="known-site.example",
        effective_date="2026-10-05",
    )
    source(client, b, csrf, "logs", "records", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    stranger = records(
        client,
        b,
        csrf,
        "logs",
        [
            {
                "occurred_at": "2026-10-05 10:00:00",
                "direction": "in",
                "amount": "10",
                "commodity": "UCR",
                "counterparty": "never-seen.example",
                "external_id": "X1",
            }
        ],
    )
    assert stranger["records"][0]["match"] is None


def test_a_site_is_its_own_host(client, world) -> None:
    """A record from api.relay-a.example is that site's; x.relay-a.example is a different site, never folded into it."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "api.relay-a.example", domains=["api.relay-a.example"])
    booked = biz(
        client,
        b,
        csrf,
        "credit_purchase",
        {"face": money("10.00"), "total": money("10.00"), "channel": "direct"},
        counterparty="api.relay-a.example",
        effective_date="2026-10-05",
    )
    source(client, b, csrf, "logs", "records", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    row = {"occurred_at": "2026-10-05 10:00:00", "direction": "in", "amount": "10", "commodity": "UCR"}
    batch = records(
        client,
        b,
        csrf,
        "logs",
        [
            row | {"counterparty": "api.relay-a.example", "external_id": "A1"},
            row | {"counterparty": "x.relay-a.example", "external_id": "X1"},
        ],
    )
    by_site = {r["counterparty_text"]: r for r in batch["records"]}
    assert by_site["api.relay-a.example"]["match"]["transaction"]["number"] == booked["number"]
    assert by_site["x.relay-a.example"]["match"] is None


def test_a_file_name_cut_short_still_finds_its_site(client, world) -> None:
    """A printed page without its URL, in a file whose name was cut short, reads as the one known site the name
    can be; its rows then dedupe against the same page printed with the URL."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-demo.example", domains=["relay-demo.example"])
    counterparty(client, b, csrf, "other-relay.example")
    source(client, b, csrf, "relay", "redeem_page", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    fixtures = Path(__file__).parent.parent / "fixtures"
    bare = (fixtures / "redeem_page_no_url.pdf").read_bytes()
    cut = upload(client, b, csrf, "relay", "relay-demo.ex（2）.pdf", bare, "application/pdf")
    assert {r["counterparty_text"] for r in cut["records"]} == {"relay-demo.example"}
    assert all(r["external_id"].startswith("relay-demo.example:") for r in cut["records"])
    printed = (fixtures / "redeem_page.pdf").read_bytes()
    again = upload(client, b, csrf, "relay", "page.pdf", printed, "application/pdf")
    assert by_status(again) == {"duplicate": 4}


def test_credits_match_the_credit_quantity_a_booking_records(client, world) -> None:
    """¥100 bought $103 of credits: a $103 top-up is that booking, matched on credits rather than face value, and a
    day's top-ups add up to its credits the same way. Booking a top-up keeps its credits for the next import."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-d.example", domains=["relay-d.example"])

    def bought(face: str, credits: str, day: str) -> dict[str, Any]:
        inputs = {"face": money(face), "total": money(face), "credit_quantity": credits, "channel": "direct"}
        return biz(client, b, csrf, "credit_purchase", inputs, counterparty="relay-d.example", effective_date=day)

    one, day = bought("100.00", "103", "2026-10-05"), bought("150.00", "154", "2026-10-06")
    source(client, b, csrf, "logs", "records", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    row = {"direction": "in", "commodity": "UCR", "counterparty": "relay-d.example"}
    batch = records(
        client,
        b,
        csrf,
        "logs",
        [
            row | {"occurred_at": "2026-10-05 10:00:00", "amount": "103", "external_id": "T1"},
            row | {"occurred_at": "2026-10-06 09:00:00", "amount": "51", "external_id": "T2"},
            row | {"occurred_at": "2026-10-06 18:00:00", "amount": "103", "external_id": "T3"},
            row | {"occurred_at": "2026-10-08 09:00:00", "amount": "20", "external_id": "T4"},
        ],
    )
    by_id = {r["external_id"]: r for r in batch["records"]}
    assert by_id["T1"]["match"]["transaction"]["number"] == one["number"]
    assert by_id["T1"]["match"]["method"] == "same_day"
    assert {by_id[k]["match"]["transaction"]["number"] for k in ("T2", "T3")} == {day["number"]}
    assert by_id["T2"]["match"]["method"] == "daily_total"
    assert by_id["T4"]["match"] is None
    post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    after = client.get(f"/api/v1/books/{b}/import-batches/{batch['id']}").json()["data"]
    booked = next(r for r in after["records"] if r["external_id"] == "T4")
    txn = client.get(f"/api/v1/books/{b}/transactions/{booked['transaction_id']}").json()["data"]
    assert Decimal(txn["inputs"]["credit_quantity"]) == 20


def test_saying_not_the_same_takes_back_the_evidence_link(client, world) -> None:
    """An automatic match on a finished import was filed as evidence; "不是这笔" removes that link and books the
    record on its own, so the booking no longer lists it as its source."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    wide = {"date": "日期", "direction": "in", "columns": {"链动": {"channel": "liandong"}}}
    for code in ("income_a", "income_b"):
        source(client, b, csrf, code, "generic_tabular", wide=wide, defaults={"in": {"type": "sale"}})
    post(
        client,
        b,
        csrf,
        "rules",
        {
            "code": "income-channel",
            "condition": {"field": "extracted.channel", "op": "not_null"},
            "actions": [{"type": "set_channel", "value": "{extracted.channel}"}],
        },
        201,
    )
    csv = "日期,链动\n46286,23\n".encode()
    first = upload(client, b, csrf, "income_a", "a.csv", csv, "text/csv")
    post(client, b, csrf, f"import-batches/{first['id']}:commit", {})
    again = upload(client, b, csrf, "income_b", "b.csv", csv, "text/csv")
    post(client, b, csrf, f"import-batches/{again['id']}:commit", {})
    rec = client.get(f"/api/v1/books/{b}/source-records", params={"batch_id": again["id"]}).json()["data"][0]
    booked = rec["match"]["transaction"]
    sources = client.get(f"/api/v1/books/{b}/transactions/{booked['id']}").json()["data"]["sources"]
    assert {s["role"] for s in sources} == {"primary", "evidence"}

    post(client, b, csrf, f"match-suggestions/{rec['match']['suggestion_id']}:reject", {})
    sources = client.get(f"/api/v1/books/{b}/transactions/{booked['id']}").json()["data"]["sources"]
    assert {s["role"] for s in sources} == {"primary"}
    after = client.get(f"/api/v1/books/{b}/source-records", params={"batch_id": again["id"]}).json()["data"][0]
    assert after["status"] == "booked" and after["transaction_id"] != booked["id"]


def test_records_and_bookings_show_which_fee_rule_applies(client, world) -> None:
    """The fee rule in force on each record's own date shows on the record before booking and on the
    transaction after; before the rule starts the fee is "no rule, 0"."""
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "relay-demo.example", domains=["relay-demo.example"])
    rule(
        client,
        b,
        csrf,
        code="relay-fee",
        name="中转站购额度 3%",
        rate="0.03",
        transaction_types=["credit_purchase"],
        counterparties=["relay-demo.example"],
        valid_from="2026-09-25",
    )
    source(client, b, csrf, "relay", "redeem_page", defaults={"in": {"type": "credit_purchase", "channel": "direct"}})
    pdf = (Path(__file__).parent.parent / "fixtures" / "redeem_page.pdf").read_bytes()
    batch = upload(client, b, csrf, "relay", "page.pdf", pdf, "application/pdf")
    fees = {r["effective_date"]: r["fee_rule"] for r in batch["records"]}
    assert fees["2026-09-24"] == {"basis": "none", "rule": None}
    assert fees["2026-09-26"]["basis"] == "rule" and fees["2026-09-26"]["rule"]["name"] == "中转站购额度 3%"
    assert fees["2026-09-26"]["rule"]["rate"] == "0.03"
    post(client, b, csrf, f"import-batches/{batch['id']}:commit", {})
    booked = client.get(f"/api/v1/books/{b}/source-records", params={"batch_id": batch["id"]}).json()["data"]
    detail = {
        r["effective_date"]: client.get(f"/api/v1/books/{b}/transactions/{r['transaction_id']}").json()["data"]
        for r in booked
    }
    assert (
        detail["2026-09-26"]["fee_rule"]["rule"]["code"] == "relay-fee"
        and detail["2026-09-26"]["computed"]["fee"] == 60
    )
    assert detail["2026-09-24"]["fee_rule"] == {"basis": "none", "rule": None}
