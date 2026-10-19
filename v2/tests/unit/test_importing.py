import io
import itertools
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bookkeeper.domain import matching
from bookkeeper.domain import rules as engine
from bookkeeper.domain.errors import DomainError
from bookkeeper.importers import PARSERS, sniff
from bookkeeper.importers.base import extract_face, parse_amount, parse_datetime

TZ = ZoneInfo("Asia/Shanghai")

ALIPAY = (
    "支付宝交易明细\n共2笔记录\n收入：0笔 0.00元\n支出：1笔 30.00元\n"
    "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注\n"
    "2026-10-03 08:00:00,数码电器,某云,a***@x.com,服务器续费,支出,30.00,余额,交易成功,2026100322001,M9,\n"
    "2026-10-04 08:00:00,其他,某店,b***@x.com,取消的订单,支出,9.90,余额,交易关闭,2026100422002,,\n"
)
STRIPE = (
    "id,Type,Source,Amount,Fee,Net,Currency,Created (UTC),Available On (UTC),Description\n"
    "txn_1,charge,ch_1,20.00,0.85,19.15,gbp,2026-10-05 23:30:00,2026-10-07 00:00:00,Order 1\n"
    "txn_2,payout,po_1,-19.15,0.00,-19.15,gbp,2026-10-08 01:00:00,2026-10-08 01:00:00,STRIPE PAYOUT\n"
)


def test_parsers_and_sniffing() -> None:
    assert sniff("bill.csv", ALIPAY.encode())[0] == "alipay_bill"
    assert sniff("export.csv", STRIPE.encode())[0] == "stripe_balance"
    alipay = PARSERS["alipay_bill"].parse(ALIPAY.encode("gbk"), "a.csv", {}, TZ)
    assert len(alipay.records) == 1 and len(alipay.skipped) == 1
    rec = alipay.records[0]
    assert (rec.direction, rec.amount, rec.external_id, rec.order_no) == (
        "out",
        Decimal("30.00"),
        "2026100322001",
        "M9",
    )
    assert alipay.summary.declared == {"in_count": 0, "in_amount": 0, "out_count": 1, "out_amount": Decimal("30.00")}
    stripe = PARSERS["stripe_balance"].parse(STRIPE.encode(), "s.csv", {}, TZ)
    charge, payout = stripe.records
    assert (charge.direction, charge.commodity, charge.fee_amount) == ("in", "GBP", Decimal("0.85"))
    assert charge.occurred_at.astimezone(TZ).date() == date(2026, 10, 6)  # UTC late evening → next Beijing day
    assert payout.direction == "neutral"


def test_generic_tabular_long_and_xlsx() -> None:
    from openpyxl import Workbook  # type: ignore[import-untyped]

    wb = Workbook()
    ws = wb.active
    ws.append(["时间", "方向", "金额", "对方", "说明", "卡密"])
    ws.append(["2026-10-01 09:00", "收入", 12.5, "A 店", "50R 兑换码", "ABCD-1234"])
    ws.append(["2026-10-01 10:00", "支出", "8", "B", "余额+50", ""])
    ws.append(["bad", "支出", "8", "B", "x", ""])
    buf = io.BytesIO()
    wb.save(buf)
    config = {
        "columns": {
            "datetime": "时间",
            "direction": "方向",
            "amount": "金额",
            "counterparty": "对方",
            "description": "说明",
            "code": "卡密",
        },
        "direction_values": {"收入": "in", "支出": "out"},
        "extract_face": True,
    }
    result = PARSERS["generic_tabular"].parse(buf.getvalue(), "t.xlsx", config, TZ)
    assert [r.direction for r in result.records] == ["in", "out"]
    assert result.records[0].amount == Decimal("12.5") and result.records[0].extracted["face"] == "50"
    assert result.records[0].extracted["code"]["last4"] == "1234" and result.records[0].raw["卡密"] == "***1234"
    assert result.records[1].extracted["face"] == "50"
    assert len(result.errors) == 1 and "时间" in result.errors[0].message
    odd = PARSERS["generic_tabular"].parse(
        "时间,方向,金额\n2026-10-01,其他,1\n".encode(),
        "x.csv",
        {"columns": {"datetime": "时间", "direction": "方向", "amount": "金额"}, "direction_values": {"收入": "in"}},
        TZ,
    )
    assert not odd.records and "direction_values" in odd.errors[0].message


def test_records_parser_and_helpers() -> None:
    data = json.dumps(
        [
            {
                "occurred_at": "2026-10-01T12:00:00+08:00",
                "direction": "in",
                "amount": "50",
                "commodity": "UCR",
                "extracted": {"code": "XYZ9"},
            },
            {"occurred_at": "2026-10-01 12:00", "direction": "in", "amount": 1.5},
            {"occurred_at": "2026-10-01 12:00", "direction": "sideways", "amount": "1"},
        ]
    ).encode()
    result = PARSERS["records"].parse(data, "r.json", {}, TZ)
    assert len(result.records) == 1 and result.records[0].extracted["code"]["last4"] == "XYZ9"
    assert [e.row_no for e in result.errors] == [2, 3]
    assert parse_amount("¥1,234.50元") == Decimal("1234.50") and parse_amount("/") is None
    assert parse_datetime("46286", TZ).date() == date(2026, 9, 21)
    assert extract_face("余额+100") == Decimal("100") and extract_face("Claude 20刀") == Decimal("20")
    assert extract_face("100R兑换码") == Decimal("100") and extract_face("会员") is None


def test_rule_conditions_actions_and_locks() -> None:
    facts = {
        "source": "ld",
        "direction": "out",
        "amount": Decimal("103"),
        "description": "100R兑换码（relay-b）",
        "counterparty_text": "ＡＢＣ 店",
        "time_of_day": "23:30",
        "weekday": 6,
        "extracted": {"face": "100"},
        "counterparty_candidates": ["relay-b.example"],
    }
    cond = {
        "all": [
            {"field": "description", "op": "regex", "value": r"(?P<face>\d+)R"},
            {"field": "counterparty_text", "op": "eq", "value": "abc店"},
            {"field": "amount", "op": "between", "value": ["100", "110"]},
            {"field": "time_of_day", "op": "time_between", "value": ["22:00", "02:00"]},
            {
                "any": [
                    {"field": "weekday", "op": "weekday_in", "value": [6, 7]},
                    {"field": "source", "op": "eq", "value": "x"},
                ]
            },
            {"not": {"field": "description", "op": "contains", "value": "测试"}},
            {"field": "extracted.face", "op": "approx", "value": {"value": "100", "tolerance": "1"}},
            {"field": "counterparty", "op": "alias_of", "value": "relay-b.example"},
        ]
    }
    engine.validate_condition(cond)
    hit, captures = engine.evaluate(cond, facts)
    assert hit and captures == {"face": "100"}
    assert engine.specificity(cond) == 0 + 10 + 5 + 5 + 1 + 0 + 5 + 9  # regex 0, eq 10, between 5…
    general = engine.RuleDef(
        "r1",
        "general",
        1,
        "classify",
        100,
        {"field": "direction", "op": "eq", "value": "out"},
        [{"type": "set_transaction_type", "value": "expense"}, {"type": "set_category", "value": "5602.99"}],
    )
    specific = engine.RuleDef(
        "r2",
        "relay-b",
        1,
        "classify",
        100,
        cond,
        [
            {"type": "set_transaction_type", "value": "credit_purchase"},
            {"type": "set_input", "name": "face", "value": {"amount": "{captures.face}", "commodity": "CNY"}},
            {"type": "set_counterparty", "value": "relay-b.example"},
        ],
    )
    out = engine.apply([specific, general], facts, {}, locked=["counterparty"])
    assert out.classification["type"] == "credit_purchase"  # the more specific rule runs last and wins
    assert out.classification["inputs"]["face"] == {"amount": "100", "commodity": "CNY"}
    assert "counterparty" not in out.classification
    assert out.trace[-1]["changes"][-1] == {"field": "counterparty", "skipped": "locked"}
    ignored = engine.apply(
        [
            engine.RuleDef(
                "r3",
                "noise",
                1,
                "normalize",
                1,
                {"field": "amount", "op": "lt", "value": "1000"},
                [{"type": "ignore", "reason": "gift"}],
            )
        ],
        facts,
        {},
    )
    assert ignored.ignored == "gift"
    with pytest.raises(DomainError):
        engine.validate_condition({"field": "nope", "op": "eq", "value": 1})
    with pytest.raises(DomainError):
        engine.validate_actions([{"type": "launch_rocket"}])


def brute_force(left: list[float], right: list[float], before: float, after: float, penalty: float) -> float:
    best = float("inf")
    n, m = len(left), len(right)
    for k in range(min(n, m) + 1):
        for li in itertools.combinations(range(n), k):
            for rj in itertools.permutations(range(m), k):
                gaps = [right[j] - left[i] for i, j in zip(li, rj, strict=True)]
                if all(-before <= g <= after for g in gaps):
                    best = min(best, sum(abs(g) for g in gaps) + penalty * (n + m - 2 * k))
    return best


@settings(max_examples=150, deadline=None)
@given(
    st.lists(st.integers(0, 300), min_size=0, max_size=5),
    st.lists(st.integers(0, 300), min_size=0, max_size=5),
    st.integers(0, 60),
    st.integers(1, 240),
    st.integers(1, 200),
)
def test_pairing_is_globally_optimal(left: list[int], right: list[int], before: int, after: int, penalty: int) -> None:
    lf, rf = sorted(float(x) for x in left), sorted(float(x) for x in right)
    pairs = matching.pair(lf, rf, before=before, after=after, penalty=penalty)
    assert all(-before <= g <= after for _i, _j, g in pairs)
    assert len({i for i, _j, _g in pairs}) == len(pairs) == len({j for _i, j, _g in pairs})
    assert matching.total_cost(pairs, len(lf), len(rf), penalty) == pytest.approx(
        brute_force(lf, rf, before, after, penalty)
    )


def test_score_and_decide() -> None:
    record = matching.Candidate("r", 5150, date(2026, 10, 10), "relay-a.example", "LD1")
    exact = matching.Candidate("t1", 5150, date(2026, 10, 10), "relay-a.example", "", "LD1")
    assert matching.score(record, exact, tolerance=1).method == "external_id"
    near = matching.Candidate("t2", 5150, date(2026, 10, 11), "relay-a", "")
    far = matching.Candidate("t3", 5100, date(2026, 10, 14), "other", "")
    ranked = sorted([matching.score(record, c, tolerance=100) for c in (near, far)], key=lambda s: -s.score)
    assert ranked[0].id == "t2" and matching.decide(ranked) in ("pending", "auto_accepted")
    assert matching.decide([]) == "none"


def test_card_shop_header_is_the_row_naming_most_columns() -> None:
    """Exports that open with a title and a summary block (which also mentions 订单) still find the order table."""
    csv = (
        "三平台订单汇总,,,,\n"
        "平台,保留订单（笔）,有效支出（元）,,\n"
        "16888,2,41.23,,\n"
        ",,,,\n"
        "订单时间,商品名称,实付金额,订单状态,订单号\n"
        "2026-09-22 23:01:16,成品号,1.23,已完成,FF1\n"
        "2026-09-26 16:21:27,Team 席位,40,已完成,FF2\n"
        "2026-09-27 10:00:00,Team 席位,25,已退款,FF3\n"
    )
    result = PARSERS["card_shop_orders"].parse(csv.encode(), "orders.csv", {}, ZoneInfo("Asia/Shanghai"))
    assert [(r.order_no, r.amount) for r in result.records] == [("FF1", Decimal("1.23")), ("FF2", Decimal("40"))]
    assert len(result.skipped) == 1 and not result.errors


def test_redeem_page_pdf() -> None:
    """A browser-printed 兑换码 page (synthetic fixture): the footer URL names the site, not links in the page."""
    pdf = (Path(__file__).parent.parent / "fixtures" / "redeem_page.pdf").read_bytes()
    result = PARSERS["redeem_page"].parse(pdf, "whatever.pdf", {}, ZoneInfo("Asia/Shanghai"))
    assert [(r.occurred_at.isoformat(), r.amount, r.reference, r.extracted["entry_kind"]) for r in result.records] == [
        ("2026-09-26T10:20:30+08:00", Decimal("20.00"), "DEMO-0003", "兑换"),
        ("2026-09-25T21:14:49+08:00", Decimal("100.00"), "DEMO-0002", "兑换"),
        ("2026-09-25T08:51:22+08:00", Decimal("50.00"), "DEMO-0001", "兑换"),
        ("2026-09-24T12:00:00+08:00", Decimal("5.00"), None, "管理员"),
    ]
    assert {r.counterparty_text for r in result.records} == {"relay-demo.example"}
    assert {r.commodity for r in result.records} == {"UCR"} and not result.errors
    with pytest.raises(Exception, match="需要 PDF"):
        PARSERS["redeem_page"].parse(b"date,amount\n", "x.csv", {}, ZoneInfo("Asia/Shanghai"))


def test_subset_summing_prefers_explaining_more_records() -> None:
    from bookkeeper.services.matching import subset_summing

    assert subset_summing([1000, 1000, 2000], 2000) == [0, 1]
    assert subset_summing([5000, 8, 10000], 15000) == [0, 2]  # a gift code in the day does not spoil the total
    assert subset_summing([5000, 8], 6000) is None
    assert subset_summing([1] * 25, 25) == list(range(25)) and subset_summing([1] * 25, 3) is None


def test_a_file_name_cut_short_names_the_one_site_it_can_be() -> None:
    from bookkeeper.importers.redeem import site_host

    no_url = [("余额充值（兑换）", "余额充值（兑换）")]
    assert site_host(no_url, "relay-b.exa（2）.pdf", ["relay-b.example", "relay-c.example"]) == "relay-b.example"
    assert (
        site_host(no_url, "relay-b.exa（2）.pdf", ["relay-b.example", "relay-b.examples"]) == "relay-b.exa"
    )  # two could be meant: no guess
    assert site_host(no_url, "relay-b.exa（2）.pdf", ["relay-c.example"]) == "relay-b.exa"  # none: stays as read
    assert (
        site_host(no_url, "relay-c.example.pdf", ["relay-c.example", "relay-c.examplex"]) == "relay-c.example"
    )  # a known host stays exact
    assert (
        site_host(no_url, "relay-e.example.pdf", ["www.relay-e.example"]) == "relay-e.example"
    )  # www. is the same site
    footer = [("x", "https://relay-b.exa/redeem                      1/1")]
    assert (
        site_host(footer, "relay-b.example.pdf", ["relay-b.example"]) == "relay-b.exa"
    )  # the page's own URL is taken exactly


def test_an_ai_read_page_without_a_site_takes_the_known_site_its_file_is_named_after() -> None:
    from bookkeeper.services.ai_extract import _records

    row = dict.fromkeys(("currency", "fee", "quantity", "face", "order_no", "status", "counterparty", "description"))
    row |= {"occurred_at": "2026-09-14 10:00:00", "direction": "in", "amount": "100"}

    def party(name: str, known: list[str], site: str | None = None) -> str | None:
        return _records(name, {"site": site, "records": [row]}, "UCR", known)[0]["counterparty"]

    assert (
        party("relay-b.exa（2）.pdf", ["relay-b.example", "relay-c.example"]) == "relay-b.example"
    )  # an image-only print, name cut short
    assert party("relay-b.exa（2）.pdf", ["relay-b.example", "relay-b.examples"]) is None  # ambiguous: no guess
    assert party("unknown.site（1）.pdf", ["relay-b.example"]) is None  # never an unknown host from a file name
    assert party("IMG_0042.png", ["relay-b.example"]) is None
    assert (
        party("relay-b.exa（2）.pdf", ["relay-b.example"], site="relay-b.exa") == "relay-b.exa"
    )  # what the page shows is kept exactly
