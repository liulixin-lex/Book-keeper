from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Workspace
from app.services.reports import overview

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


def _insert_record(
    connection: sqlite3.Connection,
    *,
    record_id: str,
    record_type: str,
    description: str,
    category_id: str,
    components: list[tuple[str, int]],
    lines: list[tuple[str, int, int]],
    metadata: str = "{}",
) -> None:
    entry_id = f"entry-{record_id}"
    connection.execute(
        """
        INSERT INTO business_records (
          id, workspace_id, record_type, status, accounting_date,
          date_precision, category_id, description, source_locator_json,
          metadata_json, version
        ) VALUES (?, 'workspace', ?, 'posted', '2026-06-30', 'day', ?, ?, '{}', ?, 1)
        """,
        (record_id, record_type, category_id, description, metadata),
    )
    connection.execute(
        """
        INSERT INTO journal_entries (
          id, workspace_id, record_id, entry_date, status, memo
        ) VALUES (?, 'workspace', ?, '2026-06-30', 'draft', ?)
        """,
        (entry_id, record_id, description),
    )
    for index, (role, amount) in enumerate(components):
        connection.execute(
            """
            INSERT INTO money_components (
              id, record_id, role, sequence, currency, amount_e8,
              amount_cny_e8, is_derived, raw_amount_text
            ) VALUES (?, ?, ?, 0, 'CNY', ?, ?, 0, ?)
            """,
            (
                f"component-{record_id}-{index}",
                record_id,
                role,
                amount,
                amount,
                str(amount),
            ),
        )
    for index, (account_id, debit, credit) in enumerate(lines):
        connection.execute(
            """
            INSERT INTO journal_lines (
              id, entry_id, account_id, debit_cny_e8, credit_cny_e8,
              original_currency, original_amount_e8, description
            ) VALUES (?, ?, ?, ?, ?, 'CNY', ?, ?)
            """,
            (
                f"line-{record_id}-{index}",
                entry_id,
                account_id,
                debit,
                credit,
                debit or credit,
                description,
            ),
        )
    connection.execute("UPDATE journal_entries SET status = 'posted' WHERE id = ?", (entry_id,))
    connection.execute(
        "UPDATE business_records SET posted_entry_id = ? WHERE id = ?",
        (entry_id, record_id),
    )


def _create_legacy_fixture(database: Path, *, include_system_funds: bool = True) -> None:
    result = _run_alembic(database, "0007_normalize_counterparty_roles")
    assert result.returncode == 0, result.stdout + result.stderr
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO workspaces (id, name, base_currency) VALUES ('workspace', 'test', 'CNY')"
        )
        accounts = [
            ("clearing", "1012", "其他货币资金", "asset", "clearing"),
            ("pending", "1221", "其他应收款", "asset", "pending_difference"),
            ("revenue", "5001", "主营业务收入", "revenue", "operating_revenue"),
            ("other-revenue", "5051", "其他业务收入", "revenue", "other_revenue"),
            ("expense", "5602", "管理费用", "expense", "administrative_expense"),
            ("fee", "5603", "财务费用", "expense", "processing_fee"),
        ]
        if include_system_funds:
            accounts.insert(0, ("cash", "1002", "银行存款", "asset", "system_funds"))
        connection.executemany(
            """
            INSERT INTO accounts (
              id, workspace_id, code, name, account_type, subtype, is_active
            ) VALUES (?, 'workspace', ?, ?, ?, ?, 1)
            """,
            accounts,
        )
        connection.executemany(
            """
            INSERT INTO categories (
              id, workspace_id, account_id, name, kind, is_active
            ) VALUES (?, 'workspace', ?, ?, ?, 1)
            """,
            [
                ("income-category", "revenue", "主营业务收入", "income"),
                ("expense-category", "expense", "云服务", "expense"),
            ],
        )
        _insert_record(
            connection,
            record_id="historical-income",
            record_type="income",
            description="Historical Stripe income",
            category_id="income-category",
            components=[("gross", 10_000_000_000), ("fee", 500_000_000), ("net", 9_500_000_000)],
            lines=[
                ("clearing", 9_500_000_000, 0),
                ("fee", 500_000_000, 0),
                ("revenue", 0, 10_000_000_000),
            ],
        )
        if include_system_funds:
            _insert_record(
                connection,
                record_id="legacy-topup",
                record_type="topup",
                description="Legacy topup",
                category_id="expense-category",
                components=[("cost", 4_700_000_000), ("cash", 4_700_000_000)],
                lines=[("expense", 4_700_000_000, 0), ("cash", 0, 4_700_000_000)],
            )
            _insert_record(
                connection,
                record_id="legacy-subscription",
                record_type="subscription",
                description="Legacy subscription",
                category_id="expense-category",
                components=[("cost", 2_000_000_000), ("cash", 2_000_000_000)],
                lines=[("expense", 2_000_000_000, 0), ("cash", 0, 2_000_000_000)],
            )
            _insert_record(
                connection,
                record_id="expense-refund",
                record_type="adjustment",
                description="TDSQL-C MySQL版",
                category_id="expense-category",
                components=[("cost", -4_345_000_000), ("cash", -4_345_000_000)],
                lines=[("cash", 4_345_000_000, 0), ("expense", 0, 4_345_000_000)],
                metadata='{"legacy_status":"退款"}',
            )
            _insert_record(
                connection,
                record_id="tdsql-difference",
                record_type="expense",
                description="TDSQL-C MySQL版",
                category_id="expense-category",
                components=[
                    ("cost", 45_280_000_000),
                    ("cash", 39_280_000_000),
                    ("adjustment", 6_000_000_000),
                ],
                lines=[
                    ("expense", 45_280_000_000, 0),
                    ("cash", 0, 39_280_000_000),
                    ("pending", 0, 6_000_000_000),
                ],
            )
        connection.commit()


def _assert_normalized(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM business_records").fetchone() == (5,)
        assert connection.execute(
            "SELECT COUNT(*) FROM business_records WHERE record_type NOT IN ('income', 'expense')"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM money_components WHERE role = 'adjustment'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM accounts WHERE subtype IN ('clearing', 'pending_difference')"
        ).fetchone() == (0,)
        assert connection.execute(
            """
            SELECT amount_cny_e8 FROM money_components
            WHERE record_id = 'tdsql-difference' AND role = 'cost'
            """
        ).fetchone() == (39_280_000_000,)
        assert connection.execute(
            """
            SELECT
              json_extract(metadata_json, '$.legacy_operating_amount_cny'),
              json_extract(metadata_json, '$.unreconciled_difference_cny')
            FROM business_records WHERE id = 'tdsql-difference'
            """
        ).fetchone() == ("452.8", "0")
        assert connection.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT je.id FROM journal_entries je
              JOIN journal_lines jl ON jl.entry_id = je.id
              WHERE je.status = 'posted'
              GROUP BY je.id
              HAVING SUM(jl.debit_cny_e8) != SUM(jl.credit_cny_e8)
            )
            """
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action LIKE 'migration.%normalize'"
        ).fetchone() == (5,)
        assert connection.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'trigger' AND name = 'posted_line_no_update'
            """
        ).fetchone() == (1,)

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    with Session(engine) as session:
        workspace = session.get(Workspace, "workspace")
        assert workspace is not None
        report = overview(session, workspace, date(2026, 1, 1), date(2026, 8, 29))
        assert report.cash_in == "138.45"
        assert report.cash_out == "459.80"
        assert report.net_cash == "-321.35"
    engine.dispose()


def test_cash_normalization_migration_is_balanced_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "cash-normalization.db"
    _create_legacy_fixture(database)

    first = _run_alembic(database, "head")
    assert first.returncode == 0, first.stdout + first.stderr
    _assert_normalized(database)

    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE alembic_version SET version_num = '0007_normalize_counterparty_roles'"
        )
        connection.commit()
    second = _run_alembic(database, "head")
    assert second.returncode == 0, second.stdout + second.stderr
    _assert_normalized(database)


def test_cash_normalization_migration_rolls_back_completely_on_failure(
    tmp_path: Path,
) -> None:
    database = tmp_path / "cash-normalization-rollback.db"
    _create_legacy_fixture(database, include_system_funds=False)

    result = _run_alembic(database, "head")
    assert result.returncode != 0
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "0007_normalize_counterparty_roles",
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM money_components WHERE record_id = 'historical-income'"
        ).fetchone() == (3,)
        assert connection.execute(
            "SELECT account_id FROM journal_lines WHERE id = 'line-historical-income-0'"
        ).fetchone() == ("clearing",)
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action LIKE 'migration.%normalize'"
        ).fetchone() == (0,)
        assert connection.execute(
            """
            SELECT COUNT(*) FROM sqlite_master
            WHERE type = 'trigger' AND name = 'posted_line_no_update'
            """
        ).fetchone() == (1,)
