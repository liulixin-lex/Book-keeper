from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.subscriptions import (
    SubscriptionCharge,
    SubscriptionCreate,
    SubscriptionUpdate,
    add_subscription,
    add_subscription_charge,
    update_subscription,
)
from app.enums import RecordType, UserRole
from app.models import Category, Counterparty, User, Workspace
from app.schemas import MoneyInput


def test_subscription_contract_and_charge(db_session: Session, workspace: Workspace) -> None:
    user = User(
        workspace_id=workspace.id,
        username="Admin",
        email="subscription-admin@example.com",
        display_name="Admin",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "软件订阅",
        )
    )
    assert category is not None
    vendor = Counterparty(
        workspace_id=workspace.id,
        name="Example SaaS",
        roles_json=["subscription_vendor"],
        expense_category_id=category.id,
        metadata_json={},
    )
    db_session.add_all([user, vendor])
    db_session.commit()

    contract = add_subscription(
        SubscriptionCreate(
            name="Example plan",
            counterparty_id=vendor.id,
            billing_cycle="monthly",
            currency="USD",
            expected_amount="20",
            renewal_date=date(2026, 9, 1),
            auto_renew=True,
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert contract.expected_amount == "20.00"
    updated = update_subscription(
        contract.id,
        SubscriptionUpdate(expected_version=contract.version, expected_amount="22"),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert updated.expected_amount == "22.00"
    assert updated.version == contract.version + 1

    charge = add_subscription_charge(
        contract.id,
        SubscriptionCharge(
            accounting_date=date(2026, 8, 28),
            cost=MoneyInput(currency="USD", amount="20", amount_cny="145.50"),
            cash=MoneyInput(currency="USD", amount="20", amount_cny="145.50"),
            external_id="invoice-1",
            service_period_start=date(2026, 8, 1),
            service_period_end=date(2026, 8, 31),
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
        None,
    )
    assert charge.record_type == RecordType.EXPENSE
    assert charge.metadata["subscription_contract_id"] == contract.id
    assert {item.role: item.amount_cny for item in charge.amounts} == {
        "cost": "145.50",
        "cash": "145.50",
    }
