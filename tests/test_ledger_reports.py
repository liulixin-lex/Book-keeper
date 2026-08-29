from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.amounts import to_e12
from app.enums import AccountType, JournalStatus, UserRole
from app.models import Account, JournalEntry, User, Workspace
from app.schemas import ExpenseCreate, IncomeCreate, MoneyInput
from app.services.accounting import create_expense, create_income
from app.services.fx import DisplayRate
from app.services.reports import (
    daily_report,
    dashboard_report,
    grouped_ledger_report,
    overview,
)


def test_report_amounts_come_from_posted_journal_lines(
    db_session: Session, workspace: Workspace
) -> None:
    income = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 28),
            description="Ledger source check",
            channel="stripe",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="5"),
            cash_received=True,
        ),
    )

    for component in income.amounts:
        component.amount_cny_e8 = 999_999_999_999
    db_session.flush()

    report = overview(db_session, workspace, date(2026, 8, 28), date(2026, 8, 28))
    assert report.gross_revenue == "100.00"
    assert report.channel_fees == "5.00"
    assert report.net_revenue == "95.00"
    assert report.operating_net == "95.00"
    assert report.cash_in == "95.00"
    assert report.posted_records == 1
    daily = daily_report(db_session, workspace, date(2026, 8, 28), date(2026, 8, 28))
    assert len(daily) == 1
    assert daily[0].gross_revenue == "100.00"
    assert daily[0].net_revenue == "95.00"
    grouped = grouped_ledger_report(
        db_session,
        workspace,
        date(2026, 8, 28),
        date(2026, 8, 28),
        "channel",
    )
    assert grouped == [
        {
            "group": "stripe",
            "gross_revenue": "100.00",
            "channel_fees": "5.00",
            "net_revenue": "95.00",
            "operating_expenses": "0.00",
            "operating_net": "95.00",
            "cash_in": "95.00",
            "cash_out": "0.00",
            "net_cash": "95.00",
        }
    ]


def test_report_ignores_non_posted_journal_entries(
    db_session: Session, workspace: Workspace
) -> None:
    income = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 28),
            description="Draft ledger entry check",
            channel="stripe",
            gross=MoneyInput(currency="CNY", amount="100"),
        ),
    )
    entry = db_session.get(JournalEntry, income.posted_entry_id)
    assert entry is not None
    entry.status = JournalStatus.DRAFT
    db_session.flush()

    report = overview(db_session, workspace, date(2026, 8, 28), date(2026, 8, 28))
    assert report.gross_revenue == "0.00"
    assert report.net_revenue == "0.00"
    assert report.posted_records == 0
    assert daily_report(db_session, workspace, date(2026, 8, 28), date(2026, 8, 28)) == []


def test_cash_in_includes_historical_income_posted_to_clearing(
    db_session: Session, workspace: Workspace
) -> None:
    record = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 28),
            description="Historical clearing income",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="5"),
        ),
    )
    clearing = Account(
        workspace_id=workspace.id,
        code="1012-test",
        name="Historical clearing",
        account_type=AccountType.ASSET,
        subtype="clearing",
        currency="CNY",
    )
    db_session.add(clearing)
    db_session.flush()
    entry = db_session.get(JournalEntry, record.posted_entry_id)
    assert entry is not None
    asset_line = next(line for line in entry.lines if line.debit_cny_e8 == 9_500_000_000)
    asset_line.account_id = clearing.id
    db_session.flush()

    report = overview(db_session, workspace, date(2026, 8, 28), date(2026, 8, 28))
    assert report.cash_in == "95.00"
    assert report.net_cash == "95.00"


def test_expense_cash_difference_is_never_reported_as_cash(
    db_session: Session, workspace: Workspace
) -> None:
    with pytest.raises(ValueError, match="cash must equal cost plus fee"):
        create_expense(
            db_session,
            workspace,
            ExpenseCreate(
                accounting_date=date(2026, 8, 28),
                description="Mismatched expense",
                category_name="其他支出",
                cost=MoneyInput(currency="CNY", amount="20"),
                cash=MoneyInput(currency="CNY", amount="15"),
            ),
        )
    db_session.rollback()

    report = overview(db_session, workspace, date(2026, 8, 28), date(2026, 8, 28))
    assert report.operating_expenses == "0.00"
    assert report.cash_out == "0.00"


def test_expense_breakdown_by_creator_matches_total(
    db_session: Session, workspace: Workspace
) -> None:
    alice = User(
        workspace_id=workspace.id,
        username="alice-report",
        email="alice-report@example.com",
        display_name="alice-report",
        password_hash="unused",
        role=UserRole.BOOKKEEPER,
    )
    bob = User(
        workspace_id=workspace.id,
        username="bob-report",
        email="bob-report@example.com",
        display_name="bob-report",
        password_hash="unused",
        role=UserRole.BOOKKEEPER,
    )
    db_session.add_all([alice, bob])
    db_session.flush()
    for owner, amount in ((alice, "40"), (bob, "60")):
        create_expense(
            db_session,
            workspace,
            ExpenseCreate(
                accounting_date=date(2026, 8, 29),
                description=f"{owner.username} expense",
                category_name="其他支出",
                cost=MoneyInput(currency="CNY", amount=amount),
                cash=MoneyInput(currency="CNY", amount=amount),
            ),
            actor_id=owner.id,
        )

    report = overview(db_session, workspace, date(2026, 8, 29), date(2026, 8, 29))
    assert report.operating_expenses == "100.00"
    assert {row.username: row.amount for row in report.expense_by_user} == {
        "alice-report": "40.00",
        "bob-report": "60.00",
    }


def test_dashboard_converts_every_report_surface_with_one_rate(
    db_session: Session, workspace: Workspace
) -> None:
    target_date = date(2026, 8, 29)
    create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=target_date,
            description="Converted income",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="10"),
        ),
    )
    create_expense(
        db_session,
        workspace,
        ExpenseCreate(
            accounting_date=target_date,
            description="Converted expense",
            category_name="其他支出",
            cost=MoneyInput(currency="CNY", amount="20"),
            cash=MoneyInput(currency="CNY", amount="20"),
        ),
    )
    now = datetime.now(UTC)

    report = dashboard_report(
        db_session,
        workspace,
        target_date,
        target_date,
        DisplayRate(
            currency="USD",
            cny_per_unit_e12=to_e12("2"),
            source="Frankfurter",
            effective_at=now,
            fetched_at=now,
            is_stale=False,
        ),
    )

    assert report.display_currency == "USD"
    assert report.rate.cny_per_unit == "2"
    assert report.overview.gross_revenue == "50.00"
    assert report.overview.channel_fees == "5.00"
    assert report.overview.net_revenue == "45.00"
    assert report.overview.operating_expenses == "10.00"
    assert report.overview.operating_net == "35.00"
    assert report.overview.cash_in == "45.00"
    assert report.overview.cash_out == "10.00"
    assert report.overview.net_cash == "35.00"
    assert report.overview.posted_records == 2
    assert report.overview.expense_by_user[0].amount == "10.00"
    assert len(report.daily) == 1
    assert report.daily[0].operating_net == "35.00"
    assert report.daily[0].net_cash == "35.00"
