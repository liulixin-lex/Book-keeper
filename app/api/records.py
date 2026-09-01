from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.amounts import from_e8
from app.api.approvals import approval_view
from app.db import get_db
from app.dependencies import (
    AuthContext,
    require_bookkeeper,
    require_csrf,
    require_viewer,
)
from app.enums import ActorType, AmountRole, CategoryKind, RecordStatus, RecordType
from app.models import (
    ApprovalRequest,
    AuditEvent,
    BusinessRecord,
    Category,
    Counterparty,
    MoneyComponent,
    User,
    Workspace,
)
from app.schemas import (
    ApprovalRequestRead,
    DraftRecordUpdate,
    ExpenseBatchCreate,
    ExpenseCreate,
    ExpenseUpdate,
    IncomeBatchCreate,
    IncomeCreate,
    IncomeUpdate,
    MoneyRead,
    RecordBatchDelete,
    RecordBatchDeleteRead,
    RecordPageRead,
    RecordRead,
)
from app.services.accounting import (
    AccountingError,
    create_expense,
    create_income,
    delete_record_graph,
    post_record,
    resolve_category,
    resolve_counterparty,
    update_expense,
    update_income,
    validate_record_reversal,
)
from app.services.idempotency import commit_result, replay_if_exists, request_digest

router = APIRouter(prefix="/records", tags=["records"])


def _workspace(db: Session, user: User) -> Workspace:
    workspace = db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=500, detail="账本不存在")
    return workspace


def record_view(record: BusinessRecord) -> RecordRead:
    return RecordRead(
        id=record.id,
        record_type=RecordType(record.record_type),
        status=RecordStatus(record.status),
        accounting_date=record.accounting_date,
        occurred_at=record.occurred_at,
        date_precision=record.date_precision,
        description=record.description,
        source_channel=record.source_channel,
        external_id=record.external_id,
        recognition_method=record.recognition_method,
        note=record.note,
        category_id=record.category_id,
        category_name=record.category.name if record.category else None,
        counterparty_id=record.counterparty_id,
        counterparty_name=record.counterparty.name if record.counterparty else None,
        created_by_user_id=record.created_by_user_id,
        created_by_username=(
            record.created_by_user.username if record.created_by_user else "历史/系统"
        ),
        source_locator=record.source_locator_json,
        metadata=record.metadata_json,
        version=record.version,
        amounts=[
            MoneyRead(
                role=str(item.role),
                currency=item.currency,
                amount=from_e8(item.amount_e8),
                amount_cny=from_e8(item.amount_cny_e8),
                fx_rate_id=item.fx_rate_id,
                derived=item.is_derived,
            )
            for item in record.amounts
        ],
    )


@router.get("", response_model=list[RecordRead])
def list_records(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    start_date: date | None = None,
    end_date: date | None = None,
    record_type: Literal["income", "expense"] | None = None,
    record_status: Annotated[RecordStatus | None, Query(alias="status")] = None,
    category_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RecordRead]:
    statement = (
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
            selectinload(BusinessRecord.created_by_user),
        )
        .where(BusinessRecord.workspace_id == user.workspace_id)
        .order_by(BusinessRecord.accounting_date.desc(), BusinessRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if start_date:
        statement = statement.where(BusinessRecord.accounting_date >= start_date)
    if end_date:
        statement = statement.where(BusinessRecord.accounting_date <= end_date)
    if record_type:
        statement = statement.where(BusinessRecord.record_type == record_type)
    if record_status:
        statement = statement.where(BusinessRecord.status == record_status)
    if category_id:
        statement = statement.where(BusinessRecord.category_id == category_id)
    return [record_view(record) for record in db.scalars(statement)]


@router.get("/page", response_model=RecordPageRead)
def page_records(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    record_type: Literal["income", "expense"],
    start_date: date | None = None,
    end_date: date | None = None,
    record_status: Annotated[RecordStatus | None, Query(alias="status")] = None,
    category_id: str | None = None,
    created_by_user_id: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecordPageRead:
    conditions = [
        BusinessRecord.workspace_id == user.workspace_id,
        BusinessRecord.record_type == record_type,
    ]
    if start_date:
        conditions.append(BusinessRecord.accounting_date >= start_date)
    if end_date:
        conditions.append(BusinessRecord.accounting_date <= end_date)
    if record_status:
        conditions.append(BusinessRecord.status == record_status)
    if category_id:
        conditions.append(BusinessRecord.category_id == category_id)
    if created_by_user_id:
        conditions.append(BusinessRecord.created_by_user_id == created_by_user_id)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        conditions.append(
            or_(
                BusinessRecord.description.ilike(keyword),
                BusinessRecord.external_id.ilike(keyword),
                Category.name.ilike(keyword),
                Counterparty.name.ilike(keyword),
                User.username.ilike(keyword),
            )
        )

    joined_records = (
        select(BusinessRecord)
        .outerjoin(Category, Category.id == BusinessRecord.category_id)
        .outerjoin(Counterparty, Counterparty.id == BusinessRecord.counterparty_id)
        .outerjoin(User, User.id == BusinessRecord.created_by_user_id)
        .where(*conditions)
    )
    total = db.scalar(
        select(func.count(BusinessRecord.id))
        .select_from(BusinessRecord)
        .outerjoin(Category, Category.id == BusinessRecord.category_id)
        .outerjoin(Counterparty, Counterparty.id == BusinessRecord.counterparty_id)
        .outerjoin(User, User.id == BusinessRecord.created_by_user_id)
        .where(*conditions)
    )
    amount_total = db.scalar(
        select(func.coalesce(func.sum(MoneyComponent.amount_cny_e8), 0))
        .select_from(MoneyComponent)
        .join(BusinessRecord, BusinessRecord.id == MoneyComponent.record_id)
        .outerjoin(Category, Category.id == BusinessRecord.category_id)
        .outerjoin(Counterparty, Counterparty.id == BusinessRecord.counterparty_id)
        .outerjoin(User, User.id == BusinessRecord.created_by_user_id)
        .where(*conditions, MoneyComponent.role == AmountRole.CASH)
    )
    rows = db.scalars(
        joined_records.options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
            selectinload(BusinessRecord.created_by_user),
        )
        .order_by(BusinessRecord.accounting_date.desc(), BusinessRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return RecordPageRead(
        items=[record_view(record) for record in rows],
        total=int(total or 0),
        total_amount_cny=from_e8(int(amount_total or 0)),
        limit=limit,
        offset=offset,
    )


@router.get("/{record_id}", response_model=RecordRead)
def get_record(
    record_id: str,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> RecordRead:
    record = db.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
            selectinload(BusinessRecord.created_by_user),
        )
        .where(BusinessRecord.id == record_id, BusinessRecord.workspace_id == user.workspace_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record_view(record)


def _replay(
    db: Session, user: User, operation: str, key: str | None, payload: object
) -> tuple[str, dict | None]:
    digest = request_digest(payload)
    return digest, replay_if_exists(db, user, operation, key, digest)


def _record_conflict(
    db: Session,
    user: User,
    operation: str,
    key: str | None,
    digest: str,
    exc: Exception,
) -> RecordRead:
    db.rollback()
    replay = replay_if_exists(db, user, operation, key, digest)
    if replay is not None:
        return RecordRead.model_validate(replay)
    raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/income", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
def add_income(
    payload: IncomeCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RecordRead:
    if not payload.cash_received or not payload.post:
        raise HTTPException(status_code=422, detail="收入录入后必须立即到账并过账")
    digest, replay = _replay(db, user, "records.income", idempotency_key, payload)
    if replay is not None:
        return RecordRead.model_validate(replay)
    try:
        record = create_income(db, _workspace(db, user), payload, actor_id=user.id, commit=False)
        view = record_view(record)
        replay = commit_result(
            db,
            user,
            "records.income",
            idempotency_key,
            digest,
            view.model_dump(mode="json"),
            201,
        )
    except (AccountingError, IntegrityError, OperationalError) as exc:
        return _record_conflict(db, user, "records.income", idempotency_key, digest, exc)
    return RecordRead.model_validate(replay) if replay is not None else view


@router.post("/expenses", response_model=RecordRead, status_code=status.HTTP_201_CREATED)
def add_expense(
    payload: ExpenseCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RecordRead:
    if payload.cash is None or not payload.post:
        raise HTTPException(status_code=422, detail="支出录入后必须立即支付并过账")
    digest, replay = _replay(db, user, "records.expense", idempotency_key, payload)
    if replay is not None:
        return RecordRead.model_validate(replay)
    try:
        record = create_expense(db, _workspace(db, user), payload, actor_id=user.id, commit=False)
        view = record_view(record)
        replay = commit_result(
            db,
            user,
            "records.expense",
            idempotency_key,
            digest,
            view.model_dump(mode="json"),
            201,
        )
    except (AccountingError, IntegrityError, OperationalError) as exc:
        return _record_conflict(db, user, "records.expense", idempotency_key, digest, exc)
    return RecordRead.model_validate(replay) if replay is not None else view


@router.post(
    "/income/batch",
    response_model=list[RecordRead],
    status_code=status.HTTP_201_CREATED,
)
def add_income_batch(
    payload: IncomeBatchCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RecordRead]:
    workspace = _workspace(db, user)
    records: list[BusinessRecord] = []
    try:
        for index, item in enumerate(payload.items, start=1):
            if not item.cash_received or not item.post:
                raise AccountingError(f"第 {index} 条收入必须立即到账并过账")
            records.append(
                create_income(db, workspace, item, actor_id=user.id, commit=False)
            )
        views = [record_view(record) for record in records]
        db.commit()
    except (AccountingError, IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return views


@router.post(
    "/expenses/batch",
    response_model=list[RecordRead],
    status_code=status.HTTP_201_CREATED,
)
def add_expense_batch(
    payload: ExpenseBatchCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> list[RecordRead]:
    workspace = _workspace(db, user)
    records: list[BusinessRecord] = []
    try:
        for index, item in enumerate(payload.items, start=1):
            if item.cash is None or not item.post:
                raise AccountingError(f"第 {index} 条支出必须立即支付并过账")
            records.append(
                create_expense(db, workspace, item, actor_id=user.id, commit=False)
            )
        views = [record_view(record) for record in records]
        db.commit()
    except (AccountingError, IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return views


def _record_for_write(db: Session, user: User, record_id: str) -> BusinessRecord:
    record = db.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
            selectinload(BusinessRecord.created_by_user),
        )
        .where(BusinessRecord.id == record_id, BusinessRecord.workspace_id == user.workspace_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


@router.put("/{record_id}/income", response_model=RecordRead)
def edit_income(
    record_id: str,
    payload: IncomeUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> RecordRead:
    if not payload.cash_received or not payload.post:
        raise HTTPException(status_code=422, detail="收入编辑后必须立即到账并过账")
    record = _record_for_write(db, user, record_id)
    try:
        updated = update_income(
            db,
            _workspace(db, user),
            record,
            payload,
            actor_id=user.id,
        )
    except (AccountingError, IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record_view(updated)


@router.put("/{record_id}/expense", response_model=RecordRead)
def edit_expense(
    record_id: str,
    payload: ExpenseUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> RecordRead:
    if payload.cash is None or not payload.post:
        raise HTTPException(status_code=422, detail="支出编辑后必须立即支付并过账")
    record = _record_for_write(db, user, record_id)
    try:
        updated = update_expense(
            db,
            _workspace(db, user),
            record,
            payload,
            actor_id=user.id,
        )
    except (AccountingError, IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record_view(updated)


@router.post("/batch-delete", response_model=RecordBatchDeleteRead)
def delete_records_batch(
    payload: RecordBatchDelete,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> RecordBatchDeleteRead:
    existing_ids = set(
        db.scalars(
            select(BusinessRecord.id).where(
                BusinessRecord.workspace_id == user.workspace_id,
                BusinessRecord.id.in_(payload.record_ids),
                BusinessRecord.record_type.in_([RecordType.INCOME, RecordType.EXPENSE]),
            )
        )
    )
    missing_ids = set(payload.record_ids) - existing_ids
    if missing_ids:
        raise HTTPException(status_code=404, detail="部分记录不存在或不可删除，请刷新后重试")
    deleted_count = 0
    try:
        for record_id in payload.record_ids:
            record = db.scalar(
                select(BusinessRecord).where(
                    BusinessRecord.id == record_id,
                    BusinessRecord.workspace_id == user.workspace_id,
                )
            )
            if record is not None:
                deleted_count += delete_record_graph(
                    db, record, actor_id=user.id, commit=False
                )
        db.commit()
    except (AccountingError, IntegrityError, OperationalError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RecordBatchDeleteRead(deleted_count=deleted_count)


@router.patch("/{record_id}/draft", response_model=RecordRead)
def update_draft(
    record_id: str,
    payload: DraftRecordUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> RecordRead:
    record = db.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
        )
        .where(BusinessRecord.id == record_id, BusinessRecord.workspace_id == user.workspace_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    resolved_dimensions: dict[str, str | None] = {}
    try:
        if "category_id" in payload.model_fields_set:
            if payload.category_id:
                allowed = (
                    {CategoryKind.INCOME, CategoryKind.BOTH}
                    if record.record_type in {RecordType.INCOME, RecordType.REFUND}
                    else {CategoryKind.EXPENSE, CategoryKind.BOTH}
                )
                resolved_dimensions["category_id"] = resolve_category(
                    db, user.workspace_id, payload.category_id, allowed
                ).id
            else:
                resolved_dimensions["category_id"] = None
        if "counterparty_id" in payload.model_fields_set:
            resolved_dimensions["counterparty_id"] = (
                resolve_counterparty(db, user.workspace_id, payload.counterparty_id).id
                if payload.counterparty_id
                else None
            )
    except AccountingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    values: dict[str, object] = {"version": payload.expected_version + 1}
    for field in ("description", "note"):
        if field in payload.model_fields_set:
            values[field] = getattr(payload, field)
    values.update(resolved_dimensions)

    try:
        result = db.connection().execute(
            update(BusinessRecord)
            .where(
                BusinessRecord.id == record_id,
                BusinessRecord.workspace_id == user.workspace_id,
                BusinessRecord.status == RecordStatus.DRAFT,
                BusinessRecord.version == payload.expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="记录已被其他用户修改或不再是草稿",
            )
        db.commit()
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise

    updated = db.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
        )
        .where(BusinessRecord.id == record_id)
        .execution_options(populate_existing=True)
    )
    assert updated is not None
    return record_view(updated)


@router.post("/{record_id}/post", response_model=RecordRead)
def post_draft_record(
    record_id: str,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> RecordRead:
    record = db.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.category),
            selectinload(BusinessRecord.counterparty),
        )
        .where(BusinessRecord.id == record_id, BusinessRecord.workspace_id == user.workspace_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        post_record(db, record, actor_id=user.id, actor_type=ActorType.USER)
        db.commit()
    except AccountingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record_view(record)


class ReversePayload(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/{record_id}/reverse", response_model=ApprovalRequestRead)
def request_record_reversal(
    record_id: str,
    payload: ReversePayload,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalRequestRead:
    record = db.scalar(
        select(BusinessRecord)
        .options(
            selectinload(BusinessRecord.amounts),
            selectinload(BusinessRecord.counterparty),
        )
        .where(BusinessRecord.id == record_id, BusinessRecord.workspace_id == user.workspace_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    if record.status != RecordStatus.POSTED:
        raise HTTPException(status_code=409, detail="只能申请冲正已过账记录")
    try:
        validate_record_reversal(db, record)
    except AccountingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    existing = db.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.workspace_id == user.workspace_id,
            ApprovalRequest.kind == "record.reverse",
            ApprovalRequest.status == "pending",
        )
    )
    for item in existing:
        if item.payload_json.get("record_id") == record.id:
            return approval_view(item)
    approval = ApprovalRequest(
        workspace_id=user.workspace_id,
        kind="record.reverse",
        payload_json={"record_id": record.id, "reason": payload.reason},
        requested_by_user_id=user.id,
    )
    db.add(approval)
    db.flush()
    db.add(
        AuditEvent(
            workspace_id=user.workspace_id,
            actor_type=ActorType.USER,
            actor_id=user.id,
            action="record.reverse.request",
            entity_type="business_record",
            entity_id=record.id,
            after_json={"approval_id": approval.id},
        )
    )
    db.commit()
    db.refresh(approval)
    return approval_view(approval)


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_record(
    record_id: str,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    record = db.scalar(
        select(BusinessRecord).where(
            BusinessRecord.id == record_id,
            BusinessRecord.workspace_id == user.workspace_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    try:
        delete_record_graph(db, record, actor_id=user.id)
    except AccountingError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
