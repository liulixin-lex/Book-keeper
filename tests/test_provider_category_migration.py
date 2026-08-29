from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(database: Path, revision: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _create_fixture(database: Path, *, with_expense_category: bool = True) -> None:
    result = _run_alembic(database, "0009_repair_cash_metadata")
    assert result.returncode == 0, result.stdout + result.stderr
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO workspaces (id, name, base_currency) VALUES ('workspace', 'test', 'CNY')"
        )
        if with_expense_category:
            connection.execute(
                """
                INSERT INTO accounts (
                  id, workspace_id, code, name, account_type, is_active
                ) VALUES ('expense-account', 'workspace', '5602', '管理费用', 'expense', 1)
                """
            )
            connection.executemany(
                """
                INSERT INTO categories (
                  id, workspace_id, account_id, name, kind, is_active
                ) VALUES (?, 'workspace', 'expense-account', ?, 'expense', 1)
                """,
                [("cloud", "云服务"), ("other", "其他支出")],
            )
        connection.executemany(
            """
            INSERT INTO counterparties (
              id, workspace_id, name, roles_json, metadata_json, is_active
            ) VALUES (?, 'workspace', ?, ?, '{}', 1)
            """,
            [
                ("provider-used", "云服务商", '["customer"]'),
                ("provider-unused", "未分类服务商", '["customer", "supplier"]'),
            ],
        )
        if with_expense_category:
            for index, category_id in enumerate(("cloud", "cloud", "other")):
                connection.execute(
                    """
                    INSERT INTO business_records (
                      id, workspace_id, record_type, status, accounting_date,
                      date_precision, category_id, counterparty_id, description,
                      source_locator_json, metadata_json, version
                    ) VALUES (?, 'workspace', 'expense', 'draft', ?, 'day', ?,
                              'provider-used', ?, '{}', '{}', 1)
                    """,
                    (
                        f"record-{index}",
                        f"2026-08-{20 + index:02d}",
                        category_id,
                        f"Expense {index}",
                    ),
                )
        connection.commit()


def _assert_normalized(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(
            """
            SELECT provider.id, provider.roles_json, category.name
            FROM counterparties provider
            JOIN categories category ON category.id = provider.expense_category_id
            ORDER BY provider.id
            """
        ).fetchall()
        assert rows == [
            ("provider-unused", '["supplier"]', "其他支出"),
            ("provider-used", '["supplier"]', "云服务"),
        ]
        assert connection.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE action = 'migration.provider.normalize'
            """
        ).fetchone() == (2,)
        foreign_keys = connection.execute("PRAGMA foreign_key_list(counterparties)").fetchall()
        assert any(
            row[2] == "categories" and row[3] == "expense_category_id" for row in foreign_keys
        )


def test_provider_category_migration_is_linked_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "provider-category.db"
    _create_fixture(database)

    first = _run_alembic(database, "head")
    assert first.returncode == 0, first.stdout + first.stderr
    _assert_normalized(database)

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE alembic_version SET version_num = '0009_repair_cash_metadata'")
        connection.commit()
    second = _run_alembic(database, "head")
    assert second.returncode == 0, second.stdout + second.stderr
    _assert_normalized(database)


def test_provider_category_migration_rolls_back_without_expense_categories(
    tmp_path: Path,
) -> None:
    database = tmp_path / "provider-category-rollback.db"
    _create_fixture(database, with_expense_category=False)

    result = _run_alembic(database, "head")
    assert result.returncode != 0
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0009_repair_cash_metadata",
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(counterparties)")}
        assert "expense_category_id" not in columns
        assert connection.execute(
            """
            SELECT COUNT(*) FROM audit_events
            WHERE action = 'migration.provider.normalize'
            """
        ).fetchone() == (0,)
