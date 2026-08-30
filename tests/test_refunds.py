from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import AmountRole, RecordType
from app.models import JournalEntry, Workspace
from app.schemas import IncomeCreate, MoneyInput, RefundCreate
from app.services.accounting import create_income, create_refund, reverse_record
from app.services.reports import overview


def _income(db: Session, workspace: Workspace):
    return create_income(
        db,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 20),
            description="Stripe payment",
            channel="stripe",
            external_id="pi_refund_test",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="5"),
            category_id="test-category-income-main",
        ),
    )


def test_partial_refund_reduces_revenue_fee_and_cash(
    db_session: Session, workspace: Workspace
) -> None:
    income = _income(db_session, workspace)
    refund = create_refund(
        db_session,
        workspace,
        RefundCreate(
            original_record_id=income.id,
            accounting_date=date(2026, 8, 21),
            refund=MoneyInput(currency="CNY", amount="40"),
            fee_refund=MoneyInput(currency="CNY", amount="2"),
            external_id="re_1",
        ),
    )
    assert refund.record_type == RecordType.REFUND
    amounts = {str(item.role): item.amount_cny_e8 for item in refund.amounts}
    assert amounts[AmountRole.REFUND] == 4_000_000_000
    assert amounts[AmountRole.FEE] == 200_000_000
    assert amounts[AmountRole.CASH] == 3_800_000_000
    entry = db_session.scalar(select(JournalEntry).where(JournalEntry.record_id == refund.id))
    assert entry is not None
    assert sum(line.debit_cny_e8 for line in entry.lines) == sum(
        line.credit_cny_e8 for line in entry.lines
    )

    report = overview(db_session, workspace, date(2026, 8, 20), date(2026, 8, 21))
    assert report.gross_revenue == "100.00"
    assert report.channel_fees == "3.00"
    assert report.net_revenue == "57.00"
    assert report.operating_net == "57.00"
    assert report.cash_out == "38.00"

    reverse_record(db_session, refund, reason="refund entered twice")
    restored = overview(db_session, workspace, date(2026, 8, 20), date(2026, 8, 21))
    assert restored.channel_fees == "5.00"
    assert restored.net_revenue == "95.00"
    assert restored.operating_net == "95.00"
    assert restored.cash_out == "0.00"


def test_cumulative_refund_cannot_exceed_original_income(
    db_session: Session, workspace: Workspace
) -> None:
    income = _income(db_session, workspace)
    create_refund(
        db_session,
        workspace,
        RefundCreate(
            original_record_id=income.id,
            accounting_date=date(2026, 8, 21),
            refund=MoneyInput(currency="CNY", amount="80"),
            external_id="re_2",
        ),
    )
    with pytest.raises(ValueError, match="Cumulative refunds"):
        create_refund(
            db_session,
            workspace,
            RefundCreate(
                original_record_id=income.id,
                accounting_date=date(2026, 8, 22),
                refund=MoneyInput(currency="CNY", amount="21"),
                external_id="re_3",
            ),
        )


def test_income_with_active_refund_requires_child_first_reversal(
    db_session: Session, workspace: Workspace
) -> None:
    income = _income(db_session, workspace)
    refund = create_refund(
        db_session,
        workspace,
        RefundCreate(
            original_record_id=income.id,
            accounting_date=date(2026, 8, 21),
            refund=MoneyInput(currency="CNY", amount="40"),
            external_id="re_child_first",
        ),
    )

    with pytest.raises(ValueError, match="active refunds"):
        reverse_record(db_session, income, reason="wrong income")

    reverse_record(db_session, refund, reason="wrong refund")
    reversal = reverse_record(db_session, income, reason="wrong income")
    assert reversal.record_type == RecordType.INCOME
