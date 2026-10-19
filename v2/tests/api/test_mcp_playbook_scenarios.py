"""The six scenario playbooks replayed over MCP as a client would run them, each with the tier it needs, in the
order its playbook lists (docs/19 §5). Each scenario only uses tools its playbook names."""

from __future__ import annotations

import io
import json
from typing import Any

from pydantic import SecretStr

from bookkeeper.services import playbooks
from tests.ai_fakes import ScriptBackend, install
from tests.api.conftest import login, write_headers
from tests.api.test_mcp import Mcp, mcp_for


class Tracked(Mcp):
    """An MCP client that remembers which tools it called, to hold each scenario to its playbook."""

    def __init__(self, inner: Mcp) -> None:
        super().__init__(inner.client, inner.headers["Authorization"].removeprefix("Bearer "))
        self.used: list[str] = []

    def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        self.used.append(name)
        return super().call(name, **arguments)


def follows(client: Tracked, code: str) -> None:
    item = next(p for p in playbooks.BUILT_IN if p["code"] == code)
    assert set(client.used) <= set(item["tools"]), set(client.used) - set(item["tools"])


def ok(result: dict[str, Any]) -> dict[str, Any]:
    assert result["ok"], result
    return result


def test_import_screenshots(client, world) -> None:
    csrf = login(client, world.admin_email)
    upload = client.post(
        f"/api/v1/books/{world.book_id}/files",
        files={"file": ("充值.csv", io.BytesIO("时间,金额,单号\n2026-10-18 10:00,50.00,R-1\n".encode()), "text/csv")},
        headers=write_headers(csrf),
    )
    assert upload.status_code == 201
    ai = Tracked(mcp_for(client, world, csrf, tier="user_write"))
    ok(ai.call("get_context"))
    files = ok(ai.call("list_files", kind="evidence"))["data"]["evidence"]
    read = ok(ai.call("read_file", file_id=files[0]["id"]))
    assert "R-1" in read["data"]["content"] and read["data"]["untrusted"] is True
    ok(
        ai.call(
            "manage_import_source",
            action="create",
            source={"code": "topups", "kind": "records", "config": {"defaults": {"in": {"type": "sale"}}}},
        )
    )
    staged = ok(
        ai.call(
            "import_records",
            source="topups",
            records=[
                {"occurred_at": "2026-10-18T10:00:00", "direction": "in", "amount": "50.00", "external_id": "R-1"}
            ],
        )
    )
    batch_id = staged["data"]["id"]
    batch = ok(ai.call("get_import_batch", batch_id=batch_id))["data"]
    record = batch["records"][0]
    ok(ai.call("classify_records", record_ids=[record["id"]], set={"inputs": {"channel": "liandong"}}))
    done = ok(ai.call("commit_import", batch_id=batch_id))
    assert "入账 1" in done["message"]
    follows(ai, "import_screenshots")


def test_monthly_review_and_site_check_need_only_reading(client, world) -> None:
    csrf = login(client, world.admin_email)
    reader = Tracked(mcp_for(client, world, csrf, tier="user_read"))
    ok(reader.call("list_pending_work"))
    ok(reader.call("run_report", report="summary", date_from="2026-10-01", date_to="2026-10-31"))
    ok(reader.call("run_report", report="summary", date_from="2026-09-01", date_to="2026-09-30"))
    ok(reader.call("query_ledger", date_from="2026-10-01", date_to="2026-10-31", group_by=["channel"]))
    ok(reader.call("run_checks"))
    follows(reader, "monthly_review")

    site = Tracked(mcp_for(client, world, csrf, tier="user_read"))
    ok(site.call("search_counterparties", query="api.example.com"))
    ok(site.call("search_transactions", q="api.example.com", date_from="2026-10-01", date_to="2026-10-31"))
    ok(site.call("search_source_records", q="api.example.com"))
    ok(site.call("evaluate_fee", type="credit_purchase", amount="50", on="2026-10-18"))
    follows(site, "check_site_topups")


def test_add_an_upstream_site_with_its_fee_rule(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = Tracked(mcp_for(client, world, csrf, tier="admin_write"))
    found = ok(ai.call("search_counterparties", query="api.newsite.example"))
    assert not found["data"]["counterparties"]
    ok(
        ai.call(
            "upsert_reference",
            kind="counterparty",
            fields={"name": "api.newsite.example", "category": "upstream_site", "domains": ["api.newsite.example"]},
        )
    )
    rule = {"code": "newsite", "rate": "0.03", "counterparties": ["api.newsite.example"], "valid_from": "2026-10-01"}
    ok(ai.call("manage_fee_rule", action="save", rule=rule))
    fee = ok(
        ai.call(
            "evaluate_fee", type="credit_purchase", amount="50", on="2026-10-18", counterparty="api.newsite.example"
        )
    )
    assert "1.5" in json.dumps(fee["data"])
    follows(ai, "add_upstream_site")


def test_fix_a_classification_and_save_it_as_a_rule(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = Tracked(mcp_for(client, world, csrf, tier="admin_write"))
    setup = mcp_for(client, world, csrf, tier="admin_write")  # staging is not part of this scenario
    ok(
        setup.call(
            "manage_import_source",
            action="create",
            source={"code": "bills", "kind": "records", "config": {"defaults": {"out": {"type": "expense"}}}},
        )
    )
    rows = [
        {
            "occurred_at": f"2026-10-{d}T09:00:00",
            "direction": "out",
            "amount": a,
            "counterparty": "CLOUD CO",
            "external_id": f"B{d}",
        }
        for d, a in (("10", "12.00"), ("11", "13.00"))
    ]
    batch_id = ok(setup.call("import_records", source="bills", records=rows))["data"]["id"]
    records = ok(ai.call("get_import_batch", batch_id=batch_id))["data"]["records"]
    first = min(records, key=lambda r: r["occurred_at"])  # the 10th
    ok(
        ai.call(
            "classify_records", record_ids=[first["id"]], set={"type": "expense", "inputs": {"category": "5401.04"}}
        )
    )
    saved = ok(ai.call("save_rule_from_record", record_id=first["id"]))
    assert saved["data"]["reclassified"] >= 1
    after = ok(ai.call("get_import_batch", batch_id=batch_id))["data"]["records"]
    assert all(r["status"] == "classified" for r in after)
    follows(ai, "fix_and_save_rule")


def test_undo_what_the_ai_assistant_did(client, world, app, monkeypatch) -> None:
    from bookkeeper import config
    from bookkeeper.jobs.worker import Worker
    from tests.api.test_business import counterparty, money

    monkeypatch.setattr(app.state.settings, "ai_api_key", SecretStr("sk-test-undo"))
    monkeypatch.setattr(config, "get_settings", lambda: app.state.settings)
    csrf = login(client, world.admin_email)
    counterparty(client, world.book_id, csrf, "api.example.com")
    purchase = {
        "type": "credit_purchase",
        "effective_date": "2026-10-18",
        "counterparty": "api.example.com",
        "inputs": {"face": money("50"), "total": money("51.50"), "credit_quantity": "50", "channel": "direct"},
    }
    install(monkeypatch, ScriptBackend([[("create_transaction", purchase)], "记好了"]))
    run = client.post(
        f"/api/v1/books/{world.book_id}/agent/runs", json={"instruction": "记一笔"}, headers=write_headers(csrf)
    ).json()["data"]
    Worker(app.state.sessionmaker).run_once()

    ai = Tracked(mcp_for(client, world, csrf, tier="admin_write"))
    sets = ok(ai.call("get_audit_trail", view="change_sets", channel="agent", limit=5))
    found = json.dumps(sets["data"], ensure_ascii=False)
    done = client.get(f"/api/v1/books/{world.book_id}/agent/runs/{run['id']}").json()["data"]
    assert done["change_set_id"] in found
    undone = ok(ai.call("undo_change_set", change_set_id=done["change_set_id"], reason="AI 记错了"))
    assert undone["data"]["change_set_id"] == done["change_set_id"]
    follows(ai, "undo_ai_run")
    txns = client.get(f"/api/v1/books/{world.book_id}/transactions", params={"status": "reversed"}).json()["data"]
    assert txns and txns[0]["created_channel"] == "agent"
