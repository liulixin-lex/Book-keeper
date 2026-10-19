"""AI 识别 pipeline (docs/19 §4): page types, the deterministic checks, exact channel resolution, rules first and
AI suggestions after with a threshold, the 识别规则手册 as versioned data, and 存为规则. Recorded answers only."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from bookkeeper.jobs.worker import Worker
from bookkeeper.services.ai_extract import _COMMON, PAGE_TYPES
from tests.ai_fakes import FileBackend, install
from tests.api.conftest import login, write_headers
from tests.api.test_business import counterparty
from tests.api.test_imports import post, source


@pytest.fixture
def ready(app, monkeypatch) -> Any:  # type: ignore[no-untyped-def]
    from bookkeeper import config

    monkeypatch.setattr(app.state.settings, "ai_api_key", SecretStr("sk-test-pipeline"))
    monkeypatch.setattr(config, "get_settings", lambda: app.state.settings)
    return app.state.settings


def row(kind: str, **kw: Any) -> dict[str, Any]:
    """A row with exactly the fields its page type has (the schema allows no others)."""
    fields = [*_COMMON, *PAGE_TYPES[kind][1]]
    out = dict.fromkeys(fields) | {"direction": "out", "amount": "8.00"} | kw
    assert set(out) <= set(fields), set(out) - set(fields)
    return out


def read(client: Any, app: Any, world: Any, csrf: str, src: str, names: list[str]) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/books/{world.book_id}/import-batches:upload",
        headers=write_headers(csrf),
        data={"source": src},
        files=[("file", (n, f"PNG {n}".encode(), "image/png")) for n in names],
    )
    assert response.status_code == 201, response.text
    Worker(app.state.sessionmaker).run_once()
    batch_id = response.json()["data"]["id"]
    batch = client.get(f"/api/v1/books/{world.book_id}/import-batches/{batch_id}").json()["data"]
    records = client.get(f"/api/v1/books/{world.book_id}/source-records", params={"batch_id": batch_id}).json()
    return batch | {"rows": records["data"]}


def test_page_types_years_future_dates_and_channels(client, world, app, ready, monkeypatch) -> None:
    def answer(name: str, mime: str, text: str) -> dict[str, Any]:
        return {
            "page_type": "order_list",
            "site": None,
            "records": [
                row(
                    "order_list",
                    occurred_at="--10-05 12:00:00",
                    order_no="A1",
                    channel="链动小铺",
                    description="示例 Plus 成品号",
                ),
                row("order_list", occurred_at="2099-01-02 08:00:00", order_no="A2", amount="9.00"),
                row("order_list", occurred_at="2026-10-06 09:00:00", order_no="A3", amount="¥ abc"),
            ],
            "totals": ["共 3 条"],
            "unreadable": [],
        }

    backend = install(monkeypatch, FileBackend(answer))
    csrf = login(client, world.admin_email)
    source(client, world.book_id, csrf, "shots", "ai_extract", defaults={"out": {"type": "expense"}})
    batch = read(client, app, world, csrf, "shots", ["orders.png"])
    system = backend.requests[0][1].system
    assert "# 识别规则手册" in system and "订单列表（order_list）" in system  # the default handbook
    page_types = backend.requests[0][1].schema["properties"]["page"]["anyOf"]
    assert {p["properties"]["page_type"]["enum"][0] for p in page_types} == {
        "order_list",
        "topup_log",
        "wallet_bill",
        "receipt",
        "other",
    }
    messages = {c["code"]: c["message"] for c in batch["summary"]["checks"]}
    assert "1 条按上传日期推断" in messages["ai_year"] and "2099-01-02" in messages["ai_future_date"]
    assert any("金额读不清" in u for u in batch["summary"]["extraction"]["unreadable"])
    by_order = {r["order_no"]: r for r in batch["rows"]}
    assert set(by_order) == {"A1"}  # the future row is refused at staging, the unreadable one never staged
    first = by_order["A1"]
    assert first["occurred_at"].startswith("2026-10-05")  # the upload year
    assert first["classification"]["inputs"]["channel"] == "liandong"  # alias 链动小铺, exactly
    assert first["extracted"]["page_type"] == "order_list"


def test_rules_first_then_suggestions_with_a_threshold(client, world, app, ready, monkeypatch) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "OpenAI")
    post(
        client,
        b,
        csrf,
        "rules",
        {
            "code": "vps",
            "condition": {"field": "description", "op": "contains", "value": "VPS"},
            "actions": [
                {"type": "set_transaction_type", "value": "expense"},
                {"type": "set_category", "value": "5401.04"},
            ],
        },
        201,
    )

    def month(name: str) -> str:  # the second upload is next month's bill, not a copy of the first
        return "2026-10" if name == "r2.png" else "2026-09"

    def answer(name: str, mime: str, text: str) -> dict[str, Any]:
        return {
            "page_type": "receipt",
            "site": None,
            "records": [
                row(
                    "receipt",
                    occurred_at=month(name) + "-01",
                    counterparty="OpenAI",
                    description="ChatGPT Pro 订阅",
                    amount="200.00",
                ),
                row(
                    "receipt",
                    occurred_at=month(name) + "-02",
                    counterparty="某云",
                    description="VPS 月付",
                    amount="30.00",
                ),
                row(
                    "receipt",
                    occurred_at=month(name) + "-03",
                    counterparty="不认识的店",
                    description="杂项",
                    amount="5.00",
                ),
                row(
                    "receipt",
                    occurred_at=month(name) + "-04",
                    counterparty="某站",
                    description="赠送额度",
                    amount="0.00",
                ),
            ],
            "totals": [],
            "unreadable": [],
        }

    sent: list[str] = []

    def suggest(text: str) -> list[dict[str, Any]]:
        sent.append(text)
        lines = [line for line in text.splitlines() if line[:1] == "#" and line[1:2].isdigit()]
        index = {next(w for w in ("Pro", "杂项", "赠送") if w in line): int(line[1:].split(" ")[0]) for line in lines}
        return [
            {
                "index": index["Pro"],
                "type": "expense",
                "counterparty": "OpenAI",
                "category": "5401.03",
                "channel": None,
                "ignore": None,
                "confidence": 0.95,
                "reason": "OpenAI 订阅属于 AI 服务订阅",
            },
            {
                "index": index["杂项"],
                "type": "expense",
                "counterparty": "不认识的店",  # not in the book: dropped, never created
                "category": "5602.99",
                "channel": None,
                "ignore": None,
                "confidence": 0.4,
                "reason": "看不出用途",
            },
            {
                "index": index["赠送"],
                "type": None,
                "counterparty": None,
                "category": None,
                "channel": None,
                "ignore": "赠送额度，不是付款",
                "confidence": 0.9,
                "reason": "金额为 0 的赠送",
            },
        ]

    install(monkeypatch, FileBackend(answer, suggest))
    source(client, b, csrf, "bills", "ai_extract", defaults={"out": {"type": "expense"}})
    batch = read(client, app, world, csrf, "bills", ["r.png"])
    rows = {r["description"]: r for r in batch["rows"]}
    assert "VPS" not in sent[0] and "5401.03" in sent[0] and "OpenAI" in sent[0]  # rules first; the book's names
    pro = rows["ChatGPT Pro 订阅"]
    assert pro["status"] == "classified" and pro["classification"]["inputs"]["category"] == "5401.03"
    assert pro["classification"]["ai"]["auto"] is True and pro["classification"]["counterparty"] == "OpenAI"
    vague = rows["杂项"]
    assert vague["status"] == "new" and vague["classification"]["review"] == ["ai_low_confidence"]
    assert vague["classification"]["inputs"]["category"] == "5602.99" and not vague["classification"].get(
        "counterparty"
    )
    assert rows["赠送额度"]["status"] == "ignored" and rows["赠送额度"]["ignore_reason"] == "AI：赠送额度，不是付款"
    assert rows["VPS 月付"]["classification"]["inputs"]["category"] == "5401.04"

    # A person confirms the vague one: the suggestion and the 待确认 flag go, the choice is locked.
    confirmed = client.patch(
        f"/api/v1/books/{b}/source-records/{vague['id']}",
        json={"type": "expense", "inputs": {"category": "5602.99"}},
        headers=write_headers(csrf),
    ).json()["data"]
    assert confirmed["status"] == "classified" and "ai" not in confirmed["classification"]

    # Raising the threshold in the handbook sends even a 0.95 suggestion to 待确认 next time.
    current = client.get(f"/api/v1/books/{b}/ai/handbook").json()["data"]
    assert current["version"] == 0 and current["is_default"] is True
    saved = client.put(
        f"/api/v1/books/{b}/ai/handbook",
        json={"content": current["content"] + "\n- 订阅一律确认。", "threshold": 0.99, "expected_version": 0},
        headers=write_headers(csrf),
    ).json()["data"]
    assert saved["version"] == 1 and saved["threshold"] == 0.99
    again = read(client, app, world, csrf, "bills", ["r2.png"])
    pro2 = next(r for r in again["rows"] if r["description"] == "ChatGPT Pro 订阅")
    assert pro2["status"] == "new" and pro2["classification"]["review"] == ["ai_low_confidence"]


def test_the_handbook_is_versioned_data(client, world, app, ready, monkeypatch) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    url = f"/api/v1/books/{b}/ai/handbook"
    first = client.put(url, json={"content": "# 手册 1", "expected_version": 0}, headers=write_headers(csrf))
    assert first.status_code == 200 and first.json()["data"]["threshold"] == 0.85
    stale = client.put(url, json={"content": "# 冲突", "expected_version": 0}, headers=write_headers(csrf))
    assert stale.status_code == 409
    client.put(url, json={"content": "# 手册 2", "expected_version": 1, "note": "改写"}, headers=write_headers(csrf))
    restored = client.post(f"{url}:restore", json={"version": 1, "expected_version": 2}, headers=write_headers(csrf))
    assert restored.status_code == 200 and restored.json()["data"]["content"] == "# 手册 1"
    listed = client.get(url).json()["data"]
    assert [v["version"] for v in listed["versions"]] == [3, 2, 1] and listed["versions"][0]["note"] == "恢复版本 1"

    seen: list[str] = []

    def answer(name: str, mime: str, text: str) -> dict[str, Any]:
        return {"records": [], "site": None, "totals": [], "unreadable": []}

    backend = install(monkeypatch, FileBackend(answer))
    source(client, b, csrf, "shots", "ai_extract", defaults={"out": {"type": "expense"}})
    read(client, app, world, csrf, "shots", ["x.png"])
    seen.append(backend.requests[0][1].system)
    assert seen[0].endswith("# 手册 1")


def test_save_as_rule_from_a_corrected_record(client, world, app, ready, monkeypatch) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    counterparty(client, b, csrf, "Example Cloud")

    def answer(name: str, mime: str, text: str) -> dict[str, Any]:
        return {
            "page_type": "wallet_bill",
            "site": None,
            "records": [
                row(
                    "wallet_bill",
                    occurred_at="2026-10-01 10:00:00",
                    counterparty="EXAMPLE CLOUD LTD",
                    amount="12.00",
                    order_no="W1",
                ),
                row(
                    "wallet_bill",
                    occurred_at="2026-10-02 10:00:00",
                    counterparty="EXAMPLE CLOUD LTD",
                    amount="13.00",
                    order_no="W2",
                ),
            ],
            "totals": [],
            "unreadable": [],
        }

    install(monkeypatch, FileBackend(answer))
    source(client, b, csrf, "wallet", "ai_extract", defaults={"out": {"type": "expense"}})
    batch = read(client, app, world, csrf, "wallet", ["w.png"])
    first, second = sorted(batch["rows"], key=lambda r: r["order_no"])
    assert first["status"] == second["status"] == "new"
    client.patch(
        f"/api/v1/books/{b}/source-records/{first['id']}",
        json={"type": "expense", "counterparty": "Example Cloud", "inputs": {"category": "5401.04"}},
        headers=write_headers(csrf),
    )
    saved = post(client, b, csrf, f"source-records/{first['id']}:save-rule", {})
    rule = saved["rule"]
    assert rule["condition"] == {
        "all": [
            {"field": "direction", "op": "eq", "value": "out"},
            {"field": "counterparty_text", "op": "eq", "value": "EXAMPLE CLOUD LTD"},
        ]
    }
    assert {a["type"] for a in rule["actions"]} == {"set_transaction_type", "set_counterparty", "set_category"}
    assert rule["name"] == "EXAMPLE CLOUD LTD → 费用支出" and saved["reclassified"] >= 1
    other = client.get(f"/api/v1/books/{b}/source-records", params={"batch_id": batch["id"]}).json()["data"]
    follow = next(r for r in other if r["order_no"] == "W2")
    assert follow["status"] == "classified" and follow["classification"]["counterparty"] == "Example Cloud"
    again = post(client, b, csrf, f"source-records/{first['id']}:save-rule", {})
    assert again["rule"]["code"] == rule["code"] and again["rule"]["version"] == 2  # updated, not copied
