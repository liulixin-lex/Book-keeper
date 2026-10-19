from sqlalchemy import select

from bookkeeper.db.models import ApiToken, IdempotencyKey
from tests.api.conftest import bearer, create_token, login, write_headers


def test_superadmin_creates_user_and_book(client, world) -> None:
    csrf = login(client, world.admin_email)
    user = client.post(
        "/api/v1/users",
        json={"email": "Bob@Example.com", "display_name": "Bob", "password": "bob long password"},
        headers=write_headers(csrf),
    )
    assert user.status_code == 201, user.text
    assert user.json()["data"]["email"] == "bob@example.com"
    book = client.post(
        "/api/v1/books",
        json={"name": "第二账套", "owner_user_id": user.json()["data"]["id"]},
        headers=write_headers(csrf),
    )
    assert book.status_code == 201, book.text
    assert book.json()["data"]["base_commodity"] == "CNY"
    assert book.json()["data"]["timezone"] == "Asia/Shanghai"


def test_book_update_requires_matching_version(client, world) -> None:
    csrf = login(client, world.admin_email)
    url = f"/api/v1/books/{world.book_id}"
    stale = client.patch(url, json={"expected_version": 99, "name": "新名称"}, headers=write_headers(csrf))
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"
    assert stale.json()["current_version"] == 1
    ok = client.patch(url, json={"expected_version": 1, "name": "新名称"}, headers=write_headers(csrf))
    assert ok.status_code == 200
    assert ok.json()["data"]["version"] == 2


def test_token_plaintext_once_hash_stored(client, world, app) -> None:
    csrf = login(client, world.admin_email)
    data = create_token(client, world.book_id, csrf, preset="bookkeeper", mcp_enabled=True)
    assert data["token"].startswith("bk_pat_")
    assert data["scopes"] == ["import:write", "ledger:read", "ledger:write", "reference:write"]
    with app.state.sessionmaker() as session:
        row = session.get(ApiToken, data["id"])
        assert row.token_hash != data["token"]
        assert len(row.token_hash) == 64
        cached = session.execute(select(IdempotencyKey.response_body)).scalars().all()
    assert all(data["token"] not in str(body) for body in cached)
    listed = client.get(f"/api/v1/books/{world.book_id}/tokens").json()["data"]
    assert all("token" not in t for t in listed)


def test_reader_token_can_read_but_not_write(client, world) -> None:
    csrf = login(client, world.admin_email)
    token = create_token(client, world.book_id, csrf)["token"]
    client.cookies.clear()
    assert client.get(f"/api/v1/books/{world.book_id}", headers=bearer(token)).status_code == 200
    denied = client.post(
        f"/api/v1/books/{world.book_id}/tokens",
        json={"name": "y"},
        headers=bearer(token, **{"Idempotency-Key": "a1"}),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN_SCOPE"


def test_token_bound_to_its_book(client, world) -> None:
    csrf = login(client, world.admin_email)
    token = create_token(client, world.book_id, csrf)["token"]
    other = client.post("/api/v1/books", json={"name": "其他"}, headers=write_headers(csrf)).json()["data"]["id"]
    client.cookies.clear()
    response = client.get(f"/api/v1/books/{other}", headers=bearer(token))
    assert response.status_code == 403


def test_revoked_and_rotated_tokens(client, world) -> None:
    csrf = login(client, world.admin_email)
    first = create_token(client, world.book_id, csrf)
    rotated = client.post(
        f"/api/v1/books/{world.book_id}/tokens/{first['id']}:rotate", headers=write_headers(csrf)
    ).json()["data"]
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers=bearer(first["token"])).json()["code"] == "TOKEN_REVOKED"
    assert client.get("/api/v1/auth/me", headers=bearer(rotated["token"])).status_code == 200
    csrf = login(client, world.admin_email)
    client.post(f"/api/v1/books/{world.book_id}/tokens/{rotated['id']}:revoke", headers=write_headers(csrf))
    client.cookies.clear()
    assert client.get("/api/v1/auth/me", headers=bearer(rotated["token"])).status_code == 401


def test_custom_scopes_cannot_exceed_role(client, world, app) -> None:
    from bookkeeper.domain.scopes import ROLE_CAPS, Role
    from bookkeeper.services import books, identity
    from bookkeeper.services.context import Actor, RequestContext

    with app.state.sessionmaker() as session, session.begin():
        ctx = RequestContext(actor=Actor.system(), channel="cli")
        viewer = identity.create_user(
            session, ctx, email="v@example.com", display_name="V", password="viewer long password"
        )
        owner_ctx = RequestContext(
            actor=Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER]),
            channel="cli",
            book_id=world.book_id,
        )
        books.set_member(session, owner_ctx, viewer.id, Role.VIEWER)
    csrf = login(client, "v@example.com", "viewer long password")
    response = client.post(
        f"/api/v1/books/{world.book_id}/tokens",
        json={"name": "x", "preset": "custom", "scopes": ["ledger:read", "ledger:write"]},
        headers=write_headers(csrf),
    )
    assert response.status_code == 403
    assert "ledger:write" in response.json()["detail"]
    retired = client.post(
        f"/api/v1/books/{world.book_id}/tokens",
        json={"name": "x", "preset": "custom", "scopes": ["ledger:read", "ledger:post"]},
        headers=write_headers(csrf),
    )
    assert retired.status_code == 422 and "unknown scope" in retired.json()["detail"]


def test_last_owner_cannot_be_removed(client, world) -> None:
    csrf = login(client, world.admin_email)
    response = client.delete(f"/api/v1/books/{world.book_id}/members/{world.admin_id}", headers=write_headers(csrf))
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_STATE"


def test_non_member_sees_not_found(client, world, app) -> None:
    from bookkeeper.services import identity
    from bookkeeper.services.context import Actor, RequestContext

    with app.state.sessionmaker() as session, session.begin():
        identity.create_user(
            session,
            RequestContext(actor=Actor.system(), channel="cli"),
            email="out@example.com",
            display_name="O",
            password="outsider long pass",
        )
    login(client, "out@example.com", "outsider long pass")
    assert client.get(f"/api/v1/books/{world.book_id}").status_code == 404
