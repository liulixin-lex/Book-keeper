"""Operator CLI against a real database: users, books, checks, password reset."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from bookkeeper import cli
from bookkeeper.config import get_settings
from bookkeeper.db.models import User
from bookkeeper.db.session import get_sessionmaker, reset_engine_cache
from bookkeeper.security import passwords


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, database_url: str, data_dir: Path, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)  # no stray .env
    monkeypatch.setenv("BK_DATABASE_URL", database_url)
    monkeypatch.setenv("BK_DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    reset_engine_cache()
    yield
    reset_engine_cache()
    get_settings.cache_clear()


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, list[dict]]:
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    return code, [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def test_operator_commands(env: None, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BK_NEW_PASSWORD", "first-password-123")
    code, [user] = run(capsys, "create-user", "--email", "Ops@Example.com", "--name", "运维", "--superadmin")
    assert code == 0 and user["email"] == "ops@example.com"
    code, [book] = run(capsys, "create-book", "--name", "主账套", "--owner-email", "ops@example.com")
    assert code == 0
    code, [token] = run(
        capsys, "create-token", "--book", book["id"], "--user-email", "ops@example.com", "--name", "ai", "--mcp"
    )
    assert code == 0 and token["token"] and token["mcp_enabled"]

    code, runs = run(capsys, "run-checks", "--codes", "trial_balance_zero,hash_chain")
    assert code == 0 and [r["status"] for r in runs] == ["passed"]
    assert {r["code"] for r in runs[0]["results"]} == {"trial_balance_zero", "hash_chain"}

    with get_sessionmaker()() as session, session.begin():
        locked = session.execute(select(User).where(User.email == "ops@example.com")).scalar_one()
        locked.failed_logins = 9
    monkeypatch.setenv("BK_NEW_PASSWORD", "second-password-456")
    code, _ = run(capsys, "reset-password", "--email", "OPS@example.com")
    assert code == 0
    with get_sessionmaker()() as session:
        user_row = session.execute(select(User).where(User.email == "ops@example.com")).scalar_one()
        assert passwords.verify_password(user_row.password_hash, "second-password-456")
        assert user_row.failed_logins == 0 and user_row.locked_until is None


def test_unknown_check_code(env: None, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BK_NEW_PASSWORD", "first-password-123")
    run(capsys, "create-user", "--email", "a@example.com", "--name", "A")
    run(capsys, "create-book", "--name", "B", "--owner-email", "a@example.com")
    assert cli.main(["run-checks", "--codes", "no_such_check"]) == 2
    assert "VALIDATION_FAILED" in capsys.readouterr().err


def test_worker_healthcheck(env: None) -> None:
    from bookkeeper.db.session import get_sessionmaker
    from bookkeeper.jobs.worker import Worker

    assert cli.main(["healthcheck", "--worker"]) == 1  # no heartbeat yet
    Worker(get_sessionmaker()).beat()
    assert cli.main(["healthcheck", "--worker"]) == 0
