from datetime import date

from sqlalchemy.orm import Session

from app.api.records import page_records
from app.enums import UserRole
from app.models import User, Workspace
from app.schemas import ExpenseCreate, MoneyInput
from app.services.accounting import create_expense


def test_record_pages_reach_all_rows_and_filter_expenses_by_user(
    db_session: Session, workspace: Workspace
) -> None:
    alice = User(
        workspace_id=workspace.id,
        username="alice",
        email="alice@example.com",
        display_name="alice",
        password_hash="unused",
        role=UserRole.BOOKKEEPER,
    )
    bob = User(
        workspace_id=workspace.id,
        username="bob",
        email="bob@example.com",
        display_name="bob",
        password_hash="unused",
        role=UserRole.BOOKKEEPER,
    )
    db_session.add_all([alice, bob])
    db_session.flush()

    for index in range(1, 126):
        create_expense(
            db_session,
            workspace,
            ExpenseCreate(
                accounting_date=date(2026, 8, 1 + (index % 28)),
                description=f"expense-{index}",
                category_name="其他支出",
                cost=MoneyInput(currency="CNY", amount="1"),
                cash=MoneyInput(currency="CNY", amount="1"),
            ),
            actor_id=alice.id if index % 2 else bob.id,
        )

    first = page_records(
        user=alice,
        db=db_session,
        record_type="expense",
        limit=100,
        offset=0,
    )
    second = page_records(
        user=alice,
        db=db_session,
        record_type="expense",
        limit=100,
        offset=100,
    )
    assert first.total == 125
    assert first.total_amount_cny == "125.00"
    assert len(first.items) == 100
    assert len(second.items) == 25
    assert {record.id for record in first.items}.isdisjoint(record.id for record in second.items)

    alice_only = page_records(
        user=alice,
        db=db_session,
        record_type="expense",
        created_by_user_id=alice.id,
        limit=100,
        offset=0,
    )
    assert alice_only.total == 63
    assert alice_only.total_amount_cny == "63.00"
    assert {record.created_by_username for record in alice_only.items} == {"alice"}
