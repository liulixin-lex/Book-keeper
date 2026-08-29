from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_admin
from app.models import AuditEvent, User

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_type: str
    actor_id: str | None
    action: str
    entity_type: str
    entity_id: str
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    request_id: str | None
    ai_run_id: str | None
    created_at: datetime


class AuditPageRead(BaseModel):
    items: list[AuditView]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AuditPageRead)
def list_audit_events(
    user: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AuditPageRead:
    conditions = [AuditEvent.workspace_id == user.workspace_id]
    if entity_type:
        conditions.append(AuditEvent.entity_type == entity_type)
    if entity_id:
        conditions.append(AuditEvent.entity_id == entity_id)
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions)) or 0
    items = list(
        db.scalars(
            select(AuditEvent)
            .where(*conditions)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return AuditPageRead(items=items, total=total, limit=limit, offset=offset)
