"""Replay of the MCP scenarios A–D (docs/09 §9) as an AI client would run them."""

from __future__ import annotations

import json

from tests.api.conftest import login, write_headers
from tests.api.test_mcp import mcp_for


def test_mcp_scenarios_a_to_d(client, world) -> None:
    csrf = login(client, world.admin_email)
    book = world.book_id
    for body in (
        {"name": "relay-b.example", "category": "upstream_site", "domains": ["relay-b.example"]},
        {"name": "某商户", "category": "other"},
    ):
        assert (
            client.post(f"/api/v1/books/{book}/counterparties", headers=write_headers(csrf), json=body).status_code
            == 201
        )
    rule = {
        "code": "liandong_buy",
        "rate": "0.03",
        "transaction_types": ["credit_purchase"],
        "channels": ["liandong"],
        "valid_from": "2026-01-01",
    }
    assert client.post(f"/api/v1/books/{book}/fee-rules", headers=write_headers(csrf), json=rule).status_code == 201
    ai = mcp_for(client, world, csrf, preset="admin")

    # A. record a purchase from natural language: context → counterparty → schema → dry run → record
    context = ai.call("get_context")
    assert context["data"]["book"]["base_commodity"] == "CNY" and "ledger:write" in context["data"]["caller"]["scopes"]
    assert ai.call("search_counterparties", query="relay-b")["data"]["counterparties"][0]["name"] == "relay-b.example"
    schema = ai.call("get_reference", kind="transaction_type", code="credit_purchase")
    assert "face" in json.dumps(schema["data"], ensure_ascii=False)
    purchase = {
        "type": "credit_purchase",
        "occurred_at": "2026-10-17T18:20:39+08:00",
        "inputs": {"face": {"amount": "50.00", "commodity": "CNY"}, "credit_quantity": "50", "channel": "liandong"},
        "counterparty": "relay-b.example",
        "order_no": "LD261017000001",
    }
    dry = ai.call("create_transaction", **purchase, dry_run=True)
    assert dry["ok"] and dry["meta"]["dry_run"]
    lines = {(li["account_code"], li["amount"]["minor"]) for li in dry["data"]["entries"][0]["lines"]}
    assert lines == {("5401.01", 5000), ("5603.01", 150), ("1012.01", -5150)}
    assert dry["data"]["description"].startswith("relay-b.example · 额度采购")
    posted = ai.call("create_transaction", **purchase)
    assert posted["ok"] and posted["data"]["status"] == "posted", posted
    number = posted["data"]["number"]
    post_change_set = posted["meta"]["change_set_id"]

    # B. import a statement: records → classify the unknown one → commit → pending work
    assert ai.call(
        "manage_import_source",
        action="create",
        source={
            "code": "wallet",
            "kind": "records",
            "config": {"defaults": {"in": {"type": "sale", "channel": "yunmao"}}},
        },
    )["ok"]
    batch = ai.call(
        "import_records",
        source="wallet",
        records=[
            {"occurred_at": "2026-10-18 09:00:00", "direction": "in", "amount": "30", "external_id": "W1"},
            {
                "occurred_at": "2026-10-18 10:00:00",
                "direction": "out",
                "amount": "12",
                "counterparty": "某商户",
                "external_id": "W2",
            },
        ],
    )
    assert batch["data"]["summary"]["by_status"] == {"classified": 1, "new": 1}
    unknown = ai.call("search_source_records", batch_id=batch["data"]["id"], status="new")["data"]
    classified = ai.call(
        "classify_records", record_ids=[unknown[0]["id"]], set={"type": "expense", "inputs": {"category": "5602.99"}}
    )
    assert classified["ok"], classified
    committed = ai.call("commit_import", batch_id=batch["data"]["id"])
    assert committed["ok"] and committed["data"]["counts"]["booked"] == 2, committed
    pending = ai.call("list_pending_work")
    assert pending["ok"] and "summary" in pending["data"]

    # C. fee rate corrected retroactively: new rule version → repost dry run → repost
    saved = ai.call("manage_fee_rule", action="save", rule=rule | {"rate": "0.02", "valid_from": "2026-10-01"})
    assert saved["ok"], saved
    trial = ai.call("repost_transactions", reason="链动采购费率改为 2%", types=["credit_purchase"], dry_run=True)
    assert trial["ok"] and trial["data"]["reposted"] == 1 and trial["data"]["fee_delta"] == -50, trial
    reposted = ai.call("repost_transactions", reason="链动采购费率改为 2%", types=["credit_purchase"])
    assert reposted["ok"] and reposted["message"].startswith("检查 1 笔：按新规则重算 1 笔"), reposted
    after = ai.call("get_transaction", ref=number)["data"]
    assert after["computed"]["fee"] == 100  # 2% of 50.00

    # D. undo an AI mistake: find the change set in the audit trail → undo
    sets = ai.call("get_audit_trail", view="change_sets", channel="mcp")["data"]
    assert post_change_set in {s["id"] for s in sets}
    undone = ai.call("undo_change_set", change_set_id=post_change_set, reason="记错了，撤回")
    assert undone["ok"] and undone["data"]["actions"][0]["action"] == "deleted", undone
    final = ai.call("get_transaction", ref=number)["data"]
    assert final["status"] == "reversed"
