from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    BusinessRecord,
    Counterparty,
    JournalEntry,
    JournalLine,
    MoneyComponent,
    RecordLink,
    Workspace,
)
from app.schemas import IncomeCreate, MoneyInput, RefundCreate
from app.services.accounting import create_income, create_refund, delete_record_graph
from app.services.reports import grouped_ledger_report, overview


def test_deleting_income_removes_linked_refund_and_ledger_data(
    db_session: Session, workspace: Workspace
) -> None:
    counterparty = Counterparty(
        workspace_id=workspace.id,
        name="Deletion linkage customer",
        roles_json=["customer"],
        metadata_json={},
    )
    db_session.add(counterparty)
    db_session.flush()
    income = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 28),
            description="Income to delete",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="5"),
            counterparty_id=counterparty.id,
        ),
    )
    create_refund(
        db_session,
        workspace,
        RefundCreate(
            original_record_id=income.id,
            accounting_date=date(2026, 8, 29),
            refund=MoneyInput(currency="CNY", amount="20"),
        ),
    )

    assert grouped_ledger_report(
        db_session, workspace, date(2026, 8, 28), date(2026, 8, 29), "category"
    )
    assert grouped_ledger_report(
        db_session, workspace, date(2026, 8, 28), date(2026, 8, 29), "provider"
    )

    assert delete_record_graph(db_session, income, actor_id="test-user") == 2
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0
    assert db_session.scalar(select(func.count()).select_from(MoneyComponent)) == 0
    assert db_session.scalar(select(func.count()).select_from(RecordLink)) == 0
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 0
    assert db_session.scalar(select(func.count()).select_from(JournalLine)) == 0

    report = overview(db_session, workspace, date(2026, 8, 28), date(2026, 8, 29))
    assert report.gross_revenue == "0.00"
    assert report.cash_in == "0.00"
    assert report.cash_out == "0.00"
    assert (
        grouped_ledger_report(
            db_session, workspace, date(2026, 8, 28), date(2026, 8, 29), "category"
        )
        == []
    )
    assert (
        grouped_ledger_report(
            db_session,
            workspace,
            date(2026, 8, 28),
            date(2026, 8, 29),
            "provider",
        )
        == []
    )
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == income.id,
            AuditEvent.action == "record.delete",
        )
    )
    assert audit is not None
    assert audit.before_json["deleted_record_count"] == 2
