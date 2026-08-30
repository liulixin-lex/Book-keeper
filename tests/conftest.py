from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.enums import CategoryKind
from app.models import Account, Category, Workspace
from app.services.seed import seed_defaults

TEST_CATEGORY_SEEDS = (
    ("test-category-income-main", "主营业务收入", CategoryKind.INCOME, "5001"),
    ("test-category-income-other", "其他业务收入", CategoryKind.INCOME, "5051"),
    ("test-category-upstream", "上游采购", CategoryKind.EXPENSE, "5401"),
    ("test-category-account", "账号采购", CategoryKind.EXPENSE, "5401"),
    ("test-category-cloud", "云服务", CategoryKind.EXPENSE, "5602"),
    ("test-category-subscription", "软件订阅", CategoryKind.EXPENSE, "5602"),
    ("test-category-fee", "交易手续费", CategoryKind.EXPENSE, "5603"),
    ("test-category-expense-other", "其他支出", CategoryKind.EXPENSE, "5602"),
)


def seed_test_categories(session: Session, workspace: Workspace) -> None:
    accounts = {
        account.code: account
        for account in session.scalars(
            select(Account).where(Account.workspace_id == workspace.id)
        )
    }
    session.add_all(
        [
            Category(
                id=category_id,
                workspace_id=workspace.id,
                account_id=accounts[code].id,
                name=name,
                kind=kind,
            )
            for category_id, name, kind, code in TEST_CATEGORY_SEEDS
        ]
    )
    session.commit()


@pytest.fixture
def db_session(tmp_path) -> Generator[Session, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def pragmas(connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        workspace = seed_defaults(session)
        seed_test_categories(session, workspace)
        yield session
    engine.dispose()


@pytest.fixture
def workspace(db_session: Session) -> Workspace:
    workspace = db_session.query(Workspace).first()
    assert workspace is not None
    return workspace
