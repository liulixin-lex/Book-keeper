"""v1 → v2 migration against a small synthetic v1 database with the real schema subset."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from sqlalchemy import func, select

from bookkeeper.db.models import Attachment, Counterparty, CounterpartyAlias, LegacyMap, SourceRecord, Transaction, User
from bookkeeper.migration import legacy_v1
from bookkeeper.security import passwords

SCHEMA = """
create table workspaces (id text, name text, base_currency text, created_at text, updated_at text);
create table users (id text, workspace_id text, email text, display_name text, password_hash text, role text,
                    is_active int, created_at text, updated_at text, username text, deleted_at text);
create table accounts (id text, workspace_id text, code text, name text, account_type text, subtype text,
                       currency text, is_active int, created_at text, updated_at text);
create table categories (id text, workspace_id text, parent_id text, account_id text, name text, kind text,
                         is_active int, created_at text, updated_at text);
create table counterparties (id text, workspace_id text, name text, roles_json text, metadata_json text,
                             is_active int, created_at text, updated_at text, expense_category_id text);
create table business_records (id text, workspace_id text, record_type text, status text, accounting_date text,
  occurred_at text, date_precision text, service_period_start text, service_period_end text, project_id text,
  category_id text, counterparty_id text, payment_account_id text, source_document_id text, source_channel text,
  external_id text, business_fingerprint text, recognition_method text, description text, note text,
  source_locator_json text, metadata_json text, version int, created_by_user_id text, created_by_ai_run_id text,
  posted_entry_id text, reversed_by_record_id text, created_at text, updated_at text);
create table money_components (id text, record_id text, role text, sequence int, currency text, amount_e8 int,
                               amount_cny_e8 int, fx_rate_id text, is_derived int, raw_amount_text text);
create table fx_rates (id text, base_currency text, quote_currency text, rate_e12 int, effective_at text,
                       source text, rate_type text, fetched_at text);
create table source_documents (id text, workspace_id text, filename text, mime_type text, sha256 text,
                               storage_path text, size_bytes int, uploaded_by_id text, created_at text, updated_at text);
create table journal_entries (id text, workspace_id text, record_id text, entry_date text, status text, memo text,
                              reversal_of_id text, posted_by_user_id text, posted_by_ai_run_id text, posted_at text);
create table journal_lines (id text, entry_id text, account_id text, debit_cny_e8 int, credit_cny_e8 int,
                            original_currency text, original_amount_e8 int, description text);
create table audit_events (id text, action text, created_at text);
"""
E8 = 100_000_000
STATEMENT = b"date,amount\n2026-09-06,20\n"


def build_v1(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute("insert into workspaces values ('ws','旧账本','CNY','','')")
    admin_hash = passwords.hash_password("old-password-123")
    con.execute(
        "insert into users values ('u1','ws','boss@example.com','老板',?, 'admin',1,'','','boss',null)", (admin_hash,)
    )
    con.execute(
        "insert into users values ('u2','ws','keeper@example.com','记账',?, 'bookkeeper',1,'','','keeper',null)",
        (passwords.hash_password("another-password"),),
    )
    accounts = {
        "1002": "银行存款",
        "5001": "主营业务收入",
        "5401": "主营业务成本",
        "5602": "管理费用",
        "5603": "财务费用",
    }
    for code, name in accounts.items():
        con.execute("insert into accounts values (?, 'ws', ?, ?, '', '', 'CNY', 1, '', '')", (f"a{code}", code, name))
    cats = {
        "链动收入": ("income", "5001"),
        "Stripe收入": ("income", "5001"),
        "xorpay收入": ("income", "5001"),
        "上游充值": ("expense", "5401"),
        "账号购买": ("expense", "5401"),
        "订阅": ("expense", "5401"),
        "其他支出": ("expense", "5401"),
    }
    for name, (kind, code) in cats.items():
        con.execute(
            "insert into categories values (?, 'ws', null, ?, ?, ?, 1, '', '')", (f"c-{name}", f"a{code}", name, kind)
        )
    for name in ("api.relay-a.example", "sub.relay-g.example", "链动小铺", "OpenAI", "AdCo（广告）"):
        con.execute("insert into counterparties values (?, 'ws', ?, '[]', '{}', 1, '', '', null)", (f"p-{name}", name))
    lines: list[tuple[str, str, int, int]] = []

    def record(
        rid: str,
        rtype: str,
        day: str,
        cat: str,
        cp: str | None,
        desc: str,
        comps: list[tuple[str, str, float, float]],
        *,
        ext: str | None = None,
        md: dict | None = None,
        occurred: str | None = None,
    ) -> None:
        con.execute(
            "insert into business_records (id, workspace_id, record_type, status, accounting_date, occurred_at, date_precision,"
            " category_id, counterparty_id, external_id, description, metadata_json, created_by_user_id)"
            " values (?, 'ws', ?, 'posted', ?, ?, ?, ?, ?, ?, ?, ?, 'u2')",
            (
                rid,
                rtype,
                day,
                occurred,
                "timestamp" if occurred else "day",
                f"c-{cat}",
                f"p-{cp}" if cp else None,
                ext,
                desc,
                json.dumps(md or {}, ensure_ascii=False),
            ),
        )
        for role, cur, amount, cny in comps:
            con.execute(
                "insert into money_components values (?, ?, ?, 0, ?, ?, ?, null, 0, '')",
                (str(uuid.uuid4()), rid, role, cur, round(amount * E8), round(cny * E8)),
            )
        entry = f"e-{rid}"
        con.execute(
            "insert into journal_entries values (?, 'ws', ?, ?, 'posted', '', null, 'u2', null, '')", (entry, rid, day)
        )
        cash = sum(c[3] for c in comps if c[0] in ("cash",))
        gross = sum(c[3] for c in comps if c[0] == "gross")
        fee = sum(c[3] for c in comps if c[0] == "fee")
        if rtype == "income":
            lines.extend(
                [
                    (entry, "a1002", round((gross - fee) * E8), 0),
                    (entry, "a5603", round(fee * E8), 0),
                    (entry, "a5001", 0, round(gross * E8)),
                ]
            )
        else:
            cost = sum(c[3] for c in comps if c[0] == "cost")
            account = "a5602" if cat == "其他支出" else "a5401"
            lines.extend(
                [
                    (entry, account, round(cost * E8), 0),
                    (entry, "a5603", round((cash - cost) * E8), 0),
                    (entry, "a1002", 0, round(cash * E8)),
                ]
            )

    record(
        "r1",
        "income",
        "2026-09-01",
        "链动收入",
        None,
        "2",
        [("gross", "CNY", 100, 100), ("fee", "CNY", 3, 3), ("net", "CNY", 97, 97)],
    )
    record(
        "r2",
        "income",
        "2026-09-02",
        "Stripe收入",
        None,
        "1",
        [("gross", "GBP", 20, 190), ("fee", "GBP", 1, 9.5), ("net", "CNY", 180.5, 180.5)],
        ext="ch_123",
    )
    record(
        "r3",
        "income",
        "2026-09-03",
        "xorpay收入",
        None,
        "3",
        [("gross", "CNY", 53, 53), ("fee", "CNY", 0.848, 0.848), ("net", "CNY", 52.152, 52.152)],
    )
    record(
        "r4",
        "expense",
        "2026-09-04",
        "上游充值",
        "api.relay-a.example",
        "上游",
        [
            ("cost", "CNY", 100, 100),
            ("cash", "CNY", 103, 103),
            ("fee", "CNY", 3, 3),
            ("credited_value", "UPSTREAM_CREDIT", 103, 103),
        ],
        md={"lines": ["10:00:01 $50←链动LD260904AAAAAA", "11:00:02 $53 账号A", "看不懂的一行"]},
        occurred="2026-09-04 02:00:00.000000",
    )
    record(
        "r5",
        "expense",
        "2026-09-05",
        "账号购买",
        "链动小铺",
        "示例 Plus 成品号 质保首登【网页+反代+已接码】",
        [("cost", "CNY", 30, 30), ("cash", "CNY", 30, 30)],
        ext="LD260905BBBBBB",
    )
    record(
        "r6",
        "expense",
        "2026-09-06",
        "订阅",
        "OpenAI",
        "pro2 / OpenAI",
        [("cost", "USD", 20, 144), ("cash", "USD", 20, 144)],
    )
    record("r7", "expense", "2026-09-07", "订阅", "OpenAI", "手续费", [("cost", "CNY", 2, 2), ("cash", "CNY", 2, 2)])
    record(
        "r8",
        "expense",
        "2026-09-08",
        "其他支出",
        "AdCo（广告）",
        "PromoPlus 广告费",
        [("cost", "CNY", 50, 50), ("cash", "CNY", 50, 50)],
    )
    record(
        "r9",
        "expense",
        "2026-09-09",
        "上游充值",
        "api.relay-a.example",
        "坏数据",
        [("cost", "CNY", 10, 10), ("cash", "CNY", 8, 8)],
    )
    for i, (entry, account, debit, credit) in enumerate(lines):
        con.execute(
            "insert into journal_lines values (?, ?, ?, ?, ?, 'CNY', 0, '')", (f"l{i}", entry, account, debit, credit)
        )
    con.execute(
        "insert into fx_rates values ('f1','GBP','CNY',9500000000000,'2026-09-02 00:00:00','Frankfurter','daily_reference','')"
    )
    con.execute(
        "insert into fx_rates values ('f2','JPY','CNY',48000000000,'2026-09-02 00:00:00','Frankfurter','daily_reference','')"
    )
    con.execute(
        "insert into source_documents values ('d1','ws','x.xlsx','',?,'C:\\\\nowhere\\\\x.xlsx',1,'u1','','')",
        (hashlib.sha256(STATEMENT).hexdigest(),),
    )
    con.execute("update business_records set source_document_id = 'd1' where id in ('r6', 'r7')")
    con.execute("insert into audit_events values ('ev1','record.create','')")
    con.commit()
    con.close()


def test_dry_run_then_apply(app, tmp_path: Path) -> None:
    source = tmp_path / "v1.db"
    build_v1(source)
    originals = tmp_path / "originals"
    originals.mkdir()
    # An owner's own names live in a local file, not in the code: a vendor's legal name, a site's nickname.
    mappings = tmp_path / "mappings.json"
    mappings.write_text(
        json.dumps(
            {
                "renames": {"AdCo（广告）": ["AdCo", "marketing_vendor", []]},
                "site_aliases": {"sub.relay-g.example": ["极光"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    names = legacy_v1.Names.load(mappings)
    (originals / "x.xlsx").write_bytes(STATEMENT)
    with app.state.sessionmaker() as session:
        session.begin()
        report = legacy_v1.migrate(session, source, dry_run=True, files_dir=originals, names=names)
        session.rollback()
    assert report.counts["source_files_matched"] == 1 and report.counts["source_file_links"] == 2
    assert report.counts["records"] == 9 and report.counts["migrated"] == 8
    assert [a["record"] for a in report.anomalies] == ["r9"] and "现金" in report.anomalies[0]["reason"]
    failed = {k: v for k, v in report.checks.items() if not v["ok"]}
    assert not failed, failed
    assert {r["role"] for r in report.rounding} >= {"fee"}
    assert report.counts["evidence_items"] == 2 and report.counts["evidence_unparsed"] == 1
    assert report.counts["fx_rates"] == 1 and report.counts["fx_rates_skipped"] == 1
    with app.state.sessionmaker() as session:
        assert session.execute(select(func.count()).select_from(Transaction)).scalar_one() == 0  # rolled back

    with app.state.sessionmaker() as session:
        session.begin()
        applied = legacy_v1.migrate(
            session, source, dry_run=False, files_dir=originals, store=app.state.content_store, names=names
        )
        session.commit()
    assert all(c["ok"] for c in applied.checks.values())
    markdown = legacy_v1.render_markdown(applied)
    assert "| V1_records | ✅ |" in markdown and "坏数据" in markdown
    with app.state.sessionmaker() as session:
        txns = {t.metadata_["legacy"]["id"]: t for t in session.execute(select(Transaction)).scalars()}
        assert txns["r2"].computed["fx_rate"] == "9.500000000000"
        assert txns["r4"].description == "api.relay-a.example · 额度采购 · 2026-09-04 合计 2 笔"
        assert txns["r4"].occurred_at is not None and txns["r4"].effective_date.isoformat() == "2026-09-04"
        assert txns["r5"].description == "链动 · 账号 · 示例 Plus 成品号 质保首登"
        assert txns["r6"].description == "OpenAI · AI 服务订阅 · pro2"
        assert txns["r7"].description == "OpenAI · 手续费"
        assert txns["r8"].description == "AdCo · 广告推广 · PromoPlus 广告费"
        assert txns["r2"].external_ref == "ch_123" and txns["r5"].order_no == "LD260905BBBBBB"
        # Upstream sites keep their own host; 极光 stays an alias; no parent-domain names or aliases are made up.
        sites = {c.name: c for c in session.execute(select(Counterparty)).scalars()}
        assert {"api.relay-a.example", "sub.relay-g.example"} <= set(sites) and "relay-a.example" not in sites
        assert txns["r4"].counterparty_id == sites["api.relay-a.example"].id
        aliases = {
            (a.counterparty_id, a.pattern, a.match_type) for a in session.execute(select(CounterpartyAlias)).scalars()
        }
        assert {(cp, p) for cp, p, _m in aliases if cp == sites["api.relay-a.example"].id} == {
            (sites["api.relay-a.example"].id, "api.relay-a.example")
        }
        assert (sites["sub.relay-g.example"].id, "极光", "exact") in aliases
        assert all(t.created_channel == "migration" for t in txns.values())
        boss = session.execute(select(User).where(User.email == "boss@example.com")).scalar_one()
        assert passwords.verify_password(boss.password_hash, "old-password-123")
        evidence = (
            session.execute(select(SourceRecord).where(SourceRecord.transaction_id == txns["r4"].id)).scalars().all()
        )
        assert sorted(e.order_no or "" for e in evidence) == ["", "LD260904AAAAAA"]
        assert session.execute(select(func.count()).select_from(LegacyMap)).scalar_one() >= 8 + 4 + 2
        linked = session.execute(select(Attachment.entity_id).where(Attachment.role == "statement")).scalars().all()
        assert sorted(linked) == sorted([txns["r6"].id, txns["r7"].id])
