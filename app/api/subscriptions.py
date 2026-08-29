from __future__ import annotations

from datetime import date
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.amounts import as_decimal, from_e8, to_e8
from app.api.records import record_view
from app.db import get_db
from app.dependencies import AuthContext, require_bookkeeper, require_csrf, require_viewer
from app.enums import ActorType, RecordType
from app.models import (
    AuditEvent,
    Counterparty,
    SubscriptionContract,
    User,
    Workspace,
)
from app.schemas import ExpenseCreate, MoneyInput, RecordRead
from app.services.accounting import AccountingError, create_expense
from app.services.idempotency import commit_result, replay_if_exists, request_digest

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    counterparty_id: str
    billing_cycle: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=12)
    expected_amount: str | None = None
    renewal_date: date | None = None
    auto_renew: bool = False

    @field_validator("expected_amount")
    @classmethod
    def validate_expected_amount(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if as_decimal(normalized) < 0:
            raise ValueError("预计金额不能为负数")
        return normalized


class SubscriptionUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=240)
    counterparty_id: str | None = None
    billing_cycle: str | None = Field(default=None, min_length=1, max_length=40)
    currency: str | None = Field(default=None, min_length=3, max_length=12)
    expected_amount: str | None = None
    renewal_date: date | None = None
    auto_renew: bool | None = None
    is_active: bool | None = None

    @field_validator("expected_amount")
    @classmethod
    def validate_expected_amount(cls, value: str | None) -> str | None:
        return SubscriptionCreate.validate_expected_amount(value)

    @model_validator(mode="after")
    def require_change(self) -> SubscriptionUpdate:
        if self.model_fields_set == {"expected_version"}:
            raise ValueError("至少需要修改一个字段")
        return self


class SubscriptionCharge(BaseModel):
    accounting_date: date
    description: str | None = Field(default=None, max_length=500)
    cost: MoneyInput
    cash: MoneyInput | None = None
    external_id: str | None = Field(default=None, max_length=240)
    service_period_start: date | None = None
    service_period_end: date | None = None
    note: str | None = None
    post: bool = True


class SubscriptionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    counterparty_id: str
    name: str
    billing_cycle: str
    currency: str
    expected_amount: str | None
    renewal_date: date | None
    auto_renew: bool
    is_active: bool
    version: int


def _view(contract: SubscriptionContract) -> SubscriptionView:
    return SubscriptionView(
        id=contract.id,
        counterparty_id=contract.counterparty_id,
        name=contract.name,
        billing_cycle=contract.billing_cycle,
        currency=contract.currency,
        expected_amount=(
            from_e8(contract.expected_amount_e8)
            if contract.expected_amount_e8 is not None
            else None
        ),
        renewal_date=contract.renewal_date,
        auto_renew=contract.auto_renew,
        is_active=contract.is_active,
        version=contract.version,
    )


def _workspace(db: Session, user: User) -> Workspace:
    workspace = db.get(Workspace, user.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=500, detail="账本不存在")
    return workspace


def _contract(db: Session, user: User, contract_id: str) -> SubscriptionContract:
    contract = db.scalar(
        select(SubscriptionContract).where(
            SubscriptionContract.id == contract_id,
            SubscriptionContract.workspace_id == user.workspace_id,
        )
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="订阅合同不存在")
    return contract


def _counterparty(db: Session, user: User, counterparty_id: str) -> Counterparty:
    counterparty = db.scalar(
        select(Counterparty).where(
            Counterparty.id == counterparty_id,
            Counterparty.workspace_id == user.workspace_id,
            Counterparty.is_active.is_(True),
        )
    )
    if counterparty is None or counterparty.expense_category_id is None:
        raise HTTPException(status_code=422, detail="订阅服务商不存在")
    return counterparty


def _audit(
    db: Session,
    user: User,
    action: str,
    entity_id: str,
    after: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=user.workspace_id,
            actor_type=ActorType.USER,
            actor_id=user.id,
            action=action,
            entity_type="subscription_contract",
            entity_id=entity_id,
            after_json=after,
        )
    )


@router.get("", response_model=list[SubscriptionView])
def list_subscriptions(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SubscriptionView]:
    contracts = db.scalars(
        select(SubscriptionContract)
        .where(SubscriptionContract.workspace_id == user.workspace_id)
        .order_by(SubscriptionContract.name)
    )
    return [_view(contract) for contract in contracts]


@router.post("", response_model=SubscriptionView, status_code=status.HTTP_201_CREATED)
def add_subscription(
    payload: SubscriptionCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> SubscriptionView:
    _counterparty(db, user, payload.counterparty_id)
    contract = SubscriptionContract(
        workspace_id=user.workspace_id,
        counterparty_id=payload.counterparty_id,
        name=payload.name.strip(),
        billing_cycle=payload.billing_cycle.strip(),
        currency=payload.currency.strip().upper(),
        expected_amount_e8=(
            to_e8(payload.expected_amount) if payload.expected_amount is not None else None
        ),
        renewal_date=payload.renewal_date,
        auto_renew=payload.auto_renew,
    )
    db.add(contract)
    db.flush()
    _audit(db, user, "subscription.create", contract.id)
    db.commit()
    db.refresh(contract)
    return _view(contract)


@router.patch("/{contract_id}", response_model=SubscriptionView)
def update_subscription(
    contract_id: str,
    payload: SubscriptionUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> SubscriptionView:
    contract = _contract(db, user, contract_id)
    if payload.counterparty_id is not None:
        _counterparty(db, user, payload.counterparty_id)
    values: dict[str, Any] = {}
    for field in (
        "name",
        "counterparty_id",
        "billing_cycle",
        "renewal_date",
        "auto_renew",
        "is_active",
    ):
        if field in payload.model_fields_set:
            values[field] = getattr(payload, field)
    if payload.currency is not None:
        values["currency"] = payload.currency.strip().upper()
    if "expected_amount" in payload.model_fields_set:
        values["expected_amount_e8"] = (
            to_e8(payload.expected_amount) if payload.expected_amount is not None else None
        )
    values["version"] = payload.expected_version + 1
    changed = cast(
        CursorResult[Any],
        db.execute(
            update(SubscriptionContract)
            .where(
                SubscriptionContract.id == contract.id,
                SubscriptionContract.workspace_id == user.workspace_id,
                SubscriptionContract.version == payload.expected_version,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        ),
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="订阅合同已被其他用户修改")
    _audit(
        db,
        user,
        "subscription.update",
        contract.id,
        {"version": payload.expected_version + 1},
    )
    db.commit()
    db.expire_all()
    contract = _contract(db, user, contract_id)
    db.refresh(contract)
    return _view(contract)


@router.delete("/{contract_id}", status_code=204)
def deactivate_subscription(
    contract_id: str,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    contract = _contract(db, user, contract_id)
    changed = cast(
        CursorResult[Any],
        db.execute(
            update(SubscriptionContract)
            .where(
                SubscriptionContract.id == contract.id,
                SubscriptionContract.workspace_id == user.workspace_id,
                SubscriptionContract.version == expected_version,
            )
            .values(is_active=False, version=expected_version + 1)
            .execution_options(synchronize_session=False)
        ),
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="订阅合同已被其他用户修改")
    _audit(db, user, "subscription.deactivate", contract.id)
    db.commit()
    return Response(status_code=204)


@router.post("/{contract_id}/charges", response_model=RecordRead, status_code=201)
def add_subscription_charge(
    contract_id: str,
    payload: SubscriptionCharge,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RecordRead:
    contract = _contract(db, user, contract_id)
    if not contract.is_active:
        raise HTTPException(status_code=409, detail="订阅合同已停用")
    provider = _counterparty(db, user, contract.counterparty_id)
    digest = request_digest(
        {"contract_id": contract_id, "payload": payload.model_dump(mode="json")}
    )
    replay = replay_if_exists(db, user, "subscriptions.charge", idempotency_key, digest)
    if replay is not None:
        return RecordRead.model_validate(replay)
    try:
        record = create_expense(
            db,
            _workspace(db, user),
            ExpenseCreate(
                accounting_date=payload.accounting_date,
                description=payload.description or f"订阅费用 - {contract.name}",
                cost=payload.cost,
                cash=payload.cash,
                category_id=provider.expense_category_id,
                counterparty_id=contract.counterparty_id,
                source_channel="subscription",
                external_id=payload.external_id,
                service_period_start=payload.service_period_start,
                service_period_end=payload.service_period_end,
                note=payload.note,
                metadata={"subscription_contract_id": contract.id},
                post=payload.post,
            ),
            actor_id=user.id,
            record_type=RecordType.EXPENSE,
            commit=False,
        )
        view = record_view(record)
        replay = commit_result(
            db,
            user,
            "subscriptions.charge",
            idempotency_key,
            digest,
            view.model_dump(mode="json"),
            201,
        )
    except (AccountingError, IntegrityError, OperationalError) as exc:
        db.rollback()
        replay = replay_if_exists(db, user, "subscriptions.charge", idempotency_key, digest)
        if replay is not None:
            return RecordRead.model_validate(replay)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RecordRead.model_validate(replay) if replay is not None else view
