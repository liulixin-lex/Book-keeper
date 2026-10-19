from tests.api.conftest import PASSWORD, login, write_headers


def test_login_sets_cookie_and_me(client, world) -> None:
    csrf = login(client, world.admin_email)
    assert client.cookies.get("bk_session")
    me = client.get("/api/v1/auth/me").json()["data"]
    assert me["user"]["email"] == world.admin_email
    assert me["books"] == [{"id": world.book_id, "name": "测试账套", "role": "owner"}]
    assert me["csrf_token"] == csrf


def test_wrong_password_and_lockout(client, world) -> None:
    for _ in range(3):
        response = client.post("/api/v1/auth/login", json={"email": world.admin_email, "password": "wrong password x"})
        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHENTICATED"
    locked = client.post("/api/v1/auth/login", json={"email": world.admin_email, "password": PASSWORD})
    assert locked.status_code == 429
    assert locked.json()["code"] == "ACCOUNT_LOCKED"


def test_failed_login_is_audited_even_though_request_fails(client, world, app) -> None:
    from sqlalchemy import select

    from bookkeeper.db.models import AuditEvent

    client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever password"})
    with app.state.sessionmaker() as session:
        actions = session.execute(select(AuditEvent.action).where(AuditEvent.scope == "global")).scalars().all()
    assert "auth.login_failed" in actions


def test_unauthenticated_request(client) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_cookie_write_requires_csrf(client, world) -> None:
    csrf = login(client, world.admin_email)
    response = client.post(
        f"/api/v1/books/{world.book_id}/tokens",
        json={"name": "x"},
        headers={"Idempotency-Key": "k1"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    ok = client.post(f"/api/v1/books/{world.book_id}/tokens", json={"name": "x"}, headers=write_headers(csrf))
    assert ok.status_code == 201


def test_logout_revokes_session(client, world) -> None:
    csrf = login(client, world.admin_email)
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_change_password(client, world) -> None:
    csrf = login(client, world.admin_email)
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "another long password"},
        headers=write_headers(csrf),
    )
    assert response.status_code == 200
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": world.admin_email, "password": PASSWORD}).status_code == 401
    login(client, world.admin_email, "another long password")
