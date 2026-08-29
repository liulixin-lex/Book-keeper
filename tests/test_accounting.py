from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.amounts import to_e8
from app.enums import AmountRole, RecordStatus
from app.models import Account, FxRate, JournalEntry, MoneyComponent, Workspace
from app.schemas import ExpenseCreate, IncomeCreate, MoneyInput, TopupCreate
from app.services.accounting import (
    AccountingError,
    create_expense,
    create_income,
    create_topup,
    resolve_money,
    reverse_record,
)
from app.services.reports import overview


def test_income_posts_balanced_gross_fee_and_net(db_session: Session, workspace: Workspace) -> None:
    record = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 2),
            description="Stripe payment",
            channel="Stripe",
            external_id="payment-1",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="GBP", amount="0.74", amount_cny="6.79"),
        ),
    )
    assert record.status == RecordStatus.POSTED
    entry = db_session.get(JournalEntry, record.posted_entry_id)
    assert entry is not None
    assert sum(line.debit_cny_e8 for line in entry.lines) == to_e8("100")
    assert sum(line.credit_cny_e8 for line in entry.lines) == to_e8("100")
    amounts = {component.role: component.amount_cny_e8 for component in record.amounts}
    assert amounts[AmountRole.NET] == to_e8("93.21")
    fee = next(component for component in record.amounts if component.role == AmountRole.FEE)
    assert fee.fx_rate_id is not None
    assert db_session.get(FxRate, fee.fx_rate_id) is not None


def test_money_rejects_inconsistent_cny_and_fx_values(db_session: Session) -> None:
    with pytest.raises(AccountingError, match="must equal"):
        resolve_money(
            db_session,
            MoneyInput(currency="CNY", amount="100", amount_cny="1"),
            effective_date=date(2026, 8, 28),
        )

    snapshot = FxRate(
        base_currency="USD",
        quote_currency="CNY",
        rate_e12=7_200_000_000_000,
        effective_at=datetime(2026, 8, 28, tzinfo=UTC),
        source="test",
        rate_type="test",
    )
    db_session.add(snapshot)
    db_session.flush()
    with pytest.raises(AccountingError, match="does not match"):
        resolve_money(
            db_session,
            MoneyInput(
                currency="USD",
                amount="100",
                amount_cny="1",
                fx_rate_id=snapshot.id,
            ),
            effective_date=date(2026, 8, 28),
        )


def test_inline_fx_rate_is_persisted_as_transaction_snapshot(db_session: Session) -> None:
    money = resolve_money(
        db_session,
        MoneyInput(currency="USD", amount="10", fx_rate="7.2"),
        effective_date=date(2026, 8, 28),
    )
    assert money.amount_cny_e8 == to_e8("72")
    assert money.fx_rate_id is not None
    snapshot = db_session.get(FxRate, money.fx_rate_id)
    assert snapshot is not None
    assert snapshot.rate_e12 == 7_200_000_000_000
    assert snapshot.effective_at.date() == date(2026, 8, 28)


def test_expense_rejects_cost_cash_difference(db_session: Session, workspace: Workspace) -> None:
    with pytest.raises(AccountingError, match="cash must equal cost plus fee"):
        create_expense(
            db_session,
            workspace,
            ExpenseCreate(
                accounting_date=date(2026, 6, 30),
                description="Cloud bill",
                category_name="云服务",
                cost=MoneyInput(currency="CNY", amount="452.8"),
                cash=MoneyInput(currency="CNY", amount="392.8"),
            ),
        )
    db_session.rollback()
    report = overview(db_session, workspace, date(2026, 6, 1), date(2026, 6, 30))
    assert report.operating_expenses == "0.00"
    assert report.cash_out == "0.00"


def test_expense_fee_is_posted_separately_and_included_in_cash_out(
    db_session: Session, workspace: Workspace
) -> None:
    record = create_expense(
        db_session,
        workspace,
        ExpenseCreate(
            accounting_date=date(2026, 8, 29),
            description="Service expense with fee",
            category_name="其他支出",
            cost=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="3"),
            cash=MoneyInput(currency="CNY", amount="103"),
        ),
    )

    amounts = {component.role: component.amount_cny_e8 for component in record.amounts}
    assert amounts[AmountRole.COST] == to_e8("100")
    assert amounts[AmountRole.FEE] == to_e8("3")
    assert amounts[AmountRole.CASH] == to_e8("103")

    entry = db_session.get(JournalEntry, record.posted_entry_id)
    assert entry is not None
    assert sum(line.debit_cny_e8 for line in entry.lines) == to_e8("103")
    assert sum(line.credit_cny_e8 for line in entry.lines) == to_e8("103")
    system_funds = db_session.scalar(
        select(Account).where(Account.workspace_id == workspace.id, Account.code == "1002")
    )
    assert system_funds is not None
    assert system_funds.name == "银行存款"
    assert record.payment_account_id is None
    assert any(
        line.account_id == system_funds.id and line.credit_cny_e8 == to_e8("103")
        for line in entry.lines
    )

    report = overview(db_session, workspace, date(2026, 8, 29), date(2026, 8, 29))
    assert report.channel_fees == "0.00"
    assert report.operating_expenses == "103.00"
    assert report.cash_out == "103.00"


def test_topup_is_cost_and_internal_credit(db_session: Session, workspace: Workspace) -> None:
    record = create_topup(
        db_session,
        workspace,
        TopupCreate(
            accounting_date=date(2026, 8, 27),
            upstream_name="example-upstream",
            amount_cny="47",
        ),
    )
    credit = db_session.scalar(
        select(MoneyComponent).where(
            MoneyComponent.record_id == record.id,
            MoneyComponent.role == AmountRole.CREDITED_VALUE,
        )
    )
    assert credit is not None
    assert credit.currency == "UPSTREAM_CREDIT"
    assert credit.amount_e8 == to_e8("47")
    assert record.record_type == "expense"
    report = overview(db_session, workspace, date(2026, 8, 27), date(2026, 8, 27))
    assert report.operating_expenses == "47.00"
    assert report.cash_out == "47.00"


def test_reversal_offsets_original_record(db_session: Session, workspace: Workspace) -> None:
    original = create_expense(
        db_session,
        workspace,
        ExpenseCreate(
            accounting_date=date(2026, 8, 1),
            description="Temporary expense",
            category_name="其他支出",
            cost=MoneyInput(currency="CNY", amount="20"),
            cash=MoneyInput(currency="CNY", amount="20"),
        ),
    )
    reversal = reverse_record(db_session, original, reason="duplicate")
    assert original.status == RecordStatus.REVERSED
    assert reversal.status == RecordStatus.POSTED
    report = overview(db_session, workspace, date(2026, 8, 1), date(2026, 8, 1))
    assert report.operating_expenses == "0.00"
    assert report.cash_out == "0.00"


def test_duplicate_external_id_is_rejected(db_session: Session, workspace: Workspace) -> None:
    payload = IncomeCreate(
        accounting_date=date(2026, 8, 2),
        description="Duplicate test",
        channel="Stripe",
        external_id="same-id",
        gross=MoneyInput(currency="CNY", amount="10"),
    )
    create_income(db_session, workspace, payload)
    with pytest.raises(ValueError):
        create_income(db_session, workspace, payload)
