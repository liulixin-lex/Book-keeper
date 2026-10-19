"""Shared fixtures: a migrated template database cloned per test."""

from __future__ import annotations

import itertools
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from bookkeeper.paths import ALEMBIC_INI
from tests import pg

TEMPLATE = "bk_template"
_counter = itertools.count()


@pytest.fixture(scope="session")
def pg_server() -> Iterator[pg.PgServer]:
    server = pg.start()
    admin = create_engine(server.admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEMPLATE}"))
        conn.execute(text(f"CREATE DATABASE {TEMPLATE}"))
    admin.dispose()
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = server.url_for(TEMPLATE)
    command.upgrade(config, "head")
    yield server
    server.stop()


@pytest.fixture
def database_url(pg_server: pg.PgServer) -> Iterator[str]:
    name = f"bk_test_{os.getpid()}_{next(_counter)}"
    admin = create_engine(pg_server.admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE}"))
    yield pg_server.url_for(name)
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    admin.dispose()


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    eng = create_engine(database_url)
    yield eng
    eng.dispose()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir()
    return path
