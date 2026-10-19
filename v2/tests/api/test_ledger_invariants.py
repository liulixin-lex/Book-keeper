"""Ledger invariants the database enforces on its own, and the health checks that watch them."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.api.conftest import login, write_headers
from tests.api.ledger_helpers import journal, line, sale


def test_database_rejects_tampering(client, world, app) -> None:
    csrf = login(client, world.admin_email)
    posted = sale(client, world.book_id, csrf)
    entry_id = posted["entries"][0]["id"]
    with app.state.engine.connect() as conn:
        for statement, pattern in (
            ("UPDATE journal_lines SET amount = amount + 1", "append-only"),
            ("UPDATE journal_lines SET memo = 'x'", "append-only"),
            ("DELETE FROM journal_lines", "append-only"),
            ("UPDATE journal_entries SET description = 'x'", "only"),
            ("DELETE FROM journal_entries", "append-only"),
            ("TRUNCATE journal_lines CASCADE", "append-only"),
            ("UPDATE journal_entries SET recorded_at = now() - interval '1 day'", "only"),
        ):
            with pytest.raises(DBAPIError, match=pattern):
                conn.execute(text(statement))
            conn.rollback()
        conn.execute(text("UPDATE journal_entries SET reversed_by_entry_id = id WHERE id = :e"), {"e": entry_id})
        conn.rollback()


def test_database_rejects_unbalanced_and_invalid_lines(client, world, app) -> None:
    csrf = login(client, world.admin_email)
    posted = sale(client, world.book_id, csrf)
    entry = posted["entries"][0]
    with app.state.engine.connect() as conn:
        account = conn.execute(
            text("SELECT id FROM accounts WHERE book_id = :b AND code = '1012.01'"), {"b": world.book_id}
        ).scalar()
        txn = posted["id"]
        conn.execute(
            text("""
            INSERT INTO journal_entries (id, book_id, seq, transaction_id, kind, journal_code, number,
                effective_date, engine_version, description, line_count, channel, prev_hash, hash)
            VALUES ('jen_X', :b, 99, :t, 'posting', '记', 'X-1', '2026-10-18', 'x', 'forged', 2, 'api',
                    '\\x00', '\\x00')
        """),
            {"b": world.book_id, "t": txn},
        )
        for n, amount in ((1, 100), (2, -99)):
            conn.execute(
                text("""
                INSERT INTO journal_lines (id, book_id, entry_id, line_no, account_id, commodity, amount, base_amount,
                    line_role, effective_date, account_seq, balance_after, base_balance_after)
                VALUES (:id, :b, 'jen_X', :n, :a, 'CNY', :amt, :amt, 'manual', '2026-10-18', 1000 + :n, 0, 0)
            """),
                {"id": f"jln_X{n}", "b": world.book_id, "n": n, "a": account, "amt": amount},
            )
        with pytest.raises(DBAPIError, match="not balanced"):
            conn.commit()
        conn.rollback()
        group = conn.execute(
            text("SELECT id FROM accounts WHERE book_id = :b AND code = '5401'"), {"b": world.book_id}
        ).scalar()
        with pytest.raises(DBAPIError, match="not postable"):
            conn.execute(
                text("""
                INSERT INTO journal_lines (id, book_id, entry_id, line_no, account_id, commodity, amount, base_amount,
                    line_role, effective_date, account_seq, balance_after, base_balance_after)
                VALUES ('jln_Y', :b, :e, 9, :a, 'CNY', 1, 1, 'manual', '2026-10-18', 999, 0, 0)
            """),
                {"b": world.book_id, "e": entry["id"], "a": group},
            )
        conn.rollback()
        with pytest.raises(DBAPIError, match="base-currency line"):
            conn.execute(
                text("""
                INSERT INTO journal_lines (id, book_id, entry_id, line_no, account_id, commodity, amount, base_amount,
                    line_role, effective_date, account_seq, balance_after, base_balance_after)
                VALUES ('jln_Z', :b, :e, 9, :a, 'CNY', 100, 90, 'manual', '2026-10-18', 998, 0, 0)
            """),
                {"b": world.book_id, "e": entry["id"], "a": account},
            )
        conn.rollback()


def test_account_guards(client, world, app) -> None:
    csrf = login(client, world.admin_email)
    created = client.post(
        f"/api/v1/books/{world.book_id}/accounts",
        headers=write_headers(csrf),
        json={"code": "5401.05", "name": "模型调用"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["classification"] == "expense" and created.json()["data"]["level"] == 2
    wrong = client.post(
        f"/api/v1/books/{world.book_id}/accounts", headers=write_headers(csrf), json={"code": "5402.01", "name": "x"}
    )
    assert wrong.status_code == 422 and "上级科目 5402 不存在" in wrong.json()["detail"]
    sys_role = client.post(
        f"/api/v1/books/{world.book_id}/accounts",
        headers=write_headers(csrf),
        json={"code": "5401.06", "name": "x", "role": "trading"},
    )
    assert "系统角色" in sys_role.json()["detail"]
    sale(client, world.book_id, csrf)
    funds = client.get(f"/api/v1/books/{world.book_id}/accounts/1012.01").json()["data"]
    assert funds["balances"][0]["balance"] == 9700
    narrow = client.patch(
        f"/api/v1/books/{world.book_id}/accounts/1012.01",
        headers=write_headers(csrf),
        json={"expected_version": funds["version"], "allowed_commodities": ["GBP"]},
    )
    assert narrow.status_code == 422 and "postings" in narrow.json()["detail"]
    with app.state.engine.connect() as conn:
        with pytest.raises(DBAPIError, match="has postings"):
            conn.execute(
                text("UPDATE accounts SET normal_side = 'credit' WHERE code = '1012.01' AND book_id = :b"),
                {"b": world.book_id},
            )
        conn.rollback()


def test_balance_rule_normal_side_only(client, world) -> None:
    csrf = login(client, world.admin_email)
    funds = client.get(f"/api/v1/books/{world.book_id}/accounts/1012.01").json()["data"]
    client.patch(
        f"/api/v1/books/{world.book_id}/accounts/1012.01",
        headers=write_headers(csrf),
        json={"expected_version": funds["version"], "balance_rule": "normal_side_only"},
    )
    body = journal(
        client,
        world.book_id,
        csrf,
        [line("5602.99", "debit", "10.00"), line("1012.01", "credit", "10.00")],
        expect=422,
    )
    assert body["code"] == "BALANCE_RULE_VIOLATION"


def test_checks_pass_then_detect_tampering(client, world, app) -> None:
    csrf = login(client, world.admin_email)
    sale(client, world.book_id, csrf, date="2026-10-01")
    sale(client, world.book_id, csrf, date="2026-09-30")
    run = client.post(f"/api/v1/books/{world.book_id}/checks:run", headers=write_headers(csrf), json={}).json()["data"]
    assert run["status"] == "passed", run
    with app.state.engine.begin() as conn:
        conn.execute(text("ALTER TABLE journal_lines DISABLE TRIGGER journal_lines_immutable"))  # simulate tampering
        conn.execute(text("UPDATE journal_lines SET memo = 'forged' WHERE line_no = 1"))
        conn.execute(text("ALTER TABLE journal_lines ENABLE TRIGGER journal_lines_immutable"))
        conn.execute(text("UPDATE account_balances SET balance = balance + 1 WHERE commodity = 'CNY' AND balance > 0"))
    run = client.post(f"/api/v1/books/{world.book_id}/checks:run", headers=write_headers(csrf), json={}).json()["data"]
    failed = {r["code"] for r in run["results"] if r["status"] == "fail"}
    assert {"hash_chain", "balances_cache"} <= failed
    chain = next(r for r in run["results"] if r["code"] == "hash_chain")
    assert chain["details"][0]["reason"] == "hash mismatch"
    history = client.get(f"/api/v1/books/{world.book_id}/check-runs").json()["data"]
    assert [h["status"] for h in history] == ["failed", "passed"]
