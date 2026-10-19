"""The four token tiers: every REST route and every MCP tool, allowed or 403, plus who may hand out which tier.

The spec checks (``test_the_table_matches_the_tiers``) are written from the tier descriptions, independent of the
route table; the matrix then calls every route and tool with each tier and holds the server to the table.
"""

from __future__ import annotations

import io
import re
import uuid

import pytest
from sqlalchemy import text

from bookkeeper.api import permissions
from bookkeeper.api.permissions import BOOK, ROUTES, Need
from bookkeeper.domain.scopes import ROLE_CAPS, TIER_SCOPES, Role, Scope, Tier
from bookkeeper.mcp_api.tools import TOOLS
from bookkeeper.services import books, identity, ratelimit
from bookkeeper.services.context import Actor, RequestContext
from tests.api.conftest import PASSWORD, bearer, create_token, login, write_headers
from tests.api.test_mcp import Mcp

READ_ONLY_POSTS = {("POST", "/checks:run"), ("POST", "/rules:test")}  # compute, change no ledger data


def allows(rule: Need, scopes: frozenset[Scope], *, as_token: bool = True) -> bool:
    if rule.web_only and as_token:
        return False
    held = set(rule.scopes) | (set(rule.as_token) if as_token else set())
    return held <= scopes and (not rule.any_of or bool(set(rule.any_of) & scopes))


def allowed_routes(tier: Tier) -> set[tuple[str, str]]:
    return {key for key, rule in ROUTES.items() if allows(rule, TIER_SCOPES[tier])}


def test_every_book_route_is_in_the_table(app) -> None:
    served = {
        (method.upper(), path.removeprefix(BOOK))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(BOOK)
        for method in operations
    }
    assert served - set(ROUTES) == set(), "routes without a permission entry"
    assert set(ROUTES) - served == set(), "table entries without a route"
    for method, path in served:  # every served path resolves to exactly its own entry
        assert permissions.rule_for(method, concrete(path, "bk_1")) is ROUTES[(method, path)], (method, path)


def test_the_table_matches_the_tiers() -> None:
    def writes(tier: Tier) -> set[tuple[str, str]]:
        return {k for k in allowed_routes(tier) if k[0] != "GET"}

    assert writes(Tier.USER_READ) <= READ_ONLY_POSTS
    assert writes(Tier.ADMIN_READ) <= READ_ONLY_POSTS
    user_write = allowed_routes(Tier.USER_WRITE)
    assert {
        ("POST", "/transactions"),
        ("PATCH", "/transactions/{ref}"),
        ("DELETE", "/transactions/{ref}"),
        ("POST", "/transactions/{ref}:restore"),
        ("POST", "/import-batches:upload"),
        ("POST", "/import-batches/{batch_id}:commit"),
        ("POST", "/import-batches/{batch_id}:decide-matches"),
        ("POST", "/match-suggestions/{suggestion_id}:accept"),
        ("POST", "/counterparties"),
        ("POST", "/dimension-types/{type_code}/values"),
        ("POST", "/change-sets/{change_set_id}:undo"),
    } <= user_write
    management_reads = {
        ("GET", "/members"),
        ("GET", "/audit-events"),
        ("GET", "/rules"),
        ("GET", "/fee-rules"),
        ("GET", "/pairing-rules"),
        ("GET", "/ai/providers"),
        ("GET", "/ai/routes"),
        ("GET", "/mcp-calls"),
    }
    admin_only_writes = {
        ("POST", "/rules"),
        ("POST", "/fee-rules"),
        ("POST", "/pairing-rules"),
        ("PUT", "/members/{user_id}"),
        ("PATCH", ""),
        ("POST", "/accounts"),
        ("POST", "/fx-rates"),
        ("POST", "/tokens"),
    }
    assert not (management_reads | admin_only_writes) & user_write
    assert management_reads <= allowed_routes(Tier.ADMIN_READ)
    assert not management_reads & allowed_routes(Tier.USER_READ)
    web_only = {k for k, rule in ROUTES.items() if rule.web_only}
    assert {("POST", "/ai/providers"), ("PUT", "/ai/routes")} <= web_only
    assert allowed_routes(Tier.ADMIN_WRITE) == set(ROUTES) - web_only


def concrete(path: str, book_id: str) -> str:
    return BOOK.replace("{book_id}", book_id) + re.sub(r"\{(\w+)\}", lambda m: f"missing_{m.group(1)}", path)


@pytest.fixture
def tier_tokens(client, world, monkeypatch) -> dict[Tier, str]:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(ratelimit, "hit", lambda *a, **k: None)  # ~120 calls per token in a few seconds
    csrf = login(client, world.admin_email)
    made = {tier: create_token(client, world.book_id, csrf, tier=tier.value, mcp_enabled=True) for tier in Tier}
    client.cookies.clear()
    return {tier: data["token"] for tier, data in made.items()}


@pytest.mark.parametrize("tier", list(Tier))
def test_every_rest_route_for_each_tier(client, world, tier_tokens, tier) -> None:  # type: ignore[no-untyped-def]
    token = tier_tokens[tier]
    allowed = allowed_routes(tier)
    wrong = []
    for method, path in sorted(ROUTES):
        url = concrete(path, world.book_id)
        headers = bearer(token, **({} if method == "GET" else {"Idempotency-Key": str(uuid.uuid4())}))
        body = None if method in ("GET", "DELETE") else {}
        response = client.request(method, url, headers=headers, json=body)
        expect_ok = (method, path) in allowed
        if response.status_code >= 500 or (response.status_code == 403) == expect_ok:
            wrong.append(f"{method} {path} → {response.status_code} {response.text[:120]}")
    assert wrong == [], f"{tier.value}:\n" + "\n".join(wrong)


@pytest.mark.parametrize("tier", list(Tier))
def test_every_mcp_tool_for_each_tier(client, tier_tokens, tier) -> None:  # type: ignore[no-untyped-def]
    mcp = Mcp(client, tier_tokens[tier])
    scopes = TIER_SCOPES[tier]
    usable = {
        name for name, t in TOOLS.items() if set(t.scopes) <= scopes and (not t.any_of or bool(set(t.any_of) & scopes))
    }
    listed = mcp.tools()
    assert listed == sorted(listed) or len(listed) == len(set(listed))  # deterministic, no duplicates
    assert set(listed) == usable
    if tier in (Tier.USER_READ, Tier.ADMIN_READ):
        assert {TOOLS[n].kind for n in usable} == {"read"}
    if tier is Tier.USER_WRITE:
        assert not usable & {"manage_rule", "manage_fee_rule", "manage_pairing_rule", "get_admin_info"}
    assert ("get_admin_info" in usable) is (Scope.ADMIN_READ in scopes)
    wrong = []
    for name in sorted(TOOLS):
        result = mcp.call(name)
        refused = result["code"] == "FORBIDDEN_SCOPE"
        if refused == (name in usable) or (refused and result.get("status") != 403) or result["code"] == "INTERNAL":
            wrong.append(f"{name} → {result['code']} {result['message'][:80]}")
    assert wrong == [], f"{tier.value}:\n" + "\n".join(wrong)


def test_admin_read_sees_ai_config_through_mcp_without_keys(client, world, app, monkeypatch) -> None:
    from pydantic import SecretStr

    monkeypatch.setattr(app.state.settings, "master_key", SecretStr("m" * 40))
    csrf = login(client, world.admin_email)
    body = {"name": "中转", "kind": "openai_compatible", "base_url": "https://relay.example.com/v1"}
    body |= {"api_key": "sk-matrix-000000000000abcd", "models": ["m-1"]}
    created = client.post(f"/api/v1/books/{world.book_id}/ai/providers", json=body, headers=write_headers(csrf))
    assert created.status_code == 201, created.text
    overseer = Mcp(client, create_token(client, world.book_id, csrf, tier="admin_read", mcp_enabled=True)["token"])
    result = overseer.call("get_admin_info", kind="ai")
    assert result["ok"] and result["data"]["providers"][0]["key_hint"] == "••••abcd"
    assert "sk-matrix" not in str(result)
    members = overseer.call("get_admin_info", kind="members")
    assert members["ok"] and members["data"][0]["role"] == "owner"


def add_member(app, world, email: str, role: Role) -> str:  # type: ignore[no-untyped-def]
    with app.state.sessionmaker() as session, session.begin():
        system = RequestContext(actor=Actor.system(), channel="cli")
        user = identity.create_user(session, system, email=email, display_name=email, password=PASSWORD)
        owner = RequestContext(
            actor=Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER]),
            channel="cli",
            book_id=world.book_id,
        )
        books.set_member(session, owner, user.id, role)
        return str(user.id)


def set_role(app, world, user_id: str, role: Role) -> None:  # type: ignore[no-untyped-def]
    with app.state.sessionmaker() as session, session.begin():
        owner = RequestContext(
            actor=Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER]),
            channel="cli",
            book_id=world.book_id,
        )
        books.set_member(session, owner, user_id, role)


def test_who_may_hand_out_which_tier(client, world, app) -> None:
    add_member(app, world, "keeper@example.com", Role.ACCOUNTANT)
    add_member(app, world, "viewer@example.com", Role.VIEWER)
    url = f"/api/v1/books/{world.book_id}/tokens"
    for email, may in (
        ("keeper@example.com", {Tier.USER_READ, Tier.USER_WRITE}),
        ("viewer@example.com", {Tier.USER_READ}),
        (world.admin_email, set(Tier)),
    ):
        csrf = login(client, email)
        for tier in Tier:
            response = client.post(url, json={"name": tier.value, "tier": tier.value}, headers=write_headers(csrf))
            assert (response.status_code == 201) is (tier in may), (email, tier, response.text)
        client.cookies.clear()
    csrf = login(client, world.admin_email)
    tokens = {tier: create_token(client, world.book_id, csrf, tier=tier.value)["token"] for tier in Tier}
    client.cookies.clear()
    for tier, token in tokens.items():
        response = client.post(url, json={"name": "x"}, headers=bearer(token, **write_headers()))
        assert (response.status_code == 201) is (tier is Tier.ADMIN_WRITE), (tier, response.text)
    old = client.post(
        url,
        json={"name": "x", "preset": "custom", "scopes": ["ledger:read"]},
        headers=bearer(tokens[Tier.ADMIN_WRITE], **write_headers()),
    )
    assert old.status_code == 422  # scopes are not picked one by one any more


def test_a_lowered_role_lowers_its_tokens(client, world, app) -> None:
    deputy = add_member(app, world, "deputy@example.com", Role.ADMIN)
    csrf = login(client, "deputy@example.com")
    token = create_token(client, world.book_id, csrf, tier="admin_write")["token"]
    client.cookies.clear()
    b = f"/api/v1/books/{world.book_id}"
    assert client.get(f"{b}/members", headers=bearer(token)).status_code == 200

    set_role(app, world, deputy, Role.ACCOUNTANT)  # admin_write → user_write
    assert client.get(f"{b}/members", headers=bearer(token)).status_code == 403
    entry = client.post(f"{b}/transactions", json={}, headers=bearer(token, **write_headers()))
    assert entry.status_code == 422  # still may record (the body is just empty)
    csrf = login(client, world.admin_email)
    listed = {t["user_id"]: t for t in client.get(f"{b}/tokens").json()["data"]}
    assert listed[deputy]["tier"] == "admin_write" and listed[deputy]["effective_tier"] == "user_write"
    client.cookies.clear()

    set_role(app, world, deputy, Role.VIEWER)  # → user_read
    refused = client.post(f"{b}/transactions", json={}, headers=bearer(token, **write_headers()))
    assert refused.status_code == 403
    assert client.get(f"{b}/transactions", headers=bearer(token)).status_code == 200


def test_user_tiers_read_their_own_uploads_only(client, world, app) -> None:
    add_member(app, world, "keeper@example.com", Role.ACCOUNTANT)
    csrf = login(client, world.admin_email)
    upload = client.post(
        f"/api/v1/books/{world.book_id}/files",
        files={"file": ("owner.txt", io.BytesIO(b"owner's"), "text/plain")},
        headers=write_headers(csrf),
    )
    file_id = upload.json()["data"]["id"]
    overseer = create_token(client, world.book_id, csrf, tier="admin_read")["token"]
    client.cookies.clear()
    csrf = login(client, "keeper@example.com")
    keeper = create_token(client, world.book_id, csrf, tier="user_read")["token"]
    client.cookies.clear()
    content = f"/api/v1/books/{world.book_id}/files/{file_id}/content"
    assert client.get(content, headers=bearer(keeper)).status_code == 404
    assert client.get(content, headers=bearer(overseer)).status_code == 200


def test_migration_maps_presets_to_tiers(pg_server, capsys) -> None:  # type: ignore[no-untyped-def]
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from bookkeeper.paths import ALEMBIC_INI

    name = f"bk_tiers_{uuid.uuid4().hex[:8]}"
    admin = create_engine(pg_server.admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name} TEMPLATE bk_template"))
    url = pg_server.url_for(name)
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = url
    engine = create_engine(url)
    try:
        command.downgrade(config, "0013")
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, display_name, password_hash) VALUES ('usr_1', 'a@x.test', 'A', 'x');"
                    "INSERT INTO books (id, name, base_commodity) VALUES ('bk_1', 'B', 'CNY')"
                )
            )
            rows = [
                ("tok_r", "reader", ["ledger:read"]),
                ("tok_b", "bookkeeper", ["import:write", "ledger:read", "ledger:write", "reference:write"]),
                ("tok_a", "admin", ["admin", "config:write", "ledger:read"]),
                ("tok_c1", "custom", ["ledger:read", "ledger:write", "import:write", "reference:write", "rules:write"]),
                ("tok_c2", "custom", ["ledger:read", "admin:read"]),
                ("tok_c3", "custom", ["ledger:write"]),
            ]
            for token_id, preset, scopes in rows:
                conn.execute(
                    text(
                        "INSERT INTO api_tokens (id, book_id, user_id, name, token_hash, token_prefix, scopes, preset,"
                        " created_by) VALUES (:id, 'bk_1', 'usr_1', :id, :hash, 'p', :scopes, :preset, 'usr_1')"
                    ),
                    {"id": token_id, "hash": token_id.ljust(64, "0"), "scopes": scopes, "preset": preset},
                )
        capsys.readouterr()
        command.upgrade(config, "head")
        report = capsys.readouterr().out
        with engine.connect() as conn:
            tiers = dict(conn.execute(text("SELECT id, tier FROM api_tokens")).all())
            revoked = {r for (r,) in conn.execute(text("SELECT id FROM api_tokens WHERE revoked_at IS NOT NULL"))}
        assert tiers == {
            "tok_r": "user_read",
            "tok_b": "user_write",
            "tok_a": "admin_write",
            "tok_c1": "user_write",
            "tok_c2": "admin_read",
            "tok_c3": "user_read",
        }
        assert revoked == {"tok_c3"}
        assert "tok_c1" in report and "不再有 rules:write" in report and "tok_c3" in report and "已吊销" in report
        command.downgrade(config, "0013")
        with engine.connect() as conn:
            back = dict(conn.execute(text("SELECT id, preset FROM api_tokens")).all())
        assert back["tok_r"] == "reader" and back["tok_c2"] == "custom" and back["tok_a"] == "admin"
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


def test_gate_runs_before_the_body_is_validated(client, world) -> None:
    csrf = login(client, world.admin_email)
    reader = create_token(client, world.book_id, csrf, tier="user_read")["token"]
    client.cookies.clear()
    garbage = client.post(
        f"/api/v1/books/{world.book_id}/transactions", json={"nonsense": 1}, headers=bearer(reader, **write_headers())
    )
    assert garbage.status_code == 403 and garbage.json()["code"] == "FORBIDDEN_SCOPE"
    assert permissions.ROUTES[("POST", "/transactions")].scopes == (Scope.LEDGER_WRITE,)
