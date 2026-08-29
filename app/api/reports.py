from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_viewer
from app.models import User, Workspace
from app.schemas import DailyReportRow, OverviewRead
from app.services.reports import daily_report, overview

router = APIRouter(prefix="/reports", tags=["reports"])


def _workspace(db: Session, user: User) -> Workspace:
    workspace = db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=500, detail="账本不存在")
    return workspace


@router.get("/overview", response_model=OverviewRead)
def get_overview(
    start_date: date,
    end_date: date,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> OverviewRead:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    return overview(db, _workspace(db, user), start_date, end_date)


@router.get("/daily", response_model=list[DailyReportRow])
def get_daily_report(
    start_date: date,
    end_date: date,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    basis: str = Query(default="both", pattern="^(both|operating|cash)$"),
) -> list[DailyReportRow]:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    # Both metric groups are returned for a stable API shape; basis is retained for clients.
    return daily_report(db, _workspace(db, user), start_date, end_date)
