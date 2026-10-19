"""Ledger benchmark (docs/02 NFR-04): posting latency and report latency at ~1M journal lines.

Usage: uv run python scripts/bench_ledger.py [--posts 500] [--lines 1000000]
Starts a throwaway PostgreSQL cluster (same helper as the tests) unless BK_TEST_DATABASE_URL is set.
The bulk-loaded history bypasses triggers (benchmark only) and is not hash-chained.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from tests import pg

from bookkeeper.domain.scopes import ROLE_CAPS, Role
from bookkeeper.paths import ALEMBIC_INI
from bookkeeper.services import books, checks, identity, reports, transactions
from bookkeeper.services.context import Actor, RequestContext


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * q))]


def timed(label: str, fn, repeat: int = 5) -> None:  # type: ignore[no-untyped-def]
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    print(f"{label:<38} p50 {statistics.median(samples):8.1f} ms   p95 {pct(samples, 0.95):8.1f} ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--posts", type=int, default=500)
    parser.add_argument("--lines", type=int, default=1_000_000)
    args = parser.parse_args()

    server = pg.start()
    admin = create_engine(server.admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS bk_bench"))
        conn.execute(text("CREATE DATABASE bk_bench"))
    url = server.url_for("bk_bench")
    config = Config(str(ALEMBIC_INI))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as s, s.begin():
            sys_ctx = RequestContext(actor=Actor.system(), channel="cli")
            user = identity.create_user(
                s, sys_ctx, email="bench@example.com", display_name="b", password="bench password 1", is_superadmin=True
            )
            book = books.create_book(s, sys_ctx, name="bench", owner_user_id=user.id)
            book_id, user_id = book.id, user.id
        ctx = RequestContext(
            actor=Actor(type="user", user_id=user_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER]),
            channel="api",
            book_id=book_id,
        )

        bulk_entries = args.lines // 4
        print(f"bulk loading {bulk_entries:,} entries / {bulk_entries * 4:,} lines …", flush=True)
        start = time.perf_counter()
        with engine.begin() as conn:
            conn.execute(text("SET session_replication_role = replica"))  # skip triggers (bench only)
            acc = dict(conn.execute(text("SELECT code, id FROM accounts WHERE book_id = :b"), {"b": book_id}).all())
            tty = conn.execute(
                text("SELECT id FROM transaction_types WHERE book_id = :b AND code = 'manual_journal'"), {"b": book_id}
            ).scalar()
            conn.execute(
                text("""
                INSERT INTO fiscal_periods (id, book_id, year, month, start_date, end_date)
                SELECT 'fp_bench_' || to_char(m, 'YYYYMM'), :b, extract(year FROM m), extract(month FROM m), m::date,
                       (m + interval '1 month - 1 day')::date
                FROM generate_series('2022-01-01'::date, '2026-12-01'::date, interval '1 month') m
                ON CONFLICT DO NOTHING
            """),
                {"b": book_id},
            )
            params = {
                "b": book_id,
                "n": bulk_entries,
                "t": tty,
                "f": acc["1012.01"],
                "r": acc["5001.01"],
                "e": acc["5603.01"],
                "c": acc["5401.01"],
            }
            conn.execute(
                text("""
                INSERT INTO transactions (id, book_id, number, transaction_type_id, status, effective_date, description,
                    created_channel, inputs, computed, default_dimensions, provenance, metadata)
                SELECT 'txn_b' || g, :b, 'B' || g, :t, 'posted', date '2022-01-01' + (g % 1800), 'bench', 'migration',
                       '{}', '{}', '{}', '{}', '{}'
                FROM generate_series(1, :n) g
            """),
                params,
            )
            conn.execute(
                text("""
                INSERT INTO journal_entries (id, book_id, seq, transaction_id, kind, journal_code, number, period_id,
                    effective_date, engine_version, description, line_count, channel, prev_hash, hash)
                SELECT 'jen_b' || g, :b, g, 'txn_b' || g, 'posting', '记', 'B-' || g,
                       'fp_bench_' || to_char(date '2022-01-01' + (g % 1800), 'YYYYMM'),
                       date '2022-01-01' + (g % 1800), 'bench', 'bench', 4, 'migration', '\\x00', '\\x00'
                FROM generate_series(1, :n) g
            """),
                params,
            )
            conn.execute(
                text("""
                INSERT INTO journal_lines (id, book_id, entry_id, line_no, account_id, commodity, amount, base_amount,
                    line_role, effective_date, account_seq, balance_after, base_balance_after)
                SELECT 'jln_b' || g || '_' || k, :b, 'jen_b' || g, k,
                       CASE k WHEN 1 THEN :f WHEN 2 THEN :e WHEN 3 THEN :r ELSE :c END, 'CNY',
                       CASE k WHEN 1 THEN 9700 WHEN 2 THEN 300 WHEN 3 THEN -10000 ELSE 0 END
                         + CASE k WHEN 4 THEN 0 ELSE 0 END,
                       CASE k WHEN 1 THEN 9700 WHEN 2 THEN 300 WHEN 3 THEN -10000 ELSE 0 END,
                       'manual', date '2022-01-01' + (g % 1800), -(g * 10 + k), 0, 0
                FROM generate_series(1, :n) g CROSS JOIN generate_series(1, 3) k
            """),
                params,
            )
            conn.execute(
                text("""
                INSERT INTO journal_lines (id, book_id, entry_id, line_no, account_id, commodity, amount, base_amount,
                    line_role, effective_date, account_seq, balance_after, base_balance_after)
                SELECT 'jln_b' || g || '_4', :b, 'jen_b' || g, 4, :c, 'CNY', 5000, 5000, 'manual',
                       date '2022-01-01' + (g % 1800), -(g * 10 + 4), 0, 0 FROM generate_series(1, :n) g
                UNION ALL
                SELECT 'jln_b' || g || '_5', :b, 'jen_b' || g, 5, :f, 'CNY', -5000, -5000, 'manual',
                       date '2022-01-01' + (g % 1800), -(g * 10 + 5), 0, 0 FROM generate_series(1, :n) g
            """),
                params,
            )
            conn.execute(text("DELETE FROM journal_lines WHERE book_id = :b AND amount = 0"), params)
            conn.execute(
                text("""
                INSERT INTO daily_balances (account_id, commodity, date, book_id, debit, credit, base_debit, base_credit, line_count)
                SELECT account_id, commodity, effective_date, book_id, sum(greatest(amount, 0)), sum(greatest(-amount, 0)),
                       sum(greatest(base_amount, 0)), sum(greatest(-base_amount, 0)), count(*)
                FROM journal_lines WHERE book_id = :b GROUP BY 1, 2, 3, 4
            """),
                params,
            )
            conn.execute(
                text("""
                INSERT INTO account_balances (account_id, commodity, book_id, balance, base_balance, debit_total, credit_total,
                    base_debit_total, base_credit_total, line_count)
                SELECT account_id, commodity, book_id, sum(amount), sum(base_amount), sum(greatest(amount, 0)),
                       sum(greatest(-amount, 0)), sum(greatest(base_amount, 0)), sum(greatest(-base_amount, 0)), count(*)
                FROM journal_lines WHERE book_id = :b GROUP BY 1, 2, 3
            """),
                params,
            )
            conn.execute(text("UPDATE ledger_heads SET last_seq = :n WHERE book_id = :b"), params)
            conn.execute(
                text("""
                INSERT INTO ledger_heads (book_id, last_seq, last_entry_hash) VALUES (:b, :n, '\\x00')
                ON CONFLICT (book_id) DO UPDATE SET last_seq = :n
            """),
                params,
            )
            conn.execute(text("UPDATE sequences SET next_value = :n + 1 WHERE book_id = :b"), params)
        with engine.connect() as conn:
            conn.execute(text("ANALYZE"))
            total = conn.execute(text("SELECT count(*) FROM journal_lines")).scalar()
        print(f"loaded {total:,} lines in {time.perf_counter() - start:.1f}s", flush=True)

        latencies = []
        for i in range(args.posts):
            start = time.perf_counter()
            with factory() as s, s.begin():
                txn = transactions.create(
                    s,
                    ctx,
                    {
                        "type": "manual_journal",
                        "effective_date": date(2026, 10, 1) + timedelta(days=i % 28),
                        "description": "调整 · 基准",
                        "lines": [
                            transactions.LineSpec("1012.01", "debit", "97.00", "CNY"),
                            transactions.LineSpec("5603.01", "debit", "3.00", "CNY"),
                            transactions.LineSpec(
                                "5001.01", "credit", "100.00", "CNY", dimensions={"channel": "liandong"}
                            ),
                        ],
                    },
                )
                transactions.post(s, ctx, txn.id)
            latencies.append((time.perf_counter() - start) * 1000)
        print(
            f"{'create + post (3 lines)':<38} p50 {statistics.median(latencies):8.1f} ms   p95 {pct(latencies, 0.95):8.1f} ms   n={len(latencies)}"
        )

        def read(fn):  # type: ignore[no-untyped-def]
            def run() -> None:
                with factory() as s, s.begin():
                    fn(s)

            return run

        timed(
            "trial balance (1 year)",
            read(lambda s: reports.trial_balance(s, ctx, date(2025, 1, 1), date(2025, 12, 31))),
        )
        timed(
            "trial balance (all history)",
            read(lambda s: reports.trial_balance(s, ctx, date(2022, 1, 1), date(2026, 12, 31))),
        )
        timed("balances as of today", read(lambda s: reports.balances(s, ctx, date(2026, 10, 31))))
        timed(
            "account register (1 month, funds)",
            read(lambda s: reports.account_register(s, ctx, "1012.01", date(2025, 3, 1), date(2025, 3, 31))),
        )
        timed(
            "general ledger (1 year)",
            read(lambda s: reports.general_ledger(s, ctx, date(2025, 1, 1), date(2025, 12, 31))),
        )
        from datetime import UTC, datetime

        timed(
            "trial balance as_known_at (lines)",
            read(lambda s: reports.trial_balance(s, ctx, date(2025, 1, 1), date(2025, 12, 31), datetime.now(UTC))),
            repeat=3,
        )
        timed(
            "checks: balances + daily caches",
            read(lambda s: checks.run_checks(s, ctx, ["balances_cache", "daily_balances", "trial_balance_zero"])),
            repeat=2,
        )
    finally:
        engine.dispose()
        admin.dispose()
        server.stop()


if __name__ == "__main__":
    main()
