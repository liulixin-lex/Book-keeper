from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_viewer
from app.models import User, Workspace
from app.schemas import DailyReportRow, DashboardReportRead, OverviewRead
from app.services.fx import (
    FxProviderError,
    resolve_display_rate,
    validate_supported_currency,
)
from app.services.reports import daily_report, dashboard_report, overview

router = APIRouter(prefix="/reports", tags=["reports"])


def _workspace(db: Session, user: User) -> Workspace:
    workspace = db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=500, detail="账本不存在")
    return workspace


@router.get("/dashboard", response_model=DashboardReportRead)
def get_dashboard_report(
    start_date: date,
    end_date: date,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    display_currency: str = Query(default="CNY", min_length=3, max_length=3),
) -> DashboardReportRead:
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="结束日期不能早于开始日期")
    normalized = display_currency.strip().upper()
    if normalized != "CNY":
        try:
            normalized = validate_supported_currency(normalized)
        except FxProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        rate = resolve_display_rate(db, normalized)
    except FxProviderError as exc:
        raise HTTPException(status_code=502, detail=f"汇率服务不可用：{exc}") from exc
    return dashboard_report(db, _workspace(db, user), start_date, end_date, rate)


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
