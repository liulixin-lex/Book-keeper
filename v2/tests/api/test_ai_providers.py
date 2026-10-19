"""设置 → AI: providers with sealed keys, task routing with backups, usage, and who may change them."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from bookkeeper.ai.adapters import Target
from bookkeeper.db.models import AiProvider, AuditEvent, IdempotencyKey
from bookkeeper.domain.errors import DomainError
from tests.ai_fakes import FileBackend, install
from tests.api.conftest import bearer, create_token, login, write_headers

KEY = "sk-test-0000000000000000000000001234"


@pytest.fixture
def master(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(app.state.settings, "master_key", SecretStr("m" * 40))


def api(client: Any, method: str, path: str, csrf: str | None, expect: int, **kw: Any) -> dict[str, Any]:
    response = client.request(method, path, headers=write_headers(csrf) | kw.pop("headers", {}), **kw)
    assert response.status_code == expect, response.text
    return response.json()


def provider(client: Any, b: str, csrf: str, **body: Any) -> dict[str, Any]:
    payload = {
        "name": "主力",
        "kind": "openai_compatible",
        "base_url": "https://relay.example.com/v1",
        "api_key": KEY,
        "models": ["model-a", "model-b"],
        "default_model": "model-a",
    } | body
    return api(client, "POST", f"/api/v1/books/{b}/ai/providers", csrf, 201, json=payload)["data"]


def test_keys_are_sealed_never_shown_and_bound_to_the_url(client, world, app, master) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    created = provider(client, b, csrf)
    assert created["key_hint"] == "••••1234" and "api_key" not in created and KEY not in str(created)
    assert created["capabilities"]["pdf"] is False  # OpenAI-compatible defaults: no PDF input
    listed = api(client, "GET", f"/api/v1/books/{b}/ai/providers", None, 200)["data"]
    assert KEY not in str(listed)
    with app.state.sessionmaker() as session:
        row = session.get(AiProvider, created["id"])
        assert row is not None and row.api_key_sealed and KEY not in row.api_key_sealed
        events = list(session.execute(select(AuditEvent)).scalars())
        assert "ai_provider.create" in {e.action for e in events}
        assert not [e.action for e in events if KEY in f"{e.before}{e.after}{e.diff}"]
        replays = list(session.execute(select(IdempotencyKey)).scalars())
        assert replays and not [r for r in replays if KEY in f"{r.request_hash}{r.response_body}"]

    moved = api(
        client,
        "PATCH",
        f"/api/v1/books/{b}/ai/providers/{created['id']}",
        csrf,
        422,
        json={"expected_version": created["version"], "base_url": "https://other.example.com/v1"},
    )
    assert "重新填写 API 密钥" in moved["detail"]
    renamed = api(
        client,
        "PATCH",
        f"/api/v1/books/{b}/ai/providers/{created['id']}",
        csrf,
        200,
        json={
            "expected_version": created["version"],
            "base_url": "https://other.example.com/v1",
            "api_key": "sk-new-key-9999",
            "timeout_seconds": 30,
        },
    )["data"]
    assert renamed["key_hint"] == "••••9999" and renamed["base_url"] == "https://other.example.com/v1"

    # The sealed key only opens for the provider and address it was saved for.
    from bookkeeper.ai import secrets

    with app.state.sessionmaker() as session:
        row = session.get(AiProvider, created["id"])
        assert row is not None and row.api_key_sealed
        settings = app.state.settings
        assert secrets.unseal(row.api_key_sealed, settings, f"{row.id}|{row.base_url}") == "sk-new-key-9999"
        with pytest.raises(DomainError):
            secrets.unseal(row.api_key_sealed, settings, f"{row.id}|https://relay.example.com/v1")


def test_without_a_master_key_nothing_is_stored(client, world) -> None:
    csrf = login(client, world.admin_email)
    body = {"name": "x", "kind": "anthropic", "api_key": KEY, "models": ["m"]}
    failed = api(client, "POST", f"/api/v1/books/{world.book_id}/ai/providers", csrf, 409, json=body)
    assert "BK_MASTER_KEY" in failed["detail"]


def test_tokens_cannot_change_providers_even_as_admin(client, world, master) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    token = create_token(client, b, csrf, preset="admin")["token"]
    body = {"name": "x", "kind": "anthropic", "api_key": KEY, "models": ["m"]}
    refused = client.post(f"/api/v1/books/{b}/ai/providers", json=body, headers=bearer(token, **write_headers()))
    assert refused.status_code == 403 and "网页端" in refused.json()["detail"]
    created = provider(client, b, csrf)
    readable = client.get(f"/api/v1/books/{b}/ai/providers", headers=bearer(token))
    assert readable.status_code == 200 and KEY not in readable.text
    reader = create_token(client, b, csrf, preset="reader")["token"]
    assert client.get(f"/api/v1/books/{b}/ai/providers", headers=bearer(reader)).status_code == 403
    assert client.get(f"/api/v1/books/{b}/ai/status", headers=bearer(reader)).status_code == 200
    test = client.post(f"/api/v1/books/{b}/ai/providers/{created['id']}:test", headers=bearer(token, **write_headers()))
    assert test.status_code == 403


def test_recognition_uses_the_routed_providers_in_order_and_counts_usage(
    client, world, app, master, monkeypatch
) -> None:
    from bookkeeper import config
    from bookkeeper.jobs.worker import Worker

    monkeypatch.setattr(config, "get_settings", lambda: app.state.settings)
    csrf = login(client, world.admin_email)
    b = world.book_id
    down = provider(client, b, csrf, name="备用前的主力", base_url="https://down.example.com/v1")
    up = provider(
        client,
        b,
        csrf,
        name="备用",
        base_url="https://up.example.com/v1",
        prices={"model-a": {"input": 3, "output": 15}},
    )
    status = api(client, "GET", f"/api/v1/books/{b}/ai/status", None, 200)["data"]
    assert status == {"extract": False, "agent": False}  # nothing routed and no BK_AI_* key
    routes = {"extract": [{"provider_id": down["id"]}, {"provider_id": up["id"], "model": "model-a"}], "agent": []}
    saved = api(client, "PUT", f"/api/v1/books/{b}/ai/routes", csrf, 200, json=routes)["data"]
    assert [r["provider_name"] for r in saved["extract"]] == ["备用前的主力", "备用"]
    assert api(client, "GET", f"/api/v1/books/{b}/ai/status", None, 200)["data"]["extract"] is True

    seen: list[tuple[str, str]] = []

    def answer(name: str, mime: str, text: str) -> dict[str, Any]:
        target: Target = backend.requests[-1][0]
        seen.append((target.provider_name, target.base_url or ""))
        if target.base_url == "https://down.example.com/v1":
            raise DomainError("AI_UNAVAILABLE", "AI 服务暂时连不上，请稍后再试。")
        assert target.api_key == KEY
        row = dict.fromkeys(("currency", "fee", "quantity", "face", "order_no", "status", "counterparty"))
        row |= {"occurred_at": "2026-10-05 12:00:00", "direction": "out", "amount": "8.00", "description": "测试"}
        return {
            "page_kind": "订单",
            "site": None,
            "records": [row],
            "totals": [],
            "unreadable": [],
            "_usage": {"input_tokens": 1_000_000, "output_tokens": 100_000},
        }

    backend = install(monkeypatch, FileBackend(answer))
    api(
        client,
        "POST",
        f"/api/v1/books/{b}/import-sources",
        csrf,
        201,
        json={"code": "shots", "kind": "ai_extract", "config": {"defaults": {"out": {"type": "expense"}}}},
    )
    upload = client.post(
        f"/api/v1/books/{b}/import-batches:upload",
        headers=write_headers(csrf),
        data={"source": "shots"},
        files=[("file", ("1.png", b"PNG", "image/png"))],
    )
    assert upload.status_code == 201, upload.text
    Worker(app.state.sessionmaker).run_once()
    batch = api(client, "GET", f"/api/v1/books/{b}/import-batches/{upload.json()['data']['id']}", None, 200)["data"]
    assert batch["status"] == "parsed" and batch["summary"]["records"] == 1
    assert seen == [("备用前的主力", "https://down.example.com/v1"), ("备用", "https://up.example.com/v1")]
    usage = api(client, "GET", f"/api/v1/books/{b}/ai/usage", None, 200)["data"]["items"]
    by_provider = {u["provider"]: u for u in usage}
    assert by_provider["备用"]["input_tokens"] == 1_000_000 and by_provider["备用"]["cost_usd"] == pytest.approx(4.5)
    assert by_provider["备用前的主力"]["calls"] == 1 and by_provider["备用前的主力"]["cost_usd"] is None


def test_test_connection_lists_models_and_answers(client, world, master, monkeypatch) -> None:
    from tests.ai_fakes import ScriptBackend

    csrf = login(client, world.admin_email)
    b = world.book_id
    created = provider(client, b, csrf)
    install(monkeypatch, ScriptBackend(["OK"]))
    result = api(client, "POST", f"/api/v1/books/{b}/ai/providers/{created['id']}:test", csrf, 200)["data"]
    assert result["ok"] is True and result["reply"] == "OK" and result["models"] == ["model-a"]
    assert result["capabilities"]["tools"] is True


def test_deleting_a_provider_drops_it_from_routing(client, world, master) -> None:
    csrf = login(client, world.admin_email)
    b = world.book_id
    first = provider(client, b, csrf)
    api(client, "PUT", f"/api/v1/books/{b}/ai/routes", csrf, 200, json={"extract": [{"provider_id": first["id"]}]})
    api(client, "DELETE", f"/api/v1/books/{b}/ai/providers/{first['id']}", csrf, 200)
    assert api(client, "GET", f"/api/v1/books/{b}/ai/routes", None, 200)["data"]["extract"] == []
    wrong = api(
        client, "PUT", f"/api/v1/books/{b}/ai/routes", csrf, 422, json={"agent": [{"provider_id": "aip_missing"}]}
    )
    assert "不存在" in wrong["detail"]
