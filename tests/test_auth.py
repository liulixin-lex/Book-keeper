from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.models import Workspace


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    settings = Settings(
        app_env="test",
        app_secret_key="test-secret-that-is-not-used-outside-tests",
        database_url="sqlite://",
        session_cookie_secure=False,
        openai_api_key=None,
        _env_file=None,
    )
    with testing_session() as session:
        session.add(
            Workspace(
                id="00000000-0000-0000-0000-000000000001",
                name="Seeded Ledger",
                base_currency="CNY",
            )
        )
        session.commit()

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)
    engine.dispose()


def bootstrap(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "workspace_name": "Test Ledger",
            "email": "ADMIN@example.com",
            "display_name": "Admin",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("ledger_csrf")
    assert token
    return {"X-CSRF-Token": token}


def test_bootstrap_is_single_use_and_session_can_read_me(client: TestClient) -> None:
    assert client.get("/api/v1/auth/status").json() == {"initialized": False}
    auth = bootstrap(client)
    assert auth["user"]["email"] == "admin@example.com"
    assert auth["user"]["role"] == "admin"
    assert auth["user"]["workspace_id"] == "00000000-0000-0000-0000-000000000001"
    assert auth["user"]["username"] == "Admin"
    assert client.get("/api/v1/auth/status").json() == {"initialized": True}

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == auth["user"]["id"]

    duplicate = client.post(
        "/api/v1/auth/bootstrap",
        json={
            "workspace_name": "Other",
            "email": "other@example.com",
            "display_name": "Other",
            "password": "another secure password",
        },
    )
    assert duplicate.status_code == 409


def test_login_logout_and_csrf(client: TestClient) -> None:
    bootstrap(client)

    without_csrf = client.post("/api/v1/auth/logout")
    assert without_csrf.status_code == 403

    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong password"},
    )
    assert bad_login.status_code == 401

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "admin"

    username_login = client.post(
        "/api/v1/auth/login",
        json={
            "identifier": "admin",
            "password": "correct horse battery staple",
        },
    )
    assert username_login.status_code == 200


def test_token_registration_is_not_email_bound_and_is_single_use(
    client: TestClient,
) -> None:
    bootstrap(client)
    invitation = client.post(
        "/api/v1/users/invitations",
        headers=csrf_headers(client),
        json={"role": "bookkeeper"},
    )
    assert invitation.status_code == 201, invitation.text
    token = invitation.json()["token"]
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "token": token,
            "username": "member-one",
            "email": "member@example.com",
            "password": "member secure password",
        },
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["user"]["username"] == "member-one"

    reused = client.post(
        "/api/v1/auth/register",
        json={
            "token": token,
            "username": "member-two",
            "email": "other@example.com",
            "password": "another secure password",
        },
    )
    assert reused.status_code == 400


def test_profile_username_email_and_password_updates(client: TestClient) -> None:
    bootstrap(client)
    renamed = client.patch(
        "/api/v1/auth/profile",
        headers=csrf_headers(client),
        json={"username": "ledger-admin"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["username"] == "ledger-admin"

    wrong_password = client.patch(
        "/api/v1/auth/profile",
        headers=csrf_headers(client),
        json={"email": "new-admin@example.com", "current_password": "wrong"},
    )
    assert wrong_password.status_code == 400

    changed = client.patch(
        "/api/v1/auth/profile",
        headers=csrf_headers(client),
        json={
            "email": "new-admin@example.com",
            "current_password": "correct horse battery staple",
            "new_password": "updated secure password",
        },
    )
    assert changed.status_code == 200, changed.text
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "ledger-admin", "password": "updated secure password"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "new-admin@example.com"


def test_admin_invites_bookkeeper_and_permissions_are_enforced(client: TestClient) -> None:
    bootstrap(client)
    missing_csrf = client.post(
        "/api/v1/users/invitations",
        json={"email": "books@example.com", "role": "bookkeeper"},
    )
    assert missing_csrf.status_code == 403

    invitation = client.post(
        "/api/v1/users/invitations",
        headers=csrf_headers(client),
        json={"email": "books@example.com", "role": "bookkeeper"},
    )
    assert invitation.status_code == 201, invitation.text
    invitation_token = invitation.json()["token"]

    # Accepting the invitation replaces the current client's admin session.
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "token": invitation_token,
            "display_name": "Bookkeeper",
            "password": "bookkeeper secure password",
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["user"]["role"] == "bookkeeper"
    assert client.get("/api/v1/users").status_code == 403
    assert client.get("/api/v1/users/invitations").status_code == 403


def test_admin_role_cannot_be_granted_directly_by_invitation(client: TestClient) -> None:
    bootstrap(client)
    response = client.post(
        "/api/v1/users/invitations",
        headers=csrf_headers(client),
        json={"email": "second-admin@example.com", "role": "admin"},
    )
    assert response.status_code == 422
    assert "用户权限审批" in response.json()["detail"]


def test_last_admin_cannot_be_demoted(client: TestClient) -> None:
    auth = bootstrap(client)
    response = client.patch(
        f"/api/v1/users/{auth['user']['id']}",
        headers=csrf_headers(client),
        json={"role": "viewer"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "必须保留至少一名有效管理员"


def test_admin_can_edit_and_delete_non_admin_account(client: TestClient) -> None:
    bootstrap(client)
    invitation = client.post(
        "/api/v1/users/invitations",
        headers=csrf_headers(client),
        json={"role": "bookkeeper"},
    )
    token = invitation.json()["token"]
    registered = client.post(
        "/api/v1/auth/register",
        json={
            "token": token,
            "username": "member-one",
            "email": "member@example.com",
            "password": "member secure password",
        },
    )
    member_id = registered.json()["user"]["id"]

    admin_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "admin", "password": "correct horse battery staple"},
    )
    assert admin_login.status_code == 200
    updated = client.patch(
        f"/api/v1/users/{member_id}",
        headers=csrf_headers(client),
        json={"username": "member-renamed", "email": "renamed@example.com"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["username"] == "member-renamed"
    assert updated.json()["email"] == "renamed@example.com"

    deleted = client.delete(
        f"/api/v1/users/{member_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204, deleted.text
    assert all(item["id"] != member_id for item in client.get("/api/v1/users").json())
    rejected_login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "renamed@example.com", "password": "member secure password"},
    )
    assert rejected_login.status_code == 401


def test_admin_can_delete_invitation_and_audit_is_paginated(client: TestClient) -> None:
    bootstrap(client)
    invitation = client.post(
        "/api/v1/users/invitations",
        headers=csrf_headers(client),
        json={"role": "viewer"},
    )
    invitation_id = invitation.json()["id"]
    token = invitation.json()["token"]

    deleted = client.delete(
        f"/api/v1/users/invitations/{invitation_id}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/v1/users/invitations").json() == []
    rejected_registration = client.post(
        "/api/v1/auth/register",
        json={
            "token": token,
            "username": "late-member",
            "email": "late@example.com",
            "password": "member secure password",
        },
    )
    assert rejected_registration.status_code == 400

    first_page = client.get("/api/v1/audit?limit=1&offset=0")
    second_page = client.get("/api/v1/audit?limit=1&offset=1")
    assert first_page.status_code == 200
    assert first_page.json()["limit"] == 1
    assert first_page.json()["offset"] == 0
    assert first_page.json()["total"] >= 3
    assert len(first_page.json()["items"]) == 1
    assert second_page.json()["offset"] == 1
    assert len(second_page.json()["items"]) == 1
    assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]
