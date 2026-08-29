from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest


def test_static_migration_installs_immutable_balanced_ledger_guards(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    with closing(sqlite3.connect(database)) as connection:
        table_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "import_batches" not in table_names
        assert "import_rows" not in table_names
        assert "classification_rules" not in table_names
        assert "settlements" not in table_names
        assert "settlement_items" not in table_names
        assert "reconciliation_sessions" not in table_names
        assert "reconciliation_items" not in table_names
        assert "business_records" in table_names
        assert "source_documents" in table_names

        trigger_names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")
        }
        assert "journal_entry_insert_posted_guard" in trigger_names
        assert "journal_entry_post_guard" in trigger_names
        assert "posted_journal_immutable" in trigger_names
        assert "posted_line_no_update" in trigger_names
        assert "posted_journal_no_delete" not in trigger_names
        assert "posted_line_no_delete" not in trigger_names

        connection.execute(
            "INSERT INTO workspaces (id, name, base_currency) VALUES ('w', 'test', 'CNY')"
        )
        connection.execute(
            """
            INSERT INTO accounts
              (id, workspace_id, code, name, account_type, is_active)
            VALUES ('a', 'w', '1000', 'cash', 'asset', 1)
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="created as draft"):
            connection.execute(
                """
                INSERT INTO journal_entries
                  (id, workspace_id, entry_date, status, memo)
                VALUES ('j-direct', 'w', '2026-08-28', 'posted', 'invalid')
                """
            )
        connection.execute(
            """
            INSERT INTO journal_entries
              (id, workspace_id, entry_date, status, memo)
            VALUES ('j', 'w', '2026-08-28', 'draft', 'test')
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="at least two lines"):
            connection.execute("UPDATE journal_entries SET status = 'posted' WHERE id = 'j'")
        connection.execute(
            """
            INSERT INTO journal_lines
              (id, entry_id, account_id, debit_cny_e8, credit_cny_e8)
            VALUES ('l1', 'j', 'a', 100, 0), ('l2', 'j', 'a', 0, 100)
            """
        )
        connection.execute("UPDATE journal_entries SET status = 'posted' WHERE id = 'j'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE journal_entries SET memo = 'changed' WHERE id = 'j'")

        connection.execute(
            """
            INSERT INTO journal_entries
              (id, workspace_id, entry_date, status, memo)
            VALUES ('j-draft', 'w', '2026-08-28', 'draft', 'draft source')
            """
        )
        connection.execute(
            """
            INSERT INTO journal_lines
              (id, entry_id, account_id, debit_cny_e8, credit_cny_e8)
            VALUES ('l-draft', 'j-draft', 'a', 25, 0)
            """
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE journal_lines SET entry_id = 'j' WHERE id = 'l-draft'")

        assert connection.execute(
            "SELECT entry_id FROM journal_lines WHERE id = 'l-draft'"
        ).fetchone() == ("j-draft",)
        debit, credit = connection.execute(
            """
            SELECT SUM(debit_cny_e8), SUM(credit_cny_e8)
            FROM journal_lines
            WHERE entry_id = 'j'
            """
        ).fetchone()
        assert debit == credit

        connection.execute("DELETE FROM journal_lines WHERE entry_id = 'j'")
        connection.execute("DELETE FROM journal_entries WHERE id = 'j'")
        assert connection.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE id = 'j'"
        ).fetchone() == (0,)
