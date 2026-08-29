from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.records import add_income
from app.api.subscriptions import SubscriptionCharge, add_subscription_charge
from app.enums import UserRole
from app.models import (
    BusinessRecord,
    Category,
    Counterparty,
    IdempotencyRecord,
    SubscriptionContract,
    User,
    Workspace,
)
from app.schemas import IncomeCreate, MoneyInput
from app.services.idempotency import commit_result


def _user(db: Session, workspace: Workspace) -> User:
    user = User(
        workspace_id=workspace.id,
        username="Idempotency tester",
        email="idempotency@example.com",
        display_name="Idempotency tester",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.commit()
    return user


def _income_payload(*, description: str = "Stripe sale") -> IncomeCreate:
    return IncomeCreate(
        accounting_date=date(2026, 8, 28),
        description=description,
        channel="stripe",
        gross=MoneyInput(currency="CNY", amount="100"),
        fee=MoneyInput(currency="CNY", amount="5"),
    )


def _fail_commit() -> None:
    raise IntegrityError("forced idempotency conflict", {}, RuntimeError("forced"))


def test_record_creation_and_idempotency_result_commit_once(
    db_session: Session, workspace: Workspace
) -> None:
    user = _user(db_session, workspace)

    first = add_income(_income_payload(), user, None, db_session, "income-key")  # type: ignore[arg-type]
    replay = add_income(_income_payload(), user, None, db_session, "income-key")  # type: ignore[arg-type]

    assert replay.id == first.id
    assert db_session.scalar(select(func.count(BusinessRecord.id))) == 1
    assert db_session.scalar(select(func.count(IdempotencyRecord.id))) == 1


def test_concurrent_idempotency_winner_is_replayed_and_loser_is_rolled_back(
    db_session: Session, workspace: Workspace
) -> None:
    user = _user(db_session, workspace)
    winner_response = {"record_id": "winner"}
    db_session.add(
        IdempotencyRecord(
            workspace_id=workspace.id,
            actor_id=user.id,
            operation="records.income",
            idempotency_key="race-key",
            request_hash="same-digest",
            response_json=winner_response,
            status_code=201,
        )
    )
    db_session.commit()

    loser_business_data = Counterparty(
        workspace_id=workspace.id,
        name="Uncommitted loser",
        roles_json=["customer"],
        metadata_json={},
    )
    db_session.add(loser_business_data)
    replay = commit_result(
        db_session,
        user,
        "records.income",
        "race-key",
        "same-digest",
        {"record_id": "loser"},
        201,
    )

    assert replay == winner_response
    assert (
        db_session.scalar(select(Counterparty).where(Counterparty.name == "Uncommitted loser"))
        is None
    )
    assert db_session.scalar(select(func.count(IdempotencyRecord.id))) == 1


def test_record_commit_conflict_rolls_back_business_data_and_key(
    db_session: Session,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user(db_session, workspace)
    monkeypatch.setattr(db_session, "commit", _fail_commit)

    with pytest.raises(HTTPException) as exc_info:
        add_income(_income_payload(), user, None, db_session, "income-key")  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert db_session.scalar(select(func.count(BusinessRecord.id))) == 0
    assert db_session.scalar(select(func.count(IdempotencyRecord.id))) == 0


def test_subscription_charge_conflict_rolls_back_business_data_and_key(
    db_session: Session,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _user(db_session, workspace)
    category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "软件订阅",
        )
    )
    assert category is not None
    vendor = Counterparty(
        workspace_id=workspace.id,
        name="Subscription vendor",
        roles_json=["subscription_vendor"],
        expense_category_id=category.id,
        metadata_json={},
    )
    db_session.add(vendor)
    db_session.flush()
    contract = SubscriptionContract(
        workspace_id=workspace.id,
        counterparty_id=vendor.id,
        name="Monthly plan",
        billing_cycle="monthly",
        currency="CNY",
    )
    db_session.add(contract)
    db_session.commit()
    monkeypatch.setattr(db_session, "commit", _fail_commit)

    with pytest.raises(HTTPException) as exc_info:
        add_subscription_charge(
            contract.id,
            SubscriptionCharge(
                accounting_date=date(2026, 8, 28),
                cost=MoneyInput(currency="CNY", amount="50"),
            ),
            user,
            None,  # type: ignore[arg-type]
            db_session,
            "subscription-key",
        )

    assert exc_info.value.status_code == 409
    assert db_session.scalar(select(func.count(BusinessRecord.id))) == 0
    assert db_session.scalar(select(func.count(IdempotencyRecord.id))) == 0
