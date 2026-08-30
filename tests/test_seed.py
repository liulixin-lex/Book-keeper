from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Category, Counterparty, Workspace
from app.services.seed import seed_defaults


def test_startup_does_not_restore_deleted_categories_or_create_providers(
    db_session: Session,
) -> None:
    workspace = db_session.scalar(select(Workspace))
    assert workspace is not None
    db_session.execute(delete(Category).where(Category.workspace_id == workspace.id))
    db_session.commit()

    seed_defaults(db_session)
    seed_defaults(db_session)

    assert db_session.scalar(
        select(func.count()).select_from(Category).where(Category.workspace_id == workspace.id)
    ) == 0
    assert db_session.scalar(
        select(func.count())
        .select_from(Counterparty)
        .where(Counterparty.workspace_id == workspace.id)
    ) == 0
