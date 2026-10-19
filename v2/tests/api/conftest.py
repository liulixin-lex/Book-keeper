"""API fixtures: app, client, a superadmin with a book, helpers."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from bookkeeper.config import Settings
from bookkeeper.main import create_app
from bookkeeper.services import books, identity
from bookkeeper.services.context import Actor, RequestContext

PASSWORD = "correct horse battery"
_keys = itertools.count()


def key() -> str:
    return f"test-key-{next(_keys)}"


@pytest.fixture
def settings(database_url: str, data_dir: Path) -> Settings:
    return Settings(
        database_url=database_url,
        data_dir=data_dir,
        public_url="http://testserver",
        log_json=False,
        login_max_failures=3,
        mcp_write_enabled=True,
    )


@pytest.fixture
def app(settings: Settings):  # type: ignore[no-untyped-def]
    application = create_app(settings, configure_logs=False)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    with TestClient(app) as test_client:
        yield test_client


@dataclass
class World:
    admin_id: str
    admin_email: str
    book_id: str


@pytest.fixture
def world(app) -> World:  # type: ignore[no-untyped-def]
    factory: sessionmaker = app.state.sessionmaker
    ctx = RequestContext(actor=Actor.system(), channel="cli")
    with factory() as session, session.begin():
        admin = identity.create_user(
            session,
            ctx,
            email="admin@example.com",
            display_name="管理员",
            password=PASSWORD,
            is_superadmin=True,
        )
        book = books.create_book(session, ctx, name="测试账套", owner_user_id=admin.id)
        return World(admin.id, admin.email, book.id)


def login(client: TestClient, email: str, password: str = PASSWORD) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf: str = response.json()["data"]["csrf_token"]
    return csrf


def write_headers(csrf: str | None = None, **extra: str) -> dict[str, str]:
    headers = {"Idempotency-Key": key()}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    headers.update(extra)
    return headers


def create_token(client: TestClient, book_id: str, csrf: str, **body: Any) -> dict[str, Any]:
    payload = {"name": "t"} | body
    response = client.post(f"/api/v1/books/{book_id}/tokens", json=payload, headers=write_headers(csrf))
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


def bearer(token: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} | extra
