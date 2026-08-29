from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.amounts import to_e12
from app.api.catalog import (
    add_category,
    add_provider,
    delete_category,
    delete_fx_rate,
    delete_provider,
    edit_category,
    edit_provider,
)
from app.api.records import record_view
from app.enums import UserRole
from app.models import Account, AuditEvent, Category, Counterparty, FxRate, User, Workspace
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    ExpenseCreate,
    IncomeCreate,
    MoneyInput,
    ProviderCreate,
    ProviderUpdate,
)
from app.services.accounting import AccountingError, create_expense, create_income


def _user(db: Session, workspace: Workspace, email: str = "master-data@example.com") -> User:
    user = User(
        workspace_id=workspace.id,
        username="Master Data",
        email=email,
        display_name="Master Data",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    db.add(user)
    db.flush()
    return user


def _account(db: Session, workspace: Workspace, code: str) -> Account:
    account = db.scalar(
        select(Account).where(Account.workspace_id == workspace.id, Account.code == code)
    )
    assert account is not None
    return account


def test_category_crud_and_reference_protection(db_session: Session, workspace: Workspace) -> None:
    user = _user(db_session, workspace)
    revenue = _account(db_session, workspace, "5001")
    category = add_category(
        CategoryCreate(
            name="  定制收入  ",
            kind="income",
            account_id=revenue.id,
            is_active=False,
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert category.name == "定制收入"
    assert category.is_active is False

    category = edit_category(
        category.id,
        CategoryUpdate(name="定制主营收入", is_active=True),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert category.name == "定制主营收入"
    assert category.is_active is True

    expense_category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "其他支出",
        )
    )
    assert expense_category is not None
    provider = add_provider(
        ProviderCreate(
            name="收款服务商",
            expense_category_id=expense_category.id,
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    record = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 29),
            description="带完整主数据的收入",
            gross=MoneyInput(currency="CNY", amount="10"),
            category_id=category.id,
            counterparty_id=provider.id,
            post=False,
        ),
    )
    view = record_view(record)
    assert view.category_name == "定制主营收入"
    assert view.counterparty_id == provider.id
    assert view.counterparty_name == "收款服务商"

    with pytest.raises(HTTPException) as linked:
        delete_category(category.id, user, None, db_session)  # type: ignore[arg-type]
    assert linked.value.status_code == 409

    unused = add_category(
        CategoryCreate(name="临时收入", kind="income", account_id=revenue.id),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert delete_category(unused.id, user, None, db_session).status_code == 204  # type: ignore[arg-type]
    assert db_session.get(Category, unused.id) is None


def test_provider_crud_category_status_and_reference_protection(
    db_session: Session, workspace: Workspace
) -> None:
    user = _user(db_session, workspace, "provider@example.com")
    expense_category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "其他支出",
        )
    )
    cloud_category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "云服务",
        )
    )
    assert expense_category is not None
    assert cloud_category is not None
    provider = add_provider(
        ProviderCreate(
            name="  星海服务商  ",
            expense_category_id=expense_category.id,
            is_active=False,
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert provider.name == "星海服务商"
    assert provider.expense_category_name == "其他支出"
    assert provider.is_active is False

    provider = edit_provider(
        provider.id,
        ProviderUpdate(
            name="星海云服务",
            expense_category_id=cloud_category.id,
            is_active=True,
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert provider.name == "星海云服务"
    assert provider.expense_category_id == cloud_category.id
    assert provider.expense_category_name == "云服务"
    assert provider.is_active is True

    with pytest.raises(AccountingError, match="提供商设置的类别"):
        create_expense(
            db_session,
            workspace,
            ExpenseCreate(
                accounting_date=date(2026, 8, 29),
                description="类别不匹配的支出",
                cost=MoneyInput(currency="CNY", amount="12"),
                category_id=expense_category.id,
                counterparty_id=provider.id,
                post=False,
            ),
        )
    db_session.rollback()

    with pytest.raises(HTTPException) as linked_provider_category:
        delete_category(cloud_category.id, user, None, db_session)  # type: ignore[arg-type]
    assert linked_provider_category.value.status_code == 409

    category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "主营业务收入",
        )
    )
    assert category is not None
    create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 29),
            description="关联提供商",
            gross=MoneyInput(currency="CNY", amount="20"),
            category_id=category.id,
            counterparty_id=provider.id,
            post=False,
        ),
    )
    with pytest.raises(HTTPException) as linked:
        delete_provider(provider.id, user, None, db_session)  # type: ignore[arg-type]
    assert linked.value.status_code == 409

    unused = add_provider(
        ProviderCreate(
            name="临时提供商",
            expense_category_id=expense_category.id,
        ),
        user,
        None,  # type: ignore[arg-type]
        db_session,
    )
    assert delete_provider(unused.id, user, None, db_session).status_code == 204  # type: ignore[arg-type]
    assert db_session.get(Counterparty, unused.id) is None

    actions = set(
        db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.workspace_id == workspace.id,
                AuditEvent.entity_type.in_(("category", "provider")),
            )
        )
    )
    assert "provider.create" in actions
    assert "provider.update" in actions
    assert "provider.delete" in actions


def test_used_fx_rate_cannot_be_deleted(db_session: Session, workspace: Workspace) -> None:
    user = _user(db_session, workspace, "fx-reference@example.com")
    rate = FxRate(
        base_currency="USD",
        quote_currency="CNY",
        rate_e12=to_e12("7.2"),
        effective_at=datetime.now(UTC),
        source="manual",
        rate_type="manual_override",
    )
    db_session.add(rate)
    db_session.flush()
    category = db_session.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "主营业务收入",
        )
    )
    assert category is not None
    create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date=date(2026, 8, 29),
            description="外币收入",
            gross=MoneyInput(currency="USD", amount="10", fx_rate_id=rate.id),
            category_id=category.id,
            post=False,
        ),
    )

    with pytest.raises(HTTPException) as linked:
        delete_fx_rate(rate.id, user, None, db_session)  # type: ignore[arg-type]
    assert linked.value.status_code == 409
