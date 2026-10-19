from bookkeeper.domain import chart, labels


def test_template_is_consistent() -> None:
    accounts = {a.code: a for a in chart.SMALL_ENTERPRISE_V1}
    assert len(accounts) == len(chart.SMALL_ENTERPRISE_V1)
    for account in chart.SMALL_ENTERPRISE_V1:
        assert chart.CODE_RE.match(account.code), account.code
        parent = chart.parent_code(account.code)
        if parent:
            assert accounts[parent].is_group, account.code
            assert accounts[parent].classification == account.classification
            assert chart.code_level(account.code) == 2
        assert account.role is None or account.role in chart.ROLES
        assert account.normal_side == chart.NORMAL_SIDE[account.classification]
        assert account.standard_code == account.code[:4]
        if account.role in chart.SYSTEM_ROLES:
            assert account.is_system, account.code
        assert not (account.is_group and account.role), "group accounts carry no role"
    for role in ("funds", "trading", "fx_gain_loss", "rounding", "opening_balance", "suspense"):
        assert sum(1 for a in chart.SMALL_ENTERPRISE_V1 if a.role == role) == 1, role


def test_taxonomy_matches_doc14() -> None:
    names = {a.code: a.name for a in chart.SMALL_ENTERPRISE_V1}
    assert names["1012.01"] == "资金账户"
    assert names["5401.03"] == "AI 服务订阅" and names["5401.04"] == "服务器与网络"
    assert [code for code, _ in chart.CHANNELS][:4] == ["liandong", "yunmao", "k16888", "stripe"]
    assert {t.code for t in chart.TRANSACTION_TYPES} == {
        "sale",
        "sale_refund",
        "credit_purchase",
        "expense",
        "purchase_refund",
        "transfer",
        "opening_balance",
        "manual_journal",
    }
    assert labels.ENUM_LABELS["transaction_status"]["reversed"] == "已删除"
