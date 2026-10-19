from sqlalchemy import func, select

from bookkeeper.db.models import Account, DimensionValue, TransactionType
from tests.api.conftest import login, write_headers
from tests.api.ledger_helpers import delete, journal, line, sale


def test_new_book_is_initialized(app, world) -> None:
    with app.state.sessionmaker() as s:
        codes = set(s.execute(select(Account.code).where(Account.book_id == world.book_id)).scalars())
        assert {"1012.01", "1999", "3901", "5001.01", "5401.01", "5401.04", "5603.09"} <= codes
        assert len(codes) == 35
        assert (
            s.execute(
                select(func.count()).select_from(TransactionType).where(TransactionType.book_id == world.book_id)
            ).scalar_one()
            == 8
        )
        channels = set(s.execute(select(DimensionValue.name).where(DimensionValue.book_id == world.book_id)).scalars())
        assert {"链动", "云猫", "Stripe", "站内商店"} <= channels
        defaults = (
            s.execute(
                select(Account.code).where(
                    Account.book_id == world.book_id, Account.role == "cost_operating", Account.is_default_for_role
                )
            )
            .scalars()
            .all()
        )
        assert defaults == ["5401.01"]


def test_manual_journal_posts_at_once(client, world) -> None:
    csrf = login(client, world.admin_email)
    posted = journal(
        client,
        world.book_id,
        csrf,
        [
            line("1012.01", "debit", "97.00"),
            line("5603.01", "debit", "3.00"),
            line("5001.01", "credit", "100.00", dimensions={"channel": "liandong"}),
        ],
    )
    assert posted["status"] == "posted"
    assert posted["number"].startswith("T2026-")
    assert posted["computed"]["entry_number"] == "记-202610-0001"
    entry = posted["entries"][0]
    assert entry["kind"] == "posting" and len(entry["lines"]) == 3
    assert [l["account_code"] for l in entry["lines"]] == ["1012.01", "5603.01", "5001.01"]
    assert entry["lines"][2]["amount"]["display"] == "-¥100.00"
    assert entry["lines"][2]["dimensions"] == {"liandong": "链动"}
    balances = client.get(
        f"/api/v1/books/{world.book_id}/balances", params={"as_of": "2026-10-31", "accounts": ["1012.01"]}
    ).json()["data"]
    assert balances["balances"][0]["balance"]["display"] == "¥97.00"
    trial = client.post(
        f"/api/v1/books/{world.book_id}/transactions?dry_run=true",
        headers=write_headers(csrf),
        json={
            "type": "manual_journal",
            "effective_date": "2026-10-18",
            "description": "调整 · 试算",
            "lines": [line("1012.01", "debit", "1.00"), line("5001.01", "credit", "1.00")],
        },
    )
    assert trial.status_code == 200 and trial.json()["meta"]["dry_run"] is True
    assert trial.json()["data"]["entries"][0]["lines"][0]["amount"]["minor"] == 100
    listed = client.get(f"/api/v1/books/{world.book_id}/transactions").json()["data"]
    assert len(listed) == 1, "a dry run saves nothing"


def test_validation_errors(client, world) -> None:
    csrf = login(client, world.admin_email)
    bad = journal(
        client,
        world.book_id,
        csrf,
        [line("1012.01", "debit", "10.00"), line("5001.01", "credit", "9.99")],
        expect=422,
    )
    assert bad["code"] == "NOT_BALANCED"
    group = journal(
        client,
        world.book_id,
        csrf,
        [line("5401", "debit", "10.00"), line("1012.01", "credit", "10.00")],
        expect=422,
    )
    assert group["code"] == "ACCOUNT_NOT_POSTABLE" and group["errors"][0]["path"] == "lines.0.account"
    system = journal(
        client,
        world.book_id,
        csrf,
        [line("3901", "debit", "10.00"), line("1012.01", "credit", "10.00")],
        expect=422,
    )
    assert "不允许手工记账" in system["detail"]
    missing = journal(
        client, world.book_id, csrf, [line("9999", "debit", "1.00"), line("1012.01", "credit", "1.00")], expect=422
    )
    assert missing["code"] == "INPUT_INVALID" and missing["errors"][0]["path"] == "lines.0.account"
    precision = journal(
        client, world.book_id, csrf, [line("1012.01", "debit", "1.001"), line("5001.01", "credit", "1.001")], expect=422
    )
    assert "2 位小数" in precision["errors"][0]["message"]
    floaty = client.post(
        f"/api/v1/books/{world.book_id}/transactions",
        headers=write_headers(csrf),
        json={
            "type": "manual_journal",
            "effective_date": "2026-10-18",
            "description": "调整 · x",
            "lines": [{"account": "1012.01", "side": "debit", "amount": {"amount": 1.5, "commodity": "CNY"}}],
        },
    )
    assert floaty.status_code == 422


def test_foreign_currency_rounding_and_conversion(client, world) -> None:
    csrf = login(client, world.admin_email)
    rate = client.post(
        f"/api/v1/books/{world.book_id}/fx-rates",
        headers=write_headers(csrf),
        json={"base": "GBP", "quote": "CNY", "rate_date": "2026-10-18", "rate": "9.5127"},
    )
    assert rate.status_code == 201, rate.text
    data = journal(
        client,
        world.book_id,
        csrf,
        [
            line("1012.01", "debit", "19.15", "GBP"),
            line("5603.01", "debit", "0.85", "GBP"),
            line("5001.01", "credit", "20.00", "GBP", dimensions={"channel": "stripe"}),
        ],
        description="Stripe · API 额度销售",
    )
    lines = data["entries"][0]["lines"]
    assert [l["base_amount"] for l in lines] == [18217, 809, -19025, -1]
    assert lines[3]["account_code"] == "5603.09" and lines[3]["line_role"] == "rounding"
    assert data["warnings"][0]["code"] == "ROUNDING_APPLIED"
    blocked = journal(
        client,
        world.book_id,
        csrf,
        [line("1012.01", "debit", "188.50"), line("1012.01", "credit", "20.00", "GBP")],
        expect=422,
        description="结汇 · GBP → CNY",
    )
    assert "allow_conversion" in blocked["detail"]
    fx = journal(
        client,
        world.book_id,
        csrf,
        [line("1012.01", "debit", "188.50"), line("1012.01", "credit", "20.00", "GBP", fx_rate="9.5")],
        allow_conversion=True,
        description="结汇 · GBP → CNY",
    )
    summary = [
        (l["account_code"], l["commodity"], l["amount"]["minor"], l["base_amount"], l["line_role"])
        for l in fx["entries"][0]["lines"]
    ]
    assert ("5603.02", "GBP", 0, 150, "fx_realization") in summary
    assert sum(item[3] for item in summary) == 0


def test_missing_rate_reports_clear_error(client, world) -> None:
    csrf = login(client, world.admin_email)
    body = journal(
        client,
        world.book_id,
        csrf,
        [line("1012.01", "debit", "1.00", "USD"), line("5001.01", "credit", "1.00", "USD")],
        expect=422,
    )
    assert body["code"] == "FX_RATE_MISSING" and "USD→CNY" in body["detail"]


def test_opening_balance_offsets_automatically(client, world) -> None:
    csrf = login(client, world.admin_email)
    response = client.post(
        f"/api/v1/books/{world.book_id}/transactions",
        headers=write_headers(csrf),
        json={
            "type": "opening_balance",
            "effective_date": "2026-05-01",
            "lines": [line("1012.01", "debit", "1000.00")],
        },
    )
    assert response.status_code == 201, response.text
    lines = response.json()["data"]["entries"][0]["lines"]
    assert [(l["account_code"], l["amount"]["minor"], l["line_role"]) for l in lines] == [
        ("1012.01", 100000, "manual"),
        ("3902", -100000, "opening_offset"),
    ]
    assert response.json()["data"]["description"] == "期初余额"
    revenue = client.post(
        f"/api/v1/books/{world.book_id}/transactions",
        headers=write_headers(csrf),
        json={"type": "opening_balance", "effective_date": "2026-05-01", "lines": [line("5001.01", "credit", "1.00")]},
    )
    assert revenue.status_code == 422


def test_delete_and_edit_lifecycle(client, world) -> None:
    csrf = login(client, world.admin_email)
    posted = sale(client, world.book_id, csrf)
    ref = posted["id"]
    data = delete(client, world.book_id, csrf, ref, reason="录错金额")
    assert data["status"] == "reversed" and data["reversal_number"] == "记-202610-0002"
    assert data["reverse_reason"] == "录错金额"
    assert (
        data["entries"][1]["kind"] == "reversal"
        and data["entries"][0]["reversed_by_entry_id"] == data["entries"][1]["id"]
    )
    assert [l["amount"]["minor"] for l in data["entries"][1]["lines"]] == [-9700, -300, 10000]
    again = delete(client, world.book_id, csrf, ref, expect=409)
    assert again["code"] == "INVALID_STATE"
    balances = client.get(f"/api/v1/books/{world.book_id}/balances", params={"as_of": "2026-10-31"}).json()["data"][
        "balances"
    ]
    assert balances == []
    manual = journal(client, world.book_id, csrf, [line("1012.01", "debit", "1.00"), line("5001.01", "credit", "1.00")])
    patched = client.patch(
        f"/api/v1/books/{world.book_id}/transactions/{manual['id']}",
        headers=write_headers(csrf),
        json={"expected_version": 1, "lines": [line("1012.01", "debit", "2.00"), line("5001.01", "credit", "2.00")]},
    )
    assert patched.status_code == 200, patched.text
    entries = patched.json()["data"]["entries"]
    assert [e["kind"] for e in entries] == ["posting", "repost_reversal", "repost"]
    assert entries[-1]["lines"][0]["amount"]["minor"] == 200
    no_summary = client.patch(
        f"/api/v1/books/{world.book_id}/transactions/{manual['id']}",
        headers=write_headers(csrf),
        json={"description": ""},
    )
    assert no_summary.status_code == 422
    edit_deleted = client.patch(
        f"/api/v1/books/{world.book_id}/transactions/{ref}",
        headers=write_headers(csrf),
        json={"description": "改"},
    )
    assert edit_deleted.json()["code"] == "INVALID_STATE"
    noted = client.patch(
        f"/api/v1/books/{world.book_id}/transactions/{manual['id']}",
        headers=write_headers(csrf),
        json={"notes": "已核对"},
    )
    assert noted.json()["data"]["notes"] == "已核对" and len(noted.json()["data"]["entries"]) == 3


def test_trial_balance_and_entries(client, world) -> None:
    csrf = login(client, world.admin_email)
    sale(client, world.book_id, csrf, "100.00", "3.00", "2026-10-01")
    sale(client, world.book_id, csrf, "50.00", "1.50", "2026-10-02")
    tb = client.get(
        f"/api/v1/books/{world.book_id}/reports/trial-balance",
        params={"date_from": "2026-10-02", "date_to": "2026-10-31"},
    ).json()["data"]
    assert tb["balanced"] is True
    funds = next(l for l in tb["lines"] if l["account_code"] == "1012.01")
    assert (funds["opening"]["minor"], funds["debit"]["minor"], funds["closing"]["minor"]) == (9700, 4850, 14550)
    assert len(tb["meta"]["fingerprint"]) == 64 and tb["meta"]["ledger_seq"] == 2
    entries = client.get(f"/api/v1/books/{world.book_id}/journal-entries", params={"after_seq": 1}).json()["data"]
    assert [e["seq"] for e in entries] == [2]


def test_as_known_at_excludes_later_postings(client, world) -> None:
    from datetime import UTC, datetime

    csrf = login(client, world.admin_email)
    sale(client, world.book_id, csrf)
    cutoff = datetime.now(UTC).isoformat()
    sale(client, world.book_id, csrf, "50.00", "1.50", "2026-10-01")
    now_tb = client.get(
        f"/api/v1/books/{world.book_id}/reports/trial-balance",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
    ).json()["data"]
    then_tb = client.get(
        f"/api/v1/books/{world.book_id}/reports/trial-balance",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31", "as_known_at": cutoff},
    ).json()["data"]
    assert now_tb["totals"]["base_debit"]["minor"] == 15000
    assert then_tb["totals"]["base_debit"]["minor"] == 10000
    assert now_tb["meta"]["fingerprint"] != then_tb["meta"]["fingerprint"]


def test_idempotent_create_replay(client, world) -> None:
    csrf = login(client, world.admin_email)
    body = {
        "type": "manual_journal",
        "effective_date": "2026-10-18",
        "description": "调整 · 一次",
        "lines": [line("1012.01", "debit", "5.00"), line("5001.01", "credit", "5.00")],
    }
    headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "create-once"}
    first = client.post(f"/api/v1/books/{world.book_id}/transactions", json=body, headers=headers)
    second = client.post(f"/api/v1/books/{world.book_id}/transactions", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert second.headers["idempotent-replayed"] == "true"
    entries = client.get(f"/api/v1/books/{world.book_id}/journal-entries").json()["data"]
    assert len(entries) == 1
