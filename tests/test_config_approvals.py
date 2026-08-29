from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.crypto import decrypt_api_key
from app.api.ai import router as ai_router
from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.users import router as users_router
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.enums import AIMode, AIStatus, ReasoningEffort, UserRole
from app.models import AIProvider, AIRun, User, Workspace


@pytest.fixture
def approval_client() -> Generator[tuple[TestClient, sessionmaker[Session], Settings], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    settings = Settings(
        app_env="test",
        app_secret_key="configuration-approval-test-secret",
        database_url="sqlite://",
        session_cookie_secure=False,
        _env_file=None,
    )
    with factory() as db:
        db.add(
            Workspace(
                id="00000000-0000-0000-0000-000000000001",
                name="Approval Ledger",
                base_currency="CNY",
            )
        )
        db.commit()

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(catalog_router, prefix="/api/v1")
    app.include_router(ai_router, prefix="/api/v1")
    app.include_router(approvals_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        bootstrapped = client.post(
            "/api/v1/auth/bootstrap",
            json={
                "workspace_name": "Approval Ledger",
                "email": "admin@example.com",
                "display_name": "Admin",
                "password": "correct horse battery staple",
            },
        )
        assert bootstrapped.status_code == 201, bootstrapped.text
        yield client, factory, settings
    Base.metadata.drop_all(engine)
    engine.dispose()


def csrf_headers(client: TestClient) -> dict[str, str]:
    csrf = client.cookies.get("ledger_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


def approve(client: TestClient, approval: dict[str, Any]) -> None:
    response = client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        headers=csrf_headers(client),
        json={"reason": "reviewed"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


def create_approved_provider(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    requested = client.post(
        "/api/v1/ai/providers",
        headers=csrf_headers(client),
        json={**payload, "probe_before_save": False},
    )
    assert requested.status_code == 202, requested.text
    approval = requested.json()
    assert approval["kind"] == "config.ai_provider.create"
    assert approval["status"] == "pending"
    assert all(
        provider["name"] != payload["name"]
        for provider in client.get("/api/v1/ai/providers").json()
    )
    approve(client, approval)
    return next(
        provider
        for provider in client.get("/api/v1/ai/providers").json()
        if provider["name"] == payload["name"]
    )


def test_provider_update_waits_for_approval_and_never_exposes_key(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, factory, settings = approval_client
    headers = csrf_headers(client)
    created = create_approved_provider(
        client,
        {
            "name": "Initial provider",
            "protocol": "responses",
            "base_url": "https://initial.example/v1",
            "model": "initial-model",
        },
    )
    provider_id = created["id"]

    requested = client.patch(
        f"/api/v1/ai/providers/{provider_id}",
        headers=headers,
        json={
            "base_url": "https://updated.example/v1/",
            "model": "updated-model",
            "api_key": "provider-secret-for-test",
            "reasoning_effort": "high",
            "probe_before_save": False,
        },
    )
    assert requested.status_code == 202, requested.text
    approval = requested.json()
    assert approval["kind"] == "config.ai_provider.update"
    assert approval["status"] == "pending"
    assert "provider-secret-for-test" not in requested.text
    assert approval["payload"]["changes"]["encrypted_api_key"] == "[redacted]"

    unchanged = client.get(f"/api/v1/ai/providers/{provider_id}").json()
    assert unchanged["base_url"] == "https://initial.example/v1"
    assert unchanged["model"] == "initial-model"
    assert unchanged["has_api_key"] is False

    stale_key_request = client.patch(
        f"/api/v1/ai/providers/{provider_id}",
        headers=headers,
        json={"api_key": "stale-provider-secret", "probe_before_save": False},
    )
    assert stale_key_request.status_code == 202
    approve(client, approval)
    stale_result = client.post(
        f"/api/v1/approvals/{stale_key_request.json()['id']}/approve",
        headers=headers,
        json={"reason": "stale key change"},
    )
    assert stale_result.status_code == 409
    changed = client.get(f"/api/v1/ai/providers/{provider_id}").json()
    assert changed["base_url"] == "https://updated.example/v1"
    assert changed["model"] == "updated-model"
    assert changed["reasoning_effort"] == "high"
    assert changed["has_api_key"] is True
    assert changed["version"] == 2
    with factory() as db:
        provider = db.get(AIProvider, provider_id)
        assert provider is not None
        assert provider.encrypted_api_key is not None
        assert (
            decrypt_api_key(provider.encrypted_api_key, settings.app_secret_key)
            == "provider-secret-for-test"
        )


def test_provider_delete_rejection_and_approval_are_non_destructive_until_approved(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, _factory, _settings = approval_client
    headers = csrf_headers(client)
    created = create_approved_provider(
        client,
        {
            "name": "Disposable provider",
            "protocol": "responses",
            "base_url": "https://delete.example/v1",
            "model": "delete-model",
        },
    )
    provider_id = created["id"]

    first = client.delete(f"/api/v1/ai/providers/{provider_id}", headers=headers)
    assert first.status_code == 202, first.text
    assert first.json()["kind"] == "config.ai_provider.delete"
    assert client.get(f"/api/v1/ai/providers/{provider_id}").status_code == 200
    rejected = client.post(
        f"/api/v1/approvals/{first.json()['id']}/reject",
        headers=headers,
        json={"reason": "keep it"},
    )
    assert rejected.status_code == 200
    assert client.get(f"/api/v1/ai/providers/{provider_id}").status_code == 200

    second = client.delete(f"/api/v1/ai/providers/{provider_id}", headers=headers)
    assert second.status_code == 202
    approve(client, second.json())
    assert client.get(f"/api/v1/ai/providers/{provider_id}").status_code == 404


def test_provider_with_ai_runs_cannot_be_deleted_by_approval(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, factory, _settings = approval_client
    headers = csrf_headers(client)
    created = create_approved_provider(
        client,
        {
            "name": "Used provider",
            "protocol": "responses",
            "base_url": "https://used.example/v1",
            "model": "used-model",
        },
    )
    provider_id = created["id"]
    with factory() as db:
        provider = db.get(AIProvider, provider_id)
        assert provider is not None
        db.add(
            AIRun(
                workspace_id=provider.workspace_id,
                provider_id=provider.id,
                mode=AIMode.CHAT,
                status=AIStatus.COMPLETED,
                model=provider.model,
                reasoning_effort=ReasoningEffort.MEDIUM,
            )
        )
        db.commit()

    requested = client.delete(f"/api/v1/ai/providers/{provider_id}", headers=headers)
    result = client.post(
        f"/api/v1/approvals/{requested.json()['id']}/approve",
        headers=headers,
        json={"reason": "delete used provider"},
    )
    assert result.status_code == 409
    assert "已有运行记录" in result.json()["detail"]
    assert client.get(f"/api/v1/ai/providers/{provider_id}").status_code == 200


def test_ai_settings_rejection_does_not_apply_and_stale_approval_cannot_overwrite(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, _factory, _settings = approval_client
    headers = csrf_headers(client)
    initial = client.get("/api/v1/ai/settings").json()
    rejected_request = client.patch(
        "/api/v1/ai/settings",
        headers=headers,
        json={"web_access_enabled": True, "version": initial["version"]},
    )
    assert rejected_request.status_code == 202
    rejected = client.post(
        f"/api/v1/approvals/{rejected_request.json()['id']}/reject",
        headers=headers,
        json={"reason": "not allowed"},
    )
    assert rejected.status_code == 200
    assert client.get("/api/v1/ai/settings").json() == initial

    first = client.patch(
        "/api/v1/ai/settings",
        headers=headers,
        json={"agents_md": "First approved rules", "version": initial["version"]},
    ).json()
    stale = client.patch(
        "/api/v1/ai/settings",
        headers=headers,
        json={"agents_md": "Stale rules", "version": initial["version"]},
    ).json()
    approve(client, first)
    stale_result = client.post(
        f"/api/v1/approvals/{stale['id']}/approve",
        headers=headers,
        json={"reason": "too late"},
    )
    assert stale_result.status_code == 409
    current = client.get("/api/v1/ai/settings").json()
    assert current["agents_md"] == "First approved rules"
    assert current["version"] == initial["version"] + 1


def test_manual_fx_rate_can_be_created_directly(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, _factory, _settings = approval_client
    requested = client.post(
        "/api/v1/catalog/fx-rates",
        headers=csrf_headers(client),
        json={
            "base_currency": "usd",
            "quote_currency": "cny",
            "rate": "7.123456789012",
            "effective_at": "2026-08-28T00:00:00Z",
            "source": "manual review",
            "rate_type": "manual",
        },
    )
    assert requested.status_code == 201, requested.text
    rates = client.get("/api/v1/catalog/fx-rates").json()
    assert len(rates) == 1
    assert rates[0]["base_currency"] == "USD"
    assert rates[0]["quote_currency"] == "CNY"
    assert rates[0]["rate"] == "7.123456789012"


def test_user_role_and_active_status_wait_for_approval(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, factory, _settings = approval_client
    with factory() as db:
        workspace = db.scalar(select(Workspace))
        assert workspace is not None
        target = User(
            workspace_id=workspace.id,
            username="Target",
            email="target@example.com",
            display_name="Target",
            password_hash="unused",
            role=UserRole.VIEWER,
            is_active=True,
        )
        db.add(target)
        db.commit()
        target_id = target.id

    requested = client.patch(
        f"/api/v1/users/{target_id}",
        headers=csrf_headers(client),
        json={"display_name": "Reviewed Target", "role": "bookkeeper", "is_active": False},
    )
    assert requested.status_code == 202, requested.text
    approval = requested.json()
    assert approval["kind"] == "config.user_permissions.update"
    before = {item["id"]: item for item in client.get("/api/v1/users").json()}[target_id]
    assert before["display_name"] == "Target"
    assert before["role"] == "viewer"
    assert before["is_active"] is True

    approve(client, approval)
    after = {item["id"]: item for item in client.get("/api/v1/users").json()}[target_id]
    assert after["display_name"] == "Reviewed Target"
    assert after["role"] == "bookkeeper"
    assert after["is_active"] is False


def test_display_name_only_remains_an_immediate_low_risk_update(
    approval_client: tuple[TestClient, sessionmaker[Session], Settings],
) -> None:
    client, _factory, _settings = approval_client
    me = client.get("/api/v1/auth/me").json()
    changed = client.patch(
        f"/api/v1/users/{me['id']}",
        headers=csrf_headers(client),
        json={"display_name": "Renamed Admin"},
    )
    assert changed.status_code == 200
    assert changed.json()["display_name"] == "Renamed Admin"
