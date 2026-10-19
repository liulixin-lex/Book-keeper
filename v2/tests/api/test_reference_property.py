from datetime import date, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bookkeeper.domain.scopes import ROLE_CAPS, Role
from bookkeeper.services import checks, transactions
from bookkeeper.services.context import Actor, RequestContext
from tests.api.conftest import login, write_headers


def _ctx(world) -> RequestContext:  # type: ignore[no-untyped-def]
    actor = Actor(type="user", user_id=world.admin_id, role=Role.OWNER, scopes=ROLE_CAPS[Role.OWNER])
    return RequestContext(actor=actor, channel="api", book_id=world.book_id)


postings = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=60),  # day offset → backdated and forward dates in any order
        st.integers(min_value=1, max_value=10**8),
        st.sampled_from(["5001.01", "5051", "5603.01", "5401.02"]),
        st.booleans(),  # reverse afterwards?
    ),
    min_size=1,
    max_size=8,
)


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(items=postings)
def test_property_balance_caches_match_lines(app, world, items) -> None:  # type: ignore[no-untyped-def]
    """P-08: after posts and reversals in random date order, caches equal a recomputation from lines."""
    base = date(2026, 8, 1)
    for offset, amount, other, do_reverse in items:
        with app.state.sessionmaker() as session, session.begin():
            ctx = _ctx(world)
            side = "credit" if other.startswith("50") else "debit"
            funds_side = "debit" if side == "credit" else "credit"
            amt = str(Decimal(amount) / 100)
            txn, _entry, _plan = transactions.create(
                session,
                ctx,
                {
                    "type": "manual_journal",
                    "effective_date": base + timedelta(days=offset),
                    "description": "调整 · 属性测试",
                    "lines": [
                        transactions.LineSpec("1012.01", funds_side, amt, "CNY"),
                        transactions.LineSpec(other, side, amt, "CNY"),
                    ],
                },
            )
            if do_reverse:
                transactions.delete(session, ctx, txn.id, "属性测试删除")
    with app.state.sessionmaker() as session, session.begin():
        run = checks.run_checks(
            session,
            _ctx(world),
            [
                "trial_balance_zero",
                "entries_balanced",
                "balances_cache",
                "daily_balances",
                "sequence_gaps",
                "hash_chain",
                "orphans",
            ],
        )
        assert run.status == "passed", run.summary


def test_counterparties_aliases_and_resolution(client, world) -> None:
    csrf = login(client, world.admin_email)
    created = client.post(
        f"/api/v1/books/{world.book_id}/counterparties",
        headers=write_headers(csrf),
        json={
            "name": "api.relay-a.example",
            "category": "upstream_site",
            "domains": ["https://api.relay-a.example/v1"],
            "aliases": ["示例站"],
        },
    )
    assert created.status_code == 201, created.text
    cp = created.json()["data"]
    assert cp["domains"] == ["api.relay-a.example"]
    client.post(
        f"/api/v1/books/{world.book_id}/counterparties/{cp['id']}/aliases",
        headers=write_headers(csrf),
        json={"pattern": "https://www.relay-a.net/", "match_type": "domain"},
    )
    account = client.post(
        f"/api/v1/books/{world.book_id}/counterparties/{cp['id']}/accounts",
        headers=write_headers(csrf),
        json={"label": "账号A", "identifier": "user@example.com"},
    )
    assert account.json()["data"]["identifier"] == "[redacted]"

    def resolve(text: str) -> list[dict]:  # type: ignore[type-arg]
        url = f"/api/v1/books/{world.book_id}/counterparties:resolve"
        return client.get(url, params={"text": text}).json()["data"]

    assert resolve("https://api.relay-a.example/v1/chat")[0]["name"] == "api.relay-a.example"
    assert resolve("relay-a.net")[0]["method"] == "domain"  # www. is the same site
    # Any other host is another site, even under the same domain: no suffix matching.
    assert resolve("x.relay-a.example") == [] and resolve("relay-a.example") == [] and resolve("sub.relay-a.net") == []
    assert resolve("示例站")[0]["method"] == "alias_exact"
    assert resolve("nothing.example") == []
    duplicate = client.post(
        f"/api/v1/books/{world.book_id}/counterparties",
        headers=write_headers(csrf),
        json={"name": "api.relay-a.example", "category": "upstream_site"},
    )
    assert duplicate.status_code == 409
    detail = client.get(f"/api/v1/books/{world.book_id}/counterparties/{cp['id']}").json()["data"]
    assert detail["accounts"][0]["label"] == "账号A"


def test_price_rules_and_credit_conversion(client, world) -> None:
    csrf = login(client, world.admin_email)
    rule = {
        "commodity": "UCR",
        "quote_commodity": "CNY",
        "rate": "1",
        "purpose": "conversion",
        "valid_from": "2026-05-01",
    }
    assert (
        client.post(
            f"/api/v1/books/{world.book_id}/commodity-price-rules", headers=write_headers(csrf), json=rule
        ).status_code
        == 201
    )
    overlap = client.post(
        f"/api/v1/books/{world.book_id}/commodity-price-rules",
        headers=write_headers(csrf),
        json=rule | {"valid_from": "2026-06-01", "rate": "1.1"},
    )
    assert overlap.status_code == 409
    body = {
        "type": "manual_journal",
        "effective_date": "2026-10-18",
        "description": "调整 · 额度换算",
        "lines": [
            {"account": "5401.01", "side": "debit", "amount": {"amount": "50", "commodity": "UCR"}},
            {"account": "1999", "side": "credit", "amount": {"amount": "50", "commodity": "UCR"}},
        ],
    }
    response = client.post(f"/api/v1/books/{world.book_id}/transactions", headers=write_headers(csrf), json=body)
    assert response.status_code == 201, response.text
    lines = response.json()["data"]["entries"][0]["lines"]
    assert lines[0]["base_amount"] == 5000 and lines[0]["fx_source"] == "price_rule"


def test_dimension_values_crud(client, world) -> None:
    csrf = login(client, world.admin_email)
    created = client.post(
        f"/api/v1/books/{world.book_id}/dimension-types/channel/values",
        headers=write_headers(csrf),
        json={"code": "taobao", "name": "淘宝"},
    )
    assert created.status_code == 201
    value = created.json()["data"]
    patched = client.patch(
        f"/api/v1/books/{world.book_id}/dimension-values/{value['id']}",
        headers=write_headers(csrf),
        json={"expected_version": 1, "is_active": False},
    )
    assert patched.json()["data"]["is_active"] is False
    body = {
        "type": "manual_journal",
        "effective_date": "2026-10-18",
        "description": "调整 · x",
        "lines": [
            {"account": "1012.01", "side": "debit", "amount": {"amount": "1", "commodity": "CNY"}},
            {
                "account": "5001.01",
                "side": "credit",
                "amount": {"amount": "1", "commodity": "CNY"},
                "dimensions": {"channel": "taobao"},
            },
        ],
    }
    inactive = client.post(f"/api/v1/books/{world.book_id}/transactions", headers=write_headers(csrf), json=body)
    assert inactive.status_code == 422 and "已停用" in inactive.json()["errors"][0]["message"]
    dims = client.get(f"/api/v1/books/{world.book_id}/dimensions").json()["data"]
    assert dims[0]["code"] == "channel" and len(dims[0]["values"]) == 9


def test_fx_fetch_job_stores_reference_rates(app, world, monkeypatch) -> None:
    from bookkeeper.db.models import FxRate
    from bookkeeper.fx_providers import frankfurter
    from bookkeeper.jobs import tasks

    calls: list[str] = []

    def fake(url: str):  # type: ignore[no-untyped-def]
        calls.append(url)
        base = url.split("base=")[1].split("&")[0]
        return {"amount": 1.0, "base": base, "date": "2026-10-16", "rates": {"CNY": 9.5127 if base == "GBP" else 7.1}}

    monkeypatch.setattr(frankfurter, "http_get_json", fake)
    with app.state.sessionmaker() as session, session.begin():
        result = tasks.fetch_fx_rates(session, {"date": "2026-10-18"})
    assert "GBP/CNY@2026-10-16" in result["stored"]
    assert all("symbols=CNY" in c for c in calls)
    with app.state.sessionmaker() as session:
        gbp = session.query(FxRate).filter_by(base="GBP", quote="CNY").one()
        assert gbp.rate == Decimal("9.5127") and gbp.source == "frankfurter" and gbp.rate_type == "reference"
