"""MCP endpoint: discovery per token, envelopes, dry run, idempotency, edit / delete / restore, undo, logging."""

from __future__ import annotations

import itertools
import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bookkeeper.db.models import ApiToken, McpCall, Transaction
from bookkeeper.mcp_api.tools import TOOLS
from tests.api.conftest import bearer, create_token, login, write_headers
from tests.api.test_business import counterparty, money

_ids = itertools.count(1)
PV = "2025-11-25"


class Mcp:
    def __init__(self, client: TestClient, token: str) -> None:
        self.client = client
        self.headers = bearer(token) | {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PV,
        }

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": next(_ids), "method": method}
        if params is not None:
            body["params"] = params
        response = self.client.post("/mcp", headers=self.headers, json=body)
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()
        assert "error" not in data, data
        return dict(data["result"])

    def tools(self) -> list[str]:
        return [t["name"] for t in self.rpc("tools/list")["tools"]]

    def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        envelope: dict[str, Any] = result["structuredContent"]
        assert json.loads(result["content"][0]["text"]) == envelope
        assert result.get("isError", False) is (not envelope["ok"])
        return envelope


def mcp_for(client: TestClient, world: Any, csrf: str, **token: Any) -> Mcp:
    issued = create_token(client, world.book_id, csrf, mcp_enabled=True, **token)
    return Mcp(client, issued["token"])


def sale_args(**extra: Any) -> dict[str, Any]:
    return {
        "type": "sale",
        "effective_date": "2026-10-18",
        "inputs": {"gross": money("100"), "fee": money("3"), "channel": "liandong"},
    } | extra


def test_initialize_and_tool_visibility(client, world) -> None:
    csrf = login(client, world.admin_email)
    admin = mcp_for(client, world, csrf, tier="admin_write")
    init = admin.rpc(
        "initialize",
        {"protocolVersion": PV, "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}},
    )
    assert init["serverInfo"]["name"] == "bookkeeper" and "get_context" in init["instructions"]
    assert set(init["capabilities"]) >= {"tools", "resources", "prompts"}
    all_tools = admin.tools()
    assert len(all_tools) == len(TOOLS) == 40
    assert {"create_transaction", "update_transaction", "delete_transaction", "undo_change_set"} <= set(all_tools)
    schema = next(t for t in admin.rpc("tools/list")["tools"] if t["name"] == "create_transaction")
    assert schema["inputSchema"]["additionalProperties"] is False
    assert schema["annotations"]["readOnlyHint"] is False and schema["annotations"]["destructiveHint"] is False

    reader = mcp_for(client, world, csrf, tier="user_read")
    assert len(reader.tools()) == 18 and "create_transaction" not in reader.tools()
    assert not {"get_audit_trail", "get_admin_info"} & set(reader.tools())
    overseer = set(mcp_for(client, world, csrf, tier="admin_read").tools())
    assert overseer == set(reader.tools()) | {"get_audit_trail", "get_admin_info"}
    keeper = set(mcp_for(client, world, csrf, tier="user_write").tools())
    assert {"create_transaction", "update_transaction", "delete_transaction", "upsert_reference"} <= keeper
    assert not keeper & {"manage_fee_rule", "manage_rule", "manage_pairing_rule"}
    assert {"import_records", "commit_import"} <= keeper
    delete = next(t for t in admin.rpc("tools/list")["tools"] if t["name"] == "delete_transaction")
    assert delete["annotations"]["destructiveHint"] is True

    forbidden = reader.call("create_transaction", **sale_args())
    assert forbidden["code"] == "FORBIDDEN_SCOPE" and "get_context" in forbidden["details"]["available"]

    plain = create_token(client, world.book_id, csrf, tier="admin_write")["token"]
    denied = client.post(
        "/mcp", headers=Mcp(client, plain).headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert denied.status_code == 403 and denied.json()["error"] == "FORBIDDEN_SCOPE"
    anonymous = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert anonymous.status_code == 401 and anonymous.headers["www-authenticate"].startswith("Bearer")
    assert client.get("/mcp", headers=admin.headers).status_code == 405


def test_record_purchase_dry_run_then_write(client, world) -> None:
    csrf = login(client, world.admin_email)
    counterparty(client, world.book_id, csrf, "relay-a.example", domains=["api.relay-a.example"])
    ai = mcp_for(client, world, csrf, tier="admin_write")
    context = ai.call("get_context")
    assert "ledger:write" in context["data"]["caller"]["scopes"] and "writes" in context["data"]["conventions"]
    found = ai.call("search_counterparties", query="https://api.relay-a.example/v1")
    assert found["data"]["resolved"][0]["name"] == "relay-a.example"
    schema = ai.call("get_reference", kind="transaction_type", code="credit_purchase")
    assert "face" in schema["data"]["input_schema"]["properties"]

    args = {
        "type": "credit_purchase",
        "effective_date": "2026-10-18",
        "counterparty": "relay-a.example",
        "inputs": {"face": money("50"), "total": money("51.50"), "credit_quantity": "50", "channel": "direct"},
    }
    dry = ai.call("create_transaction", dry_run=True, **args)
    assert dry["code"] == "DRY_RUN" and dry["meta"]["dry_run"] is True
    assert [l["line_role"] for l in dry["data"]["entries"][0]["lines"]] == ["cost", "fee", "pay"]
    assert dry["data"]["description"] == "relay-a.example · 额度采购 · 面值 ¥50 · 官网直付"
    with client.app.state.sessionmaker() as s:  # type: ignore[attr-defined]
        assert s.execute(select(func.count()).select_from(Transaction)).scalar_one() == 0

    done = ai.call("create_transaction", **args)
    assert done["ok"] and done["data"]["status"] == "posted" and done["meta"]["change_set_id"]
    assert done["message"].startswith(f"已记账 {done['data']['number']}")
    txn = ai.call("get_transaction", ref=done["data"]["number"], explain=True)
    assert txn["data"]["created_channel"] == "mcp" and txn["data"]["explain"]["fee"]["source"] == "actual"


def test_validation_errors_are_actionable(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    unknown = ai.call("create_transaction", colour="red", **sale_args())
    assert unknown["code"] == "VALIDATION_FAILED" and unknown["errors"][0]["path"] == "colour"
    floaty = ai.call("create_transaction", **sale_args(inputs={"gross": {"amount": 1.5}, "channel": "liandong"}))
    assert floaty["code"] == "INPUT_INVALID" and floaty["next_action"]["operation"] == "meta_transaction_types"
    missing = ai.call("get_transaction", ref="T2026-999999")
    assert missing["code"] == "NOT_FOUND" and missing["retryable"] is False
    nope = ai.call("no_such_tool")
    assert nope["code"] == "NOT_FOUND"


def test_idempotent_retry_writes_once(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    first = ai.call("create_transaction", idempotency_key="order-LD-1", **sale_args())
    second = ai.call("create_transaction", idempotency_key="order-LD-1", **sale_args())
    assert first["data"]["number"] == second["data"]["number"]
    assert second["meta"]["idempotent_replayed"] is True
    mismatch = ai.call("create_transaction", idempotency_key="order-LD-1", **sale_args(order_no="other"))
    assert mismatch["code"] == "IDEMPOTENCY_MISMATCH"
    with client.app.state.sessionmaker() as s:  # type: ignore[attr-defined]
        assert s.execute(select(func.count()).select_from(Transaction)).scalar_one() == 1


def test_batch_edit_delete_and_restore(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    batch = ai.call(
        "create_transactions",
        items=[sale_args(), sale_args(inputs={"gross": money("20"), "fee": money("0.60"), "channel": "yunmao"})],
    )
    assert batch["data"]["created"] == 2 and batch["message"] == "成功 2 笔，失败 0 笔"
    number = batch["data"]["results"][0]["transaction"]["number"]
    trial = ai.call("update_transaction", ref=number, inputs={"gross": money("110")}, dry_run=True)
    assert trial["code"] == "DRY_RUN" and trial["data"]["entries"][-1]["lines"][2]["amount"]["minor"] == -11000
    assert len(ai.call("get_transaction", ref=number)["data"]["entries"]) == 1, "a dry run changes nothing"
    current = ai.call("get_transaction", ref=number)["data"]
    edited = ai.call(
        "update_transaction", ref=number, expected_version=current["version"], inputs={"gross": money("110")}
    )
    assert edited["ok"] and edited["data"]["number"] == number and edited["message"].startswith(f"已修改 {number}")
    assert [e["kind"] for e in edited["data"]["entries"]] == ["posting", "repost_reversal", "repost"]
    stale = ai.call("update_transaction", ref=number, expected_version=current["version"], notes="x")
    assert stale["code"] == "VERSION_CONFLICT"
    deleted = ai.call("delete_transaction", ref=number, reason="重复")
    assert deleted["data"]["status"] == "reversed" and "restore_transaction" in deleted["message"]
    assert [t["number"] for t in ai.call("search_transactions", status="reversed")["data"]["transactions"]] == [number]
    restored = ai.call("restore_transaction", ref=number)
    assert restored["data"]["status"] == "posted" and restored["message"] == f"已恢复 {number}"
    balances = ai.call("get_balances", as_of="2026-10-31", accounts=["1012.01"])
    assert balances["data"]["balances"][0]["balance"]["minor"] == 10700 + 1940


def test_undo_change_set_and_audit(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    first = ai.call("create_transaction", **sale_args())
    second = ai.call("create_transaction", **sale_args())
    change_sets = ai.call("get_audit_trail", view="change_sets", channel="mcp")
    assert {c["id"] for c in change_sets["data"]} >= {first["meta"]["change_set_id"], second["meta"]["change_set_id"]}
    undone = ai.call("undo_change_set", change_set_id=first["meta"]["change_set_id"], reason="AI 误记")
    assert undone["data"]["actions"] == [
        {"id": first["data"]["id"], "number": first["data"]["number"], "action": "deleted"}
    ]
    undone_second = ai.call("undo_change_set", change_set_id=second["meta"]["change_set_id"])
    assert undone_second["data"]["actions"][0]["action"] == "deleted"
    twice = ai.call("undo_change_set", change_set_id=second["meta"]["change_set_id"], reason="再来")
    assert twice["code"] == "INVALID_STATE"
    restored = ai.call("undo_change_set", change_set_id=undone["data"]["undo_change_set_id"], reason="撤销撤销")
    assert restored["data"]["actions"][0]["action"] == "restored"
    balances = ai.call("get_balances", as_of="2026-10-31", accounts=["1012.01"])
    assert balances["data"]["balances"][0]["balance"]["minor"] == 9700
    checks = ai.call("run_checks")
    assert checks["data"]["status"] == "passed", checks["data"]


def test_reports_queries_explain_and_resources(client, world) -> None:
    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    ai.call("create_transaction", **sale_args())
    summary = ai.call("run_report", report="summary", date_from="2026-10-01", date_to="2026-10-31")
    assert summary["data"]["profit"]["revenue"]["minor"] == 10000
    query = ai.call(
        "query_ledger", date_from="2026-10-01", date_to="2026-10-31", group_by=["channel"], accounts=["5001"]
    )
    assert query["data"]["rows"][0]["drilldown"]["transactions"]["channel"] == "liandong"
    listed = ai.call("search_transactions", **query["data"]["rows"][0]["drilldown"]["transactions"])
    assert len(listed["data"]["transactions"]) == 1
    hypothetical = ai.call(
        "explain_posting",
        type="sale",
        inputs={"gross": money("50"), "channel": "liandong"},
        effective_date="2026-10-18",
    )
    assert hypothetical["data"]["hypothetical"] is True and hypothetical["data"]["fee"]["source"] == "none"
    with client.app.state.sessionmaker() as s:  # type: ignore[attr-defined]
        assert s.execute(select(func.count()).select_from(Transaction)).scalar_one() == 1
    work = ai.call("list_pending_work")
    assert set(work["data"]["summary"]) == {
        "unprocessed_records",
        "pending_matches",
        "uncommitted_batches",
        "estimated",
        "suspense",
        "failed_checks",
    }
    fee = ai.call("evaluate_fee", type="sale", amount="100", on="2026-10-18", channel="liandong")
    assert fee["data"]["fee_minor"] == 0
    saved = ai.call(
        "manage_fee_rule",
        action="save",
        rule={
            "code": "liandong",
            "rate": "0.03",
            "transaction_types": ["sale"],
            "channels": ["liandong"],
            "valid_from": "2026-01-01",
        },
    )
    assert saved["next_action"]["tool"] == "repost_transactions"

    resources = ai.rpc("resources/list")["resources"]
    assert {"ledger://context", "ledger://guides/posting"} <= {r["uri"] for r in resources}
    guide = ai.rpc("resources/read", {"uri": "ledger://guides/fees"})["contents"][0]
    assert guide["mimeType"] == "text/markdown" and "evaluate_fee" in guide["text"]
    context = json.loads(ai.rpc("resources/read", {"uri": "ledger://context"})["contents"][0]["text"])
    assert context["data"]["book"]["base_commodity"] == "CNY"
    prompts = {p["name"] for p in ai.rpc("prompts/list")["prompts"]}
    assert "monthly_review" in prompts
    prompt = ai.rpc("prompts/get", {"name": "monthly_review", "arguments": {"month": "2026-10"}})
    assert "2026-10" in prompt["messages"][0]["content"]["text"]


def test_calls_are_logged_and_rate_limited(client, world, app) -> None:
    csrf = login(client, world.admin_email)
    issued = create_token(client, world.book_id, csrf, tier="admin_write", mcp_enabled=True)
    ai = Mcp(client, issued["token"])
    ai.call("get_context")
    ai.call("get_transaction", ref="T2026-000404")
    calls = client.get(f"/api/v1/books/{world.book_id}/mcp-calls").json()["data"]
    assert [(c["tool"], c["ok"], c["result_code"]) for c in calls[:2]] == [
        ("get_transaction", False, "NOT_FOUND"),
        ("get_context", True, "OK"),
    ]
    with app.state.sessionmaker() as s, s.begin():
        s.get(ApiToken, issued["id"]).rate_limit_per_min = 1  # type: ignore[union-attr]
    blocked = client.post("/mcp", headers=ai.headers, json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1
    with app.state.sessionmaker() as s:
        assert s.execute(select(func.count()).select_from(McpCall)).scalar_one() == 2


def test_rest_token_writes_directly_and_undo(client, world) -> None:
    csrf = login(client, world.admin_email)
    token = create_token(client, world.book_id, csrf, tier="admin_write")["token"]
    headers = bearer(token, **{"Idempotency-Key": "sale-1"})
    created = client.post(f"/api/v1/books/{world.book_id}/transactions", headers=headers, json=sale_args())
    assert created.status_code == 201, created.text
    assert created.json()["data"]["status"] == "posted"
    replay = client.post(f"/api/v1/books/{world.book_id}/transactions", headers=headers, json=sale_args())
    assert replay.headers["Idempotent-Replayed"] == "true"
    change_set = created.json()["meta"]["change_set_id"]
    undo = client.post(f"/api/v1/books/{world.book_id}/change-sets/{change_set}:undo", headers=write_headers(csrf))
    assert undo.status_code == 200, undo.text
    assert undo.json()["data"]["actions"][0]["action"] == "deleted"
    items = client.get(f"/api/v1/books/{world.book_id}/work-items/summary").json()["data"]
    assert items["total"] == 0


def test_official_sdk_client_round_trip(app, world) -> None:
    """The official MCP client (Streamable HTTP) can initialize, list and call tools against our endpoint."""
    import anyio
    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from bookkeeper.domain.scopes import ROLE_CAPS, Role, Tier
    from bookkeeper.services import tokens
    from bookkeeper.services.context import Actor, RequestContext

    actor = Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER])
    with app.state.sessionmaker() as s, s.begin():
        ctx = RequestContext(actor=actor, channel="api", book_id=world.book_id)
        token = tokens.create_token(s, ctx, name="sdk", tier=Tier.USER_READ, mcp_enabled=True).plaintext

    async def main() -> tuple[list[str], dict[str, Any]]:
        async with app.state.mcp_manager.run():
            transport = httpx2.ASGITransport(app=app)
            async with (
                httpx2.AsyncClient(transport=transport, base_url="http://testserver", headers=bearer(token)) as http,
                streamable_http_client("http://testserver/mcp", http_client=http) as streams,
                ClientSession(streams[0], streams[1]) as session,
            ):
                await session.initialize()
                listed = await session.list_tools()
                result = await session.call_tool("get_context", {})
                return [t.name for t in listed.tools], dict(result.structured_content or {})

    names, envelope = anyio.run(main)
    assert "get_context" in names and envelope["ok"] is True


def test_official_client_modern_protocol(app, world) -> None:
    """The unified SDK client in auto mode negotiates the stateless 2026 protocol with our server."""
    import anyio
    import httpx2
    from mcp.client.client import Client
    from mcp.client.streamable_http import streamable_http_client

    from bookkeeper.domain.scopes import ROLE_CAPS, Role, Tier
    from bookkeeper.services import tokens
    from bookkeeper.services.context import Actor, RequestContext

    actor = Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER])
    with app.state.sessionmaker() as s, s.begin():
        ctx = RequestContext(actor=actor, channel="api", book_id=world.book_id)
        token = tokens.create_token(s, ctx, name="sdk2", tier=Tier.ADMIN_WRITE, mcp_enabled=True).plaintext

    async def main() -> tuple[str, list[str], dict[str, Any], dict[str, Any]]:
        async with app.state.mcp_manager.run():
            transport = httpx2.ASGITransport(app=app)
            async with (
                httpx2.AsyncClient(transport=transport, base_url="http://testserver", headers=bearer(token)) as http,
                Client(streamable_http_client("http://testserver/mcp", http_client=http)) as client,
            ):
                listed = await client.list_tools()
                good = await client.call_tool("evaluate_fee", {"type": "sale", "amount": "10", "on": "2026-10-18"})
                bad = await client.call_tool("get_transaction", {"ref": "T2026-000001"})
                return (
                    client.protocol_version,
                    [t.name for t in listed.tools],
                    dict(good.structured_content or {}),
                    dict(bad.structured_content or {}),
                )

    version, names, good, bad = anyio.run(main)
    assert len(names) == len(TOOLS)
    assert good["ok"] is True and bad["code"] == "NOT_FOUND"
    assert version == "2026-07-28"


def test_import_via_mcp(client, world) -> None:
    import base64

    csrf = login(client, world.admin_email)
    ai = mcp_for(client, world, csrf, tier="admin_write")
    created = ai.call(
        "manage_import_source",
        action="create",
        source={
            "code": "shop_sales",
            "kind": "records",
            "config": {"defaults": {"in": {"type": "sale", "channel": "yunmao"}}},
        },
    )
    assert created["ok"], created
    batch = ai.call(
        "import_records",
        source="shop_sales",
        records=[
            {
                "occurred_at": "2026-10-09 10:00:00",
                "direction": "in",
                "amount": "30",
                "fee": "0.54",
                "external_id": "Y1",
            },
            {"occurred_at": "2026-10-09 11:00:00", "direction": "in", "amount": "50", "external_id": "Y2"},
        ],
    )
    batch_id = batch["data"]["id"]
    assert (
        batch["data"]["summary"]["by_status"] == {"classified": 2} and batch["next_action"]["tool"] == "commit_import"
    )
    found = ai.call("search_source_records", batch_id=batch_id)
    assert found["data"][0]["classification"]["inputs"]["fee"] == {"amount": "0.54", "commodity": "CNY"}
    trial = ai.call("commit_import", batch_id=batch_id, dry_run=True)
    assert trial["code"] == "DRY_RUN" and trial["data"]["counts"]["booked"] == 2
    committed = ai.call("commit_import", batch_id=batch_id)
    assert committed["data"]["counts"]["booked"] == 2 and committed["message"] == "导入完成：入账 2"
    sales = ai.call("run_report", report="sales", date_from="2026-10-01", date_to="2026-10-31")
    assert sales["data"]["rows"][0]["orders"] == 2
    undo = ai.call("undo_change_set", change_set_id=committed["meta"]["change_set_id"], reason="导错了")
    assert undo["data"]["actions"][0]["action"] == "import_reverted"
    after = ai.call("get_import_batch", batch_id=batch_id)
    assert after["data"]["status"] == "reverted"

    csv = "date,amount,desc\n2026-10-10,12.5,咖啡\n"
    file_source = ai.call(
        "manage_import_source",
        action="create",
        source={
            "code": "cash_sheet",
            "kind": "generic_tabular",
            "config": {
                "columns": {"date": "date", "amount": "amount", "description": "desc"},
                "default_direction": "out",
            },
        },
    )
    assert file_source["ok"]
    imported = ai.call(
        "import_records",
        source="cash_sheet",
        file_name="cash.csv",
        content_base64=base64.b64encode(csv.encode()).decode(),
    )
    assert imported["data"]["file_id"] and imported["data"]["summary"]["by_status"] == {"new": 1}
    record_id = imported["data"]["records"][0]["id"]
    classified = ai.call(
        "classify_records", record_ids=[record_id], set={"type": "expense", "inputs": {"category": "5602.99"}}
    )
    assert classified["data"][0]["status"] == "classified"
    gone = ai.call("record_balance", account="1012.01", as_of="2026-10-31", balance="0")
    assert gone["code"] == "NOT_FOUND"
