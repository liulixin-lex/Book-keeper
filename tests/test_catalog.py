import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.catalog import add_category
from app.enums import AccountType, CategoryKind, UserRole
from app.models import Account, Category, User, Workspace
from app.schemas import CategoryCreate


def test_category_parent_must_belong_to_current_workspace(
    db_session: Session, workspace: Workspace
) -> None:
    user = User(
        workspace_id=workspace.id,
        username="Catalog tester",
        email="catalog@example.com",
        display_name="Catalog tester",
        password_hash="unused",
        role=UserRole.ADMIN,
    )
    other = Workspace(name="Other ledger", base_currency="CNY")
    db_session.add_all([user, other])
    db_session.flush()
    foreign_account = Account(
        workspace_id=other.id,
        code="9999",
        name="Foreign expense",
        account_type=AccountType.EXPENSE,
        is_active=True,
    )
    db_session.add(foreign_account)
    db_session.flush()
    foreign_parent = Category(
        workspace_id=other.id,
        account_id=foreign_account.id,
        name="Foreign parent",
        kind=CategoryKind.EXPENSE,
    )
    db_session.add(foreign_parent)
    db_session.flush()
    local_account = db_session.scalar(
        select(Account).where(
            Account.workspace_id == workspace.id,
            Account.account_type == AccountType.EXPENSE,
        )
    )
    assert local_account is not None

    with pytest.raises(HTTPException, match="父分类"):
        add_category(
            CategoryCreate(
                name="Invalid child",
                kind="expense",
                account_id=local_account.id,
                parent_id=foreign_parent.id,
            ),
            user,
            None,  # type: ignore[arg-type]
            db_session,
        )
