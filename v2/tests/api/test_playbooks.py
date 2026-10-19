"""Scenario playbooks as data (one source for MCP prompts and AI 助手), MCP resources and tool hints, by tier."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from bookkeeper.domain.scopes import TIER_SCOPES, Tier
from bookkeeper.mcp_api import hints
from bookkeeper.mcp_api.server import permitted
from bookkeeper.mcp_api.tools import TOOLS
from bookkeeper.services import playbooks
from tests.ai_fakes import ScriptBackend, install
from tests.api.conftest import create_token, login, write_headers
from tests.api.test_mcp import Mcp, mcp_for

REQUIRED = {
    "import_screenshots": "导入截图并入账",
    "monthly_review": "月度经营分析",
    "check_site_topups": "核对某站点充值",
    "fix_and_save_rule": "修正分类并存为规则",
    "add_upstream_site": "新增上游站点与手续费规则",
    "undo_ai_run": "撤销某次 AI 操作",
}


def test_the_built_in_playbooks_are_complete_and_consistent() -> None:
    by_code = {p["code"]: p for p in playbooks.BUILT_IN}
    assert {code: by_code[code]["title"] for code in REQUIRED} == REQUIRED
    for raw in playbooks.BUILT_IN:
        item = playbooks.clean(raw, raw["code"])  # every tool exists, every field is there
        assert item["when"] and item["steps"] and item["tools"] and item["done"]
        for name in item["tools"]:
            tool = TOOLS[name]
            assert set(s.value for s in tool.scopes) <= set(item["scopes"]), (raw["code"], name)
        assert "费率" not in item["when"]  # scenarios, not rates: those are the book's data


def test_every_tool_has_a_group_and_a_valid_example() -> None:
    assert set(TOOLS) == set(hints.GROUP_OF) == set(hints.HINTS)
    for name, (example, following) in hints.HINTS.items():
        TOOLS[name].model.model_validate(example)  # the example is a call the tool accepts
        assert following and "例：" in hints.describe(name, TOOLS[name].description)


@pytest.mark.parametrize("tier", list(Tier))
def test_prompts_and_resources_follow_the_tier(client, world, tier) -> None:  # type: ignore[no-untyped-def]
    csrf = login(client, world.admin_email)
    mcp = mcp_for(client, world, csrf, tier=tier.value)
    scopes = TIER_SCOPES[tier]
    listed = {p["name"] for p in mcp.rpc("prompts/list")["prompts"]}
    built_in = [playbooks.clean(p, p["code"]) for p in playbooks.BUILT_IN]
    expected = {p["code"] for p in built_in if playbooks.usable(p, scopes)}
    assert listed == expected
    if tier is Tier.USER_READ:
        assert {"monthly_review", "check_site_topups"} <= listed and "import_screenshots" not in listed
    if tier is Tier.USER_WRITE:
        assert "import_screenshots" in listed and not {"fix_and_save_rule", "undo_ai_run"} & listed
    if tier is Tier.ADMIN_WRITE:
        assert set(REQUIRED) <= listed
    resources = {r["uri"] for r in mcp.rpc("resources/list")["resources"]}
    assert {"ledger://handbook", "ledger://playbooks"} <= resources
    admin = tier in (Tier.ADMIN_READ, Tier.ADMIN_WRITE)
    assert ("ledger://rules" in resources) is admin and ("ledger://fee-rules" in resources) is admin
    groups = {g["group"]: g["tools"] for g in mcp.call("get_context")["data"]["tool_groups"]}
    usable = {t.name for t in TOOLS.values() if permitted(t, scopes)}
    assert {t for tools in groups.values() for t in tools} == usable
    assert ("记账" in groups) is (tier in (Tier.USER_WRITE, Tier.ADMIN_WRITE))
    described = next(t for t in mcp.rpc("tools/list")["tools"] if t["name"] == "get_context")
    assert described["_meta"]["bookkeeper/group"] == "开始" and "下一步：" in described["description"]


def test_prompts_render_and_resources_read(client, world) -> None:
    csrf = login(client, world.admin_email)
    admin = mcp_for(client, world, csrf, tier="admin_write")
    got = admin.rpc("prompts/get", {"name": "check_site_topups", "arguments": {"site": "api.example.com"}})
    text = got["messages"][0]["content"]["text"]
    assert text.startswith("# 场景：核对某站点充值") and "api.example.com" in text and "完成标准：" in text
    assert "工具顺序：search_counterparties → search_transactions" in text
    handbook = admin.rpc("resources/read", {"uri": "ledger://handbook"})["contents"][0]["text"]
    assert "# 识别规则手册" in handbook and "门槛" in handbook
    snapshot = admin.rpc("resources/read", {"uri": "ledger://rules"})["contents"][0]["text"]
    assert all(key in snapshot for key in ('"rules"', '"fee_rules"', '"channels"', '"ignore_rules"'))
    steps = admin.rpc("resources/read", {"uri": "ledger://playbooks"})["contents"][0]["text"]
    assert steps.count("# 场景：") == len(playbooks.BUILT_IN)

    reader = Mcp(client, create_token(client, world.book_id, csrf, tier="user_read", mcp_enabled=True)["token"])
    for method, params in (
        ("resources/read", {"uri": "ledger://rules"}),
        ("prompts/get", {"name": "undo_ai_run", "arguments": {}}),
        ("prompts/get", {"name": "monthly_review", "arguments": {}}),  # month is required
    ):
        body = {"jsonrpc": "2.0", "id": 9, "method": method, "params": params}
        answer = client.post("/mcp", headers=reader.headers, json=body).json()
        assert "error" in answer, (method, params)


def test_a_book_changes_a_playbook_and_both_sides_follow(client, world, app, monkeypatch) -> None:
    from bookkeeper import config

    monkeypatch.setattr(app.state.settings, "ai_api_key", SecretStr("sk-test-playbook"))
    monkeypatch.setattr(config, "get_settings", lambda: app.state.settings)
    csrf = login(client, world.admin_email)
    b = f"/api/v1/books/{world.book_id}/ai/playbooks"
    listed = {p["code"]: p for p in client.get(b).json()["data"]}
    topups = listed["check_site_topups"]
    assert topups["built_in"] and not topups["changed"] and set(topups["tiers"]) == set(t.value for t in Tier)
    assert listed["undo_ai_run"]["tiers"] == ["admin_write"]
    body = {k: topups[k] for k in ("title", "when", "steps", "tools", "done", "arguments")}
    body["steps"] = [*body["steps"], "最后把差异表写给用户，标出每笔的订单号。"]
    saved = client.put(f"{b}/check_site_topups", json=body | {"expected_version": 0}, headers=write_headers(csrf))
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["changed"] and saved.json()["data"]["version"] == 1
    wrong = client.put(
        f"{b}/my_own", json=body | {"tools": ["no_such_tool"], "expected_version": 0}, headers=write_headers(csrf)
    )
    assert wrong.status_code == 422 and "no_such_tool" in wrong.json()["detail"]

    admin = mcp_for(client, world, csrf, tier="admin_write")
    text = admin.rpc("prompts/get", {"name": "check_site_topups", "arguments": {"site": "x.example.com"}})
    assert "标出每笔的订单号" in text["messages"][0]["content"]["text"]

    backend = install(monkeypatch, ScriptBackend(["好"]))
    run = client.post(
        f"/api/v1/books/{world.book_id}/agent/runs",
        json={"instruction": "核对 x.example.com 的充值", "playbook": "check_site_topups", "tier": "user_read"},
        headers=write_headers(csrf),
    )
    assert run.status_code == 201, run.text
    from bookkeeper.jobs.worker import Worker

    Worker(app.state.sessionmaker).run_once()
    assert "# 场景：核对某站点充值" in backend.requests[0].system and "标出每笔的订单号" in backend.requests[0].system
    refused = client.post(
        f"/api/v1/books/{world.book_id}/agent/runs",
        json={"instruction": "撤销", "playbook": "undo_ai_run", "tier": "user_write"},
        headers=write_headers(csrf),
    )
    assert refused.status_code == 403 and "所选档位做不了" in refused.json()["detail"]

    reset = client.delete(f"{b}/check_site_topups", headers=write_headers(csrf))
    assert reset.status_code == 200 and reset.json()["data"]["playbook"]["changed"] is False
