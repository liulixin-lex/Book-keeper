from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.amounts import from_e12, to_e12
from app.db import get_db
from app.dependencies import AuthContext, require_bookkeeper, require_csrf, require_viewer
from app.enums import AccountType, ActorType, CategoryKind
from app.models import (
    Account,
    AuditEvent,
    BusinessRecord,
    Category,
    Counterparty,
    FxRate,
    MoneyComponent,
    SubscriptionContract,
    User,
)
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    FxRateCreate,
    FxRateUpdate,
    ProviderCreate,
    ProviderUpdate,
)
from app.services.fx import (
    SUPPORTED_FX_CURRENCIES,
    FxProviderError,
    fetch_and_store_rate,
    fetch_latest_supported_rates,
    validate_supported_currency,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


class ORMView(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AccountView(ORMView):
    id: str
    code: str
    name: str
    account_type: str
    subtype: str | None
    currency: str | None
    is_active: bool


class CategoryView(ORMView):
    id: str
    parent_id: str | None
    account_id: str
    name: str
    kind: CategoryKind
    is_active: bool


class ProviderView(BaseModel):
    id: str
    name: str
    expense_category_id: str
    expense_category_name: str
    is_active: bool


class FxRateView(BaseModel):
    id: str
    base_currency: str
    quote_currency: str
    rate: str
    effective_at: datetime
    source: str
    rate_type: str
    fetched_at: datetime


def fx_view(rate: FxRate) -> FxRateView:
    return FxRateView(
        id=rate.id,
        base_currency=rate.base_currency,
        quote_currency=rate.quote_currency,
        rate=from_e12(rate.rate_e12),
        effective_at=rate.effective_at,
        source=rate.source,
        rate_type=rate.rate_type,
        fetched_at=rate.fetched_at,
    )


def _category(db: Session, workspace_id: str, category_id: str) -> Category:
    category = db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.workspace_id == workspace_id,
        )
    )
    if category is None:
        raise HTTPException(status_code=404, detail="类别不存在")
    return category


def _provider(db: Session, workspace_id: str, provider_id: str) -> Counterparty:
    provider = db.scalar(
        select(Counterparty).where(
            Counterparty.id == provider_id,
            Counterparty.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="提供商不存在")
    return provider


def _expense_category(
    db: Session, workspace_id: str, category_id: str, *, active_only: bool = True
) -> Category:
    statement = select(Category).where(
        Category.id == category_id,
        Category.workspace_id == workspace_id,
        Category.kind == CategoryKind.EXPENSE,
    )
    if active_only:
        statement = statement.where(Category.is_active.is_(True))
    category = db.scalar(statement)
    if category is None:
        raise HTTPException(status_code=422, detail="请选择当前账本中已启用的支出类别")
    return category


def _fx_rate(db: Session, rate_id: str) -> FxRate:
    rate = db.get(FxRate, rate_id)
    if rate is None:
        raise HTTPException(status_code=404, detail="汇率记录不存在")
    return rate


def _validate_category_account(
    db: Session, workspace_id: str, account_id: str, kind: CategoryKind
) -> Account:
    account = db.scalar(
        select(Account).where(
            Account.id == account_id,
            Account.workspace_id == workspace_id,
            Account.is_active.is_(True),
        )
    )
    if account is None:
        raise HTTPException(status_code=422, detail="总账科目不存在或已停用")
    allowed_types = (
        {AccountType.REVENUE}
        if kind == CategoryKind.INCOME
        else {AccountType.EXPENSE}
        if kind == CategoryKind.EXPENSE
        else {AccountType.REVENUE, AccountType.EXPENSE}
    )
    if AccountType(account.account_type) not in allowed_types:
        expected = "收入" if kind == CategoryKind.INCOME else "费用"
        raise HTTPException(status_code=422, detail=f"该类别必须映射到{expected}类科目")
    return account


def _audit_catalog(
    db: Session,
    user: User,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=user.workspace_id,
            actor_type=ActorType.USER,
            actor_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )


def _category_snapshot(category: Category) -> dict[str, Any]:
    return {
        "name": category.name,
        "kind": str(category.kind),
        "account_id": category.account_id,
        "is_active": category.is_active,
    }


def _provider_snapshot(provider: Counterparty) -> dict[str, Any]:
    return {
        "name": provider.name,
        "expense_category_id": provider.expense_category_id,
        "is_active": provider.is_active,
    }


def provider_view(provider: Counterparty) -> ProviderView:
    if provider.expense_category_id is None or provider.expense_category is None:
        raise HTTPException(status_code=500, detail="提供商尚未关联支出类别")
    return ProviderView(
        id=provider.id,
        name=provider.name,
        expense_category_id=provider.expense_category_id,
        expense_category_name=provider.expense_category.name,
        is_active=provider.is_active,
    )


def _fx_snapshot(rate: FxRate) -> dict[str, Any]:
    return {
        "base_currency": rate.base_currency,
        "quote_currency": rate.quote_currency,
        "rate": from_e12(rate.rate_e12),
        "effective_at": rate.effective_at.isoformat(),
        "source": rate.source,
        "rate_type": rate.rate_type,
    }


@router.get("/accounts", response_model=list[AccountView])
def accounts(
    user: Annotated[User, Depends(require_viewer)], db: Annotated[Session, Depends(get_db)]
) -> list[Account]:
    return list(
        db.scalars(
            select(Account).where(Account.workspace_id == user.workspace_id).order_by(Account.code)
        )
    )


@router.get("/categories", response_model=list[CategoryView])
def categories(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = False,
) -> list[Category]:
    statement = select(Category).where(Category.workspace_id == user.workspace_id)
    if active_only:
        statement = statement.where(Category.is_active.is_(True))
    return list(db.scalars(statement.order_by(Category.kind, Category.name)))


@router.post("/categories", response_model=CategoryView, status_code=status.HTTP_201_CREATED)
def add_category(
    payload: CategoryCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    kind = CategoryKind(payload.kind)
    _validate_category_account(db, user.workspace_id, payload.account_id, kind)
    if payload.parent_id is not None:
        parent = db.scalar(
            select(Category).where(
                Category.id == payload.parent_id,
                Category.workspace_id == user.workspace_id,
                Category.is_active.is_(True),
            )
        )
        if parent is None:
            raise HTTPException(status_code=422, detail="父分类不存在、已停用或不属于当前账本")
    category = Category(
        workspace_id=user.workspace_id,
        name=payload.name,
        kind=kind,
        account_id=payload.account_id,
        parent_id=payload.parent_id,
        is_active=payload.is_active,
    )
    try:
        db.add(category)
        db.flush()
        _audit_catalog(
            db,
            user,
            action="category.create",
            entity_type="category",
            entity_id=category.id,
            before=None,
            after=_category_snapshot(category),
        )
        db.commit()
        db.refresh(category)
        return category
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="类别名称已存在") from exc


@router.patch("/categories/{category_id}", response_model=CategoryView)
def edit_category(
    category_id: str,
    payload: CategoryUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Category:
    category = _category(db, user.workspace_id, category_id)
    before = _category_snapshot(category)
    kind = CategoryKind(payload.kind or category.kind)
    account_id = payload.account_id or category.account_id
    _validate_category_account(db, user.workspace_id, account_id, kind)
    linked_providers = db.scalar(
        select(func.count(Counterparty.id)).where(Counterparty.expense_category_id == category.id)
    )
    if linked_providers and kind != CategoryKind.EXPENSE:
        raise HTTPException(status_code=409, detail="该类别已被提供商引用，必须保持为支出类别")
    if linked_providers and "is_active" in payload.model_fields_set and payload.is_active is False:
        active_providers = db.scalar(
            select(func.count(Counterparty.id)).where(
                Counterparty.expense_category_id == category.id,
                Counterparty.is_active.is_(True),
            )
        )
        if active_providers:
            raise HTTPException(
                status_code=409,
                detail="该类别仍被启用的提供商使用，请先停用提供商",
            )
    if "name" in payload.model_fields_set:
        category.name = payload.name or category.name
    if "kind" in payload.model_fields_set:
        category.kind = kind
    if "account_id" in payload.model_fields_set:
        category.account_id = account_id
    if "is_active" in payload.model_fields_set:
        category.is_active = bool(payload.is_active)
    try:
        db.flush()
        _audit_catalog(
            db,
            user,
            action="category.update",
            entity_type="category",
            entity_id=category.id,
            before=before,
            after=_category_snapshot(category),
        )
        db.commit()
        db.refresh(category)
        return category
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="类别名称已存在") from exc


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: str,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    category = _category(db, user.workspace_id, category_id)
    linked_records = db.scalar(
        select(func.count(BusinessRecord.id)).where(BusinessRecord.category_id == category.id)
    )
    child_categories = db.scalar(
        select(func.count(Category.id)).where(Category.parent_id == category.id)
    )
    linked_providers = db.scalar(
        select(func.count(Counterparty.id)).where(Counterparty.expense_category_id == category.id)
    )
    if linked_records or child_categories or linked_providers:
        raise HTTPException(
            status_code=409,
            detail="该类别已被账单、子类别或提供商引用，请改为停用",
        )
    before = _category_snapshot(category)
    db.delete(category)
    _audit_catalog(
        db,
        user,
        action="category.delete",
        entity_type="category",
        entity_id=category.id,
        before=before,
        after=None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/providers", response_model=list[ProviderView])
def providers(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = False,
) -> list[ProviderView]:
    statement = (
        select(Counterparty)
        .options(selectinload(Counterparty.expense_category))
        .where(Counterparty.workspace_id == user.workspace_id)
    )
    if active_only:
        statement = statement.where(Counterparty.is_active.is_(True))
    return [provider_view(item) for item in db.scalars(statement.order_by(Counterparty.name))]


@router.post("/providers", response_model=ProviderView, status_code=201)
def add_provider(
    payload: ProviderCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ProviderView:
    category = _expense_category(db, user.workspace_id, payload.expense_category_id)
    provider = Counterparty(
        workspace_id=user.workspace_id,
        name=payload.name,
        roles_json=["supplier"],
        expense_category_id=category.id,
        metadata_json={},
        is_active=payload.is_active,
    )
    try:
        db.add(provider)
        db.flush()
        _audit_catalog(
            db,
            user,
            action="provider.create",
            entity_type="provider",
            entity_id=provider.id,
            before=None,
            after=_provider_snapshot(provider),
        )
        db.commit()
        loaded_provider = db.scalar(
            select(Counterparty)
            .options(selectinload(Counterparty.expense_category))
            .where(Counterparty.id == provider.id)
        )
        assert loaded_provider is not None
        return provider_view(loaded_provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="提供商名称已存在") from exc


@router.patch("/providers/{provider_id}", response_model=ProviderView)
def edit_provider(
    provider_id: str,
    payload: ProviderUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ProviderView:
    provider = _provider(db, user.workspace_id, provider_id)
    before = _provider_snapshot(provider)
    if "name" in payload.model_fields_set:
        provider.name = payload.name or provider.name
    if "expense_category_id" in payload.model_fields_set:
        category = _expense_category(db, user.workspace_id, payload.expense_category_id or "")
        provider.expense_category_id = category.id
    if "is_active" in payload.model_fields_set:
        if payload.is_active:
            _expense_category(db, user.workspace_id, provider.expense_category_id or "")
        provider.is_active = bool(payload.is_active)
    provider.roles_json = ["supplier"]
    try:
        db.flush()
        _audit_catalog(
            db,
            user,
            action="provider.update",
            entity_type="provider",
            entity_id=provider.id,
            before=before,
            after=_provider_snapshot(provider),
        )
        db.commit()
        loaded_provider = db.scalar(
            select(Counterparty)
            .options(selectinload(Counterparty.expense_category))
            .where(Counterparty.id == provider.id)
        )
        assert loaded_provider is not None
        return provider_view(loaded_provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="提供商名称已存在") from exc


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(
    provider_id: str,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    provider = _provider(db, user.workspace_id, provider_id)
    linked_records = db.scalar(
        select(func.count(BusinessRecord.id)).where(BusinessRecord.counterparty_id == provider.id)
    )
    linked_contracts = db.scalar(
        select(func.count(SubscriptionContract.id)).where(
            SubscriptionContract.counterparty_id == provider.id
        )
    )
    if linked_records or linked_contracts:
        raise HTTPException(status_code=409, detail="该提供商已被业务引用，请改为停用")
    before = _provider_snapshot(provider)
    db.delete(provider)
    _audit_catalog(
        db,
        user,
        action="provider.delete",
        entity_type="provider",
        entity_id=provider.id,
        before=before,
        after=None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/fx-rates", response_model=list[FxRateView])
def fx_rates(
    _user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    currency: str | None = None,
) -> list[FxRateView]:
    statement = select(FxRate).where(
        FxRate.base_currency.in_(SUPPORTED_FX_CURRENCIES),
        FxRate.quote_currency == "CNY",
    )
    if currency:
        try:
            normalized = validate_supported_currency(currency)
        except FxProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        statement = statement.where(FxRate.base_currency == normalized)
    rows = db.scalars(
        statement.order_by(
            FxRate.base_currency,
            FxRate.effective_at.desc(),
            FxRate.fetched_at.desc(),
        )
    )
    latest: dict[str, FxRate] = {}
    for row in rows:
        latest.setdefault(row.base_currency, row)
    return [fx_view(latest[code]) for code in sorted(latest)]


@router.post("/fx-rates", response_model=FxRateView, status_code=status.HTTP_201_CREATED)
def add_fx_rate(
    payload: FxRateCreate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> FxRateView:
    try:
        currency = validate_supported_currency(payload.base_currency)
    except FxProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.quote_currency != "CNY":
        raise HTTPException(status_code=422, detail="本位币仅支持 CNY")
    rate = FxRate(
        base_currency=currency,
        quote_currency="CNY",
        rate_e12=to_e12(payload.rate),
        effective_at=payload.effective_at,
        source="manual",
        rate_type="manual_override",
        fetched_at=datetime.now(UTC),
    )
    try:
        db.add(rate)
        db.flush()
        _audit_catalog(
            db,
            user,
            action="fx_rate.create",
            entity_type="fx_rate",
            entity_id=rate.id,
            before=None,
            after=_fx_snapshot(rate),
        )
        db.commit()
        db.refresh(rate)
        return fx_view(rate)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="同一时间的手工汇率已存在") from exc


@router.patch("/fx-rates/{rate_id}", response_model=FxRateView)
def edit_fx_rate(
    rate_id: str,
    payload: FxRateUpdate,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> FxRateView:
    rate = _fx_rate(db, rate_id)
    before = _fx_snapshot(rate)
    rate.rate_e12 = to_e12(payload.rate)
    rate.effective_at = datetime.now(UTC)
    rate.source = "manual"
    rate.rate_type = "manual_override"
    rate.fetched_at = datetime.now(UTC)
    _audit_catalog(
        db,
        user,
        action="fx_rate.update",
        entity_type="fx_rate",
        entity_id=rate.id,
        before=before,
        after=_fx_snapshot(rate),
    )
    db.commit()
    db.refresh(rate)
    return fx_view(rate)


@router.delete("/fx-rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fx_rate(
    rate_id: str,
    user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    rate = _fx_rate(db, rate_id)
    linked_records = db.scalar(
        select(func.count(MoneyComponent.id)).where(MoneyComponent.fx_rate_id == rate.id)
    )
    if linked_records:
        raise HTTPException(status_code=409, detail="该汇率已被账单引用，不能删除")
    before = _fx_snapshot(rate)
    db.delete(rate)
    _audit_catalog(
        db,
        user,
        action="fx_rate.delete",
        entity_type="fx_rate",
        entity_id=rate.id,
        before=before,
        after=None,
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/fx-rates/refresh", response_model=list[FxRateView])
def refresh_fx_rates(
    _user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> list[FxRateView]:
    try:
        fetch_latest_supported_rates(db)
        return fx_rates(_user, db)
    except FxProviderError as exc:
        raise HTTPException(status_code=502, detail=f"汇率服务不可用：{exc}") from exc


@router.post("/fx-rates/fetch", response_model=FxRateView)
def fetch_fx_rate(
    currency: str,
    effective_date: date,
    _user: Annotated[User, Depends(require_bookkeeper)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> FxRateView:
    try:
        validate_supported_currency(currency)
        return fx_view(fetch_and_store_rate(db, currency, effective_date))
    except FxProviderError as exc:
        raise HTTPException(status_code=502, detail=f"汇率服务不可用：{exc}") from exc
