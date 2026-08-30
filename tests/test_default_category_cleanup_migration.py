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


def test_cleanup_removes_only_unused_automatic_categories(tmp_path: Path) -> None:
    database = tmp_path / "default-category-cleanup.db"
    prepared = _run_alembic(database, "0014_backup_storage")
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr

    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO workspaces (id, name, base_currency) VALUES ('workspace', 'test', 'CNY')"
        )
        connection.executemany(
            """
            INSERT INTO accounts (id, workspace_id, code, name, account_type, is_active)
            VALUES (?, 'workspace', ?, ?, ?, 1)
            """,
            [
                ("income-account", "5001", "主营业务收入", "revenue"),
                ("cost-account", "5401", "主营业务成本", "expense"),
                ("expense-account", "5602", "管理费用", "expense"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO categories (
              id, workspace_id, parent_id, account_id, name, kind, is_active
            ) VALUES (?, 'workspace', ?, ?, ?, ?, 1)
            """,
            [
                ("automatic", None, "cost-account", "上游采购", "expense"),
                ("manual", None, "expense-account", "软件订阅", "expense"),
                ("referenced", None, "income-account", "主营业务收入", "income"),
                ("child", "referenced", "income-account", "自定义子类别", "income"),
                ("custom", None, "expense-account", "自定义支出", "expense"),
            ],
        )
        connection.execute(
            """
            INSERT INTO audit_events (
              id, workspace_id, actor_type, action, entity_type, entity_id
            ) VALUES (
              'audit-manual', 'workspace', 'user', 'category.create', 'category', 'manual'
            )
            """
        )
        connection.commit()

    upgraded = _run_alembic(database, "head")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    with closing(sqlite3.connect(database)) as connection:
        names = {
            row[0] for row in connection.execute("SELECT name FROM categories ORDER BY name")
        }
        assert names == {"主营业务收入", "软件订阅", "自定义子类别", "自定义支出"}
