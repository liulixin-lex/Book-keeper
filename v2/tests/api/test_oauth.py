"""OAuth 2.1 for remote MCP clients: discovery, registration, PKCE authorize, sign-in and consent, tokens."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from bookkeeper.config import Settings
from bookkeeper.main import create_app
from bookkeeper.services import books, identity
from bookkeeper.services.context import Actor, RequestContext
from tests.api.conftest import PASSWORD, World

CALLBACK = "https://claude.ai/api/mcp/auth_callback"
BASE = "http://localhost"


@pytest.fixture
def oauth_client(database_url: str, data_dir) -> Iterator[tuple[TestClient, World]]:  # type: ignore[no-untyped-def]
    settings = Settings(
        database_url=database_url,
        data_dir=data_dir,
        public_url=BASE,
        log_json=False,
        mcp_write_enabled=True,
        oauth_enabled=True,
    )
    app = create_app(settings, configure_logs=False)
    ctx = RequestContext(actor=Actor.system(), channel="cli")
    with app.state.sessionmaker() as session, session.begin():
        admin = identity.create_user(
            session, ctx, email="owner@example.com", display_name="所有者", password=PASSWORD, is_superadmin=False
        )
        book = books.create_book(session, ctx, name="主账套", owner_user_id=admin.id)
        world = World(admin.id, admin.email, book.id)
    with TestClient(app, base_url=BASE) as client:
        yield client, world
    app.state.engine.dispose()


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def register(client: TestClient, **extra: Any) -> dict[str, Any]:
    body = {
        "client_name": "Claude",
        "redirect_uris": [CALLBACK],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    } | extra
    response = client.post("/oauth/register", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def hidden(page: str) -> dict[str, str]:
    return dict(re.findall(r'name="(request|csrf)" value="([^"]+)"', page))


def start(client: TestClient, client_id: str, challenge: str, state: str = "st-1") -> dict[str, str]:
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "resource": f"{BASE}/mcp",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    login_url = response.headers["location"]
    assert login_url.startswith(f"{BASE}/oauth/login?request=")
    page = client.get(login_url)
    assert page.status_code == 200 and "授权 Claude" in page.text and "claude.ai" in page.text
    assert page.headers["x-frame-options"] == "DENY"
    return hidden(page.text)


def sign_in_and_approve(client: TestClient, fields: dict[str, str], preset: str = "bookkeeper") -> str:
    signed = client.post(
        "/oauth/login",
        data=fields | {"action": "signin", "email": "owner@example.com", "password": PASSWORD},
        follow_redirects=False,
    )
    assert signed.status_code == 303, signed.text
    consent = client.get(signed.headers["location"])
    assert "访问级别" in consent.text
    book = re.search(r'<option value="([^"]+)"', consent.text)
    assert book
    approved = client.post(
        "/oauth/login",
        data=hidden(consent.text) | {"action": "approve", "book": book.group(1), "preset": preset},
        follow_redirects=False,
    )
    assert approved.status_code == 303, approved.text
    location: str = approved.headers["location"]
    return location


def token(client: TestClient, **form: str) -> Any:
    return client.post("/oauth/token", data=form)


def mcp_status(client: TestClient, access_token: str) -> int:
    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    return response.status_code


def test_full_oauth_flow(oauth_client) -> None:  # type: ignore[no-untyped-def]
    client, _world = oauth_client
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == f"{BASE}/mcp" and resource["authorization_servers"] == [f"{BASE}/"]
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["token_endpoint"] == f"{BASE}/oauth/token" and meta["code_challenge_methods_supported"] == ["S256"]
    unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert unauth.status_code == 401 and "resource_metadata=" in unauth.headers["www-authenticate"]

    bad = client.post("/oauth/register", json={"redirect_uris": ["http://evil.example/cb"], "client_name": "x"})
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_redirect_uri"
    registered = register(client)
    client_id = registered["client_id"]

    verifier, challenge = pkce()
    fields = start(client, client_id, challenge)
    wrong = client.post(
        "/oauth/login", data=fields | {"action": "signin", "email": "owner@example.com", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == 401 and "邮箱或密码不正确" in wrong.text

    # signing in binds the request to this browser: another browser holding the same page cannot approve
    signed = client.post(
        "/oauth/login",
        data=fields | {"action": "signin", "email": "owner@example.com", "password": PASSWORD},
        follow_redirects=False,
    )
    assert signed.status_code == 303 and "bk_oauth" in signed.headers["set-cookie"]
    saved = dict(client.cookies)
    client.cookies.clear()
    hijack = client.post("/oauth/login", data=fields | {"action": "approve", "book": _world.book_id, "preset": "admin"})
    assert hijack.status_code == 400 and "登录状态已失效" in hijack.text
    client.cookies.update(saved)
    approved = client.post(
        "/oauth/login",
        data=fields | {"action": "approve", "book": _world.book_id, "preset": "bookkeeper"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    query = parse_qs(urlsplit(approved.headers["location"]).query)
    assert query["state"] == ["st-1"]
    code = query["code"][0]

    wrong_verifier = token(
        client,
        grant_type="authorization_code",
        code=code,
        redirect_uri=CALLBACK,
        client_id=client_id,
        code_verifier="x" * 50,
    )
    assert wrong_verifier.status_code == 400 and wrong_verifier.json()["error"] == "invalid_grant"
    issued = token(
        client,
        grant_type="authorization_code",
        code=code,
        redirect_uri=CALLBACK,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert issued.status_code == 200, issued.text
    first = issued.json()
    assert first["token_type"] == "Bearer" and first["access_token"].startswith("bk_pat_")
    assert "ledger:write" in first["scope"] and "config:write" not in first["scope"]
    reused = token(
        client,
        grant_type="authorization_code",
        code=code,
        redirect_uri=CALLBACK,
        client_id=client_id,
        code_verifier=verifier,
    )
    assert reused.status_code == 400

    assert mcp_status(client, first["access_token"]) == 200
    refreshed = token(client, grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=client_id)
    assert refreshed.status_code == 200, refreshed.text
    second = refreshed.json()
    assert mcp_status(client, first["access_token"]) == 401  # rotated away
    assert mcp_status(client, second["access_token"]) == 200
    replay = token(client, grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=client_id)
    assert replay.status_code == 400
    assert mcp_status(client, second["access_token"]) == 401  # replay of a used refresh token revokes the family


def test_deny_revoke_and_role_cap(oauth_client) -> None:  # type: ignore[no-untyped-def]
    client, world = oauth_client
    client_id = register(client)["client_id"]
    _verifier, challenge = pkce()
    fields = start(client, client_id, challenge, state="deny-me")
    denied = client.post("/oauth/login", data=fields | {"action": "deny"}, follow_redirects=False)
    assert denied.status_code == 303
    assert parse_qs(urlsplit(denied.headers["location"]).query) == {
        "error": ["access_denied"],
        "error_description": ["用户拒绝授权"],
        "state": ["deny-me"],
        "iss": [f"{BASE}/"],
    }
    again = client.get(f"/oauth/login?request={fields['request']}")
    assert again.status_code == 400  # a finished request cannot be reused

    verifier, challenge = pkce()
    location = sign_in_and_approve(client, start(client, client_id, challenge), preset="admin")
    code = parse_qs(urlsplit(location).query)["code"][0]
    issued = token(
        client,
        grant_type="authorization_code",
        code=code,
        redirect_uri=CALLBACK,
        client_id=client_id,
        code_verifier=verifier,
    ).json()
    assert "config:write" in issued["scope"]
    revoked = client.post("/oauth/revoke", data={"token": issued["access_token"], "client_id": client_id})
    assert revoked.status_code == 200
    assert mcp_status(client, issued["access_token"]) == 401
    assert (
        token(
            client, grant_type="refresh_token", refresh_token=issued["refresh_token"], client_id=client_id
        ).status_code
        == 400
    )

    # a viewer can only grant read access
    app = client.app
    ctx = RequestContext(actor=Actor.system(), channel="cli")
    with app.state.sessionmaker() as session, session.begin():  # type: ignore[attr-defined]
        viewer = identity.create_user(session, ctx, email="viewer@example.com", display_name="查看", password=PASSWORD)
        from bookkeeper.db.models import BookMember

        session.add(BookMember(book_id=world.book_id, user_id=viewer.id, role="viewer"))
    _verifier, challenge = pkce()
    fields = start(client, client_id, challenge)
    client.post(
        "/oauth/login",
        data=fields | {"action": "signin", "email": "viewer@example.com", "password": PASSWORD},
        follow_redirects=False,
    )
    consent = client.get(f"/oauth/login?request={fields['request']}")
    assert 'value="admin"' not in consent.text and 'value="reader"' in consent.text
    refused = client.post(
        "/oauth/login", data=hidden(consent.text) | {"action": "approve", "book": world.book_id, "preset": "admin"}
    )
    assert refused.status_code == 403 and "超过" in refused.text


def test_confidential_client_secret_is_hashed(oauth_client) -> None:  # type: ignore[no-untyped-def]
    client, _world = oauth_client
    registered = register(client, token_endpoint_auth_method="client_secret_post")
    secret = registered["client_secret"]
    app = client.app
    from bookkeeper.db.models import OAuthClient

    with app.state.sessionmaker() as session:  # type: ignore[attr-defined]
        stored = session.get(OAuthClient, registered["client_id"])
        assert stored is not None and stored.secret_hash != secret and len(stored.secret_hash or "") == 64
    verifier, challenge = pkce()
    code = parse_qs(urlsplit(sign_in_and_approve(client, start(client, registered["client_id"], challenge))).query)[
        "code"
    ][0]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CALLBACK,
        "client_id": registered["client_id"],
    }
    assert token(client, **form, code_verifier=verifier, client_secret="wrong").status_code == 401
    assert token(client, **form, code_verifier=verifier, client_secret=secret).status_code == 200


def test_oauth_disabled_by_default(client) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404
    unauth = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert "resource_metadata" not in unauth.headers["www-authenticate"]


def test_official_sdk_oauth_client(oauth_client) -> None:  # type: ignore[no-untyped-def]
    """The official MCP client discovers the server from the 401, registers, runs PKCE and calls a tool."""
    import anyio
    import httpx2
    from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

    client, _world = oauth_client
    app = create_app(client.app.state.settings, configure_logs=False)  # type: ignore[attr-defined]  # fresh MCP manager

    class Memory:
        tokens: OAuthToken | None = None
        info: OAuthClientInformationFull | None = None

        async def get_tokens(self) -> OAuthToken | None:
            return self.tokens

        async def set_tokens(self, tokens: OAuthToken) -> None:
            self.tokens = tokens

        async def get_client_info(self) -> OAuthClientInformationFull | None:
            return self.info

        async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
            self.info = client_info

    redirect: dict[str, str] = {}

    async def main() -> tuple[dict[str, Any], Memory]:
        storage = Memory()
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url=BASE, follow_redirects=False) as browser:

            async def redirect_handler(url: str) -> None:  # the "browser": sign in and approve
                page = await browser.get(url)
                login = await browser.get(page.headers["location"])
                fields = hidden(login.text)
                signed = await browser.post(
                    "/oauth/login",
                    data=fields | {"action": "signin", "email": "owner@example.com", "password": PASSWORD},
                )
                consent = await browser.get(signed.headers["location"])
                book = re.search(r'<option value="([^"]+)"', consent.text)
                assert book
                done = await browser.post(
                    "/oauth/login",
                    data=hidden(consent.text) | {"action": "approve", "book": book.group(1), "preset": "reader"},
                )
                query = parse_qs(urlsplit(done.headers["location"]).query)
                redirect.update({k: v[0] for k, v in query.items()})

            async def callback_handler() -> AuthorizationCodeResult:
                return AuthorizationCodeResult(
                    code=redirect["code"], state=redirect.get("state"), iss=redirect.get("iss")
                )

            auth = OAuthClientProvider(
                server_url=f"{BASE}/mcp",
                client_metadata=OAuthClientMetadata(
                    client_name="SDK 客户端",
                    redirect_uris=["http://127.0.0.1:3030/callback"],
                    grant_types=["authorization_code", "refresh_token"],
                    response_types=["code"],
                    token_endpoint_auth_method="none",
                ),
                storage=storage,
                redirect_handler=redirect_handler,
                callback_handler=callback_handler,
            )
            async with (
                app.state.mcp_manager.run(),
                httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE, auth=auth) as http,
                streamable_http_client(f"{BASE}/mcp", http_client=http) as streams,
                ClientSession(streams[0], streams[1]) as session,
            ):
                await session.initialize()
                result = await session.call_tool("get_context", {})
                return dict(result.structured_content or {}), storage

    envelope, storage = anyio.run(main)
    app.state.engine.dispose()
    assert envelope["ok"] is True and envelope["data"]["book"]["name"] == "主账套"
    assert storage.tokens is not None and storage.tokens.access_token.startswith("bk_pat_")


def test_revoking_the_api_token_ends_the_grant(oauth_client) -> None:  # type: ignore[no-untyped-def]
    from tests.api.conftest import login, write_headers

    client, world = oauth_client
    client_id = register(client)["client_id"]
    verifier, challenge = pkce()
    code = parse_qs(urlsplit(sign_in_and_approve(client, start(client, client_id, challenge))).query)["code"][0]
    issued = token(
        client,
        grant_type="authorization_code",
        code=code,
        redirect_uri=CALLBACK,
        client_id=client_id,
        code_verifier=verifier,
    ).json()
    csrf = login(client, world.admin_email)
    listed = client.get(f"/api/v1/books/{world.book_id}/tokens").json()["data"]
    [oauth_token] = [t for t in listed if t["name"].startswith("OAuth · Claude")]
    assert oauth_token["mcp_enabled"] and oauth_token["preset"] == "bookkeeper"
    revoked = client.post(
        f"/api/v1/books/{world.book_id}/tokens/{oauth_token['id']}:revoke", headers=write_headers(csrf)
    )
    assert revoked.status_code == 200, revoked.text
    assert mcp_status(client, issued["access_token"]) == 401
    refresh = token(client, grant_type="refresh_token", refresh_token=issued["refresh_token"], client_id=client_id)
    assert refresh.status_code == 400  # the grant ended with the token
