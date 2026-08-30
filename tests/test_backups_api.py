from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.backups import router
from app.config import Settings, get_settings
from app.db import Base, get_db
from app.dependencies import require_admin, require_csrf
from app.enums import UserRole
from app.models import BackupSettings, User, Workspace


@pytest.fixture
def backup_api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        session.add(Workspace(id="workspace", name="Ledger", base_currency="CNY"))
        session.commit()
        admin = User(
            id="admin",
            workspace_id="workspace",
            username="admin",
            email="admin@example.com",
            display_name="Admin",
            password_hash="not-used",
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(admin)
        session.commit()

    settings = Settings(
        app_env="test",
        app_secret_key="api-backup-secret",
        database_url="sqlite://",
        _env_file=None,
    )

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    def override_admin() -> User:
        with factory() as session:
            admin = session.get(User, "admin")
            assert admin is not None
            session.expunge(admin)
            return admin

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[require_admin] = override_admin
    app.dependency_overrides[require_csrf] = lambda: None
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def test_storage_secret_is_encrypted_and_never_returned(
    backup_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = backup_api
    response = client.put(
        "/api/v1/backups/storage",
        json={
            "storage_type": "r2",
            "endpoint_url": "https://account.r2.cloudflarestorage.com",
            "region": "auto",
            "bucket": "ledger-backups",
            "access_key_id": "access-key",
            "secret_access_key": "top-secret-value",
            "prefix": "backups",
            "force_path_style": False,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["secret_configured"] is True
    assert "secret_access_key" not in response.json()

    with factory() as session:
        configuration = session.get(BackupSettings, "default")
        assert configuration is not None
        assert configuration.encrypted_secret_access_key is not None
        assert "top-secret-value" not in configuration.encrypted_secret_access_key

    read_response = client.get("/api/v1/backups/storage")
    assert read_response.status_code == 200
    assert "secret_access_key" not in read_response.json()


def test_schedule_rejects_invalid_cron(
    backup_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _factory = backup_api
    response = client.put(
        "/api/v1/backups/schedule",
        json={
            "enabled": False,
            "cron_expression": "not a cron",
            "retain_days": 14,
            "retain_count": 10,
        },
    )
    assert response.status_code == 422
    assert "Cron" in response.json()["detail"]
