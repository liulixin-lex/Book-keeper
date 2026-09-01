from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.records import add_income_batch, delete_records_batch
from app.enums import AmountRole, UserRole
from app.models import AuditEvent, BusinessRecord, JournalEntry, User, Workspace
from app.schemas import (
    ExpenseCreate,
    ExpenseUpdate,
    IncomeBatchCreate,
    IncomeCreate,
    IncomeUpdate,
    MoneyInput,
    RecordBatchDelete,
    RefundCreate,
)
from app.services.accounting import (
    AccountingError,
    create_expense,
    create_income,
    create_refund,
    update_expense,
    update_income,
)


def _bookkeeper(db: Session, workspace: Workspace) -> User:
    user = User(
        workspace_id=workspace.id,
        username="record-editor",
        email="record-editor@example.test",
        display_name="Record Editor",
        password_hash="unused",
        role=UserRole.BOOKKEEPER,
    )
    db.add(user)
    db.commit()
    return user


def test_edit_income_rebuilds_amounts_and_journal_in_place(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    original = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 31),
            description="Original income",
            gross=MoneyInput(currency="CNY", amount="100"),
            fee=MoneyInput(currency="CNY", amount="5"),
            category_id="test-category-income-main",
        ),
        actor_id=user.id,
    )
    original_entry_id = original.posted_entry_id
    original_version = original.version

    updated = update_income(
        db_session,
        workspace,
        original,
        IncomeUpdate(
            expected_version=original_version,
            accounting_date=date(2026, 9, 1),
            description="Updated income",
            gross=MoneyInput(currency="CNY", amount="200"),
            fee=MoneyInput(currency="CNY", amount="6"),
            category_id="test-category-income-other",
        ),
        actor_id=user.id,
    )

    assert updated.id == original.id
    assert updated.version == original_version + 1
    assert updated.accounting_date == date(2026, 9, 1)
    assert updated.category_id == "test-category-income-other"
    assert updated.posted_entry_id != original_entry_id
    assert db_session.get(JournalEntry, original_entry_id) is None
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 1
    amounts = {str(item.role): item.amount_cny_e8 for item in updated.amounts}
    assert amounts[str(AmountRole.GROSS)] == 20_000_000_000
    assert amounts[str(AmountRole.FEE)] == 600_000_000
    assert amounts[str(AmountRole.CASH)] == 19_400_000_000
    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.entity_id == updated.id,
            AuditEvent.action == "record.update",
        )
    )
    assert audit is not None
    assert audit.before_json["description"] == "Original income"
    assert audit.after_json["description"] == "Updated income"


def test_edit_expense_rebuilds_cash_and_fee(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    original = create_expense(
        db_session,
        workspace,
        ExpenseCreate(
            accounting_date=date(2026, 8, 31),
            description="Original expense",
            cost=MoneyInput(currency="CNY", amount="20"),
            cash=MoneyInput(currency="CNY", amount="20"),
            category_id="test-category-cloud",
        ),
        actor_id=user.id,
    )

    updated = update_expense(
        db_session,
        workspace,
        original,
        ExpenseUpdate(
            expected_version=original.version,
            accounting_date=date(2026, 9, 1),
            description="Updated expense",
            cost=MoneyInput(currency="CNY", amount="30"),
            fee=MoneyInput(currency="CNY", amount="2"),
            cash=MoneyInput(currency="CNY", amount="32"),
            category_id="test-category-expense-other",
        ),
        actor_id=user.id,
    )

    amounts = {str(item.role): item.amount_cny_e8 for item in updated.amounts}
    assert amounts[str(AmountRole.COST)] == 3_000_000_000
    assert amounts[str(AmountRole.FEE)] == 200_000_000
    assert amounts[str(AmountRole.CASH)] == 3_200_000_000


def test_linked_income_cannot_be_edited(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    original = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 30),
            description="Income with refund",
            gross=MoneyInput(currency="CNY", amount="100"),
            category_id="test-category-income-main",
        ),
        actor_id=user.id,
    )
    create_refund(
        db_session,
        workspace,
        RefundCreate(
            original_record_id=original.id,
            accounting_date=date(2026, 8, 31),
            refund=MoneyInput(currency="CNY", amount="10"),
        ),
        actor_id=user.id,
    )

    with pytest.raises(AccountingError, match="退款或冲正关联"):
        update_income(
            db_session,
            workspace,
            original,
            IncomeUpdate(
                expected_version=original.version,
                accounting_date=date(2026, 9, 1),
                description="Should not update",
                gross=MoneyInput(currency="CNY", amount="90"),
                category_id="test-category-income-main",
            ),
            actor_id=user.id,
        )


def test_batch_create_is_atomic_and_batch_delete_removes_selected_records(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    duplicate_payload = IncomeBatchCreate(
        items=[
            IncomeCreate(
                accounting_date=date(2026, 9, 1),
                description=f"Duplicate {index}",
                channel="xorpay",
                external_id="same-order",
                gross=MoneyInput(currency="CNY", amount="10"),
                category_id="test-category-income-main",
            )
            for index in range(2)
        ]
    )
    with pytest.raises(HTTPException) as exc_info:
        add_income_batch(duplicate_payload, user, None, db_session)
    assert exc_info.value.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0

    created = add_income_batch(
        IncomeBatchCreate(
            items=[
                IncomeCreate(
                    accounting_date=date(2026, 9, 1),
                    description=f"Batch income {index}",
                    gross=MoneyInput(currency="CNY", amount=str(index * 10)),
                    category_id="test-category-income-main",
                )
                for index in (1, 2)
            ]
        ),
        user,
        None,
        db_session,
    )
    result = delete_records_batch(
        RecordBatchDelete(record_ids=[item.id for item in created]),
        user,
        None,
        db_session,
    )
    assert result.deleted_count == 2
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0
