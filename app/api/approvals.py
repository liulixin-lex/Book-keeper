from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.ai.schemas import AIProviderCreate
from app.amounts import to_e12
from app.db import get_db
from app.dependencies import AuthContext, require_admin, require_csrf, require_viewer
from app.enums import ActorType, ApprovalStatus, UserRole
from app.models import (
    AIProvider,
    AIRun,
    AIWorkspaceSettings,
    ApprovalRequest,
    AuditEvent,
    BusinessRecord,
    FxRate,
    User,
)
from app.schemas import ApprovalRequestRead, FxRateCreate
from app.security import revoke_user_sessions
from app.services.accounting import AccountingError, reverse_record

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


def _sanitized_payload(value: Any, *, key: str = "") -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(
        marker in normalized_key
        for marker in ("api_key", "authorization", "password", "secret", "token", "encrypted")
    ):
        return "[redacted]"
    if isinstance(value, dict):
        return {name: _sanitized_payload(item, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [_sanitized_payload(item) for item in value]
    return deepcopy(value)


def approval_view(item: ApprovalRequest) -> ApprovalRequestRead:
    return ApprovalRequestRead(
        id=item.id,
        kind=item.kind,
        status=ApprovalStatus(item.status),
        payload=_sanitized_payload(item.payload_json),
        requested_by_user_id=item.requested_by_user_id,
        requested_by_ai_run_id=item.requested_by_ai_run_id,
        decided_by_id=item.decided_by_id,
        decided_at=item.decided_at,
        reason=item.reason,
        created_at=item.created_at,
    )


def request_approval(
    db: Session,
    *,
    requester: User,
    kind: str,
    payload: dict[str, Any],
) -> ApprovalRequestRead:
    item = ApprovalRequest(
        workspace_id=requester.workspace_id,
        kind=kind,
        status=ApprovalStatus.PENDING,
        payload_json=payload,
        requested_by_user_id=requester.id,
    )
    db.add(item)
    db.flush()
    db.add(
        AuditEvent(
            workspace_id=requester.workspace_id,
            actor_type=ActorType.USER,
            actor_id=requester.id,
            action="approval.request",
            entity_type="approval_request",
            entity_id=item.id,
            after_json={"kind": kind},
        )
    )
    db.commit()
    db.refresh(item)
    return approval_view(item)


def _approval(db: Session, user: User, approval_id: str) -> ApprovalRequest:
    item = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.workspace_id == user.workspace_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="审批请求不存在")
    return item


def _audit(
    db: Session,
    user: User,
    item: ApprovalRequest,
    action: str,
    after: dict[str, Any],
) -> None:
    db.add(
        AuditEvent(
            workspace_id=user.workspace_id,
            actor_type=ActorType.USER,
            actor_id=user.id,
            action=action,
            entity_type="approval_request",
            entity_id=item.id,
            after_json=after,
        )
    )


def _domain_audit(
    db: Session,
    admin: User,
    *,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=admin.workspace_id,
            actor_type=ActorType.USER,
            actor_id=admin.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )


def _provider_state(provider: AIProvider) -> dict[str, Any]:
    return {
        "name": provider.name,
        "protocol": str(provider.protocol),
        "base_url": provider.base_url,
        "model": provider.model,
        "reasoning_effort": str(provider.reasoning_effort),
        "timeout_seconds": provider.timeout_seconds,
        "headers_json": provider.headers_json,
        "capabilities_json": provider.capabilities_json,
        "is_active": provider.is_active,
        "has_api_key": provider.api_key_source != "none",
        "api_key_source": provider.api_key_source,
        "version": provider.version,
    }


def _apply_provider_create(db: Session, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
    configuration = payload.get("configuration")
    if not isinstance(configuration, dict):
        raise HTTPException(status_code=422, detail="AI 供应商创建审批参数不完整")
    try:
        validated = AIProviderCreate.model_validate(
            {
                **configuration,
                "use_environment_api_key": False,
                "probe_before_save": False,
            }
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="AI 供应商创建审批参数无效") from exc

    key_source = configuration.get("api_key_source", "none")
    encrypted_api_key = configuration.get("encrypted_api_key")
    if key_source not in {"none", "database", "environment"}:
        raise HTTPException(status_code=422, detail="AI 供应商密钥来源无效")
    if key_source == "database" and not isinstance(encrypted_api_key, str):
        raise HTTPException(status_code=422, detail="AI 供应商加密密钥缺失")
    if key_source != "database":
        encrypted_api_key = None

    duplicate = db.scalar(
        select(AIProvider.id).where(
            AIProvider.workspace_id == admin.workspace_id,
            AIProvider.name == validated.name.strip(),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="AI 供应商名称已存在")

    provider = AIProvider(
        workspace_id=admin.workspace_id,
        name=validated.name.strip(),
        protocol=validated.protocol,
        base_url=validated.base_url,
        model=validated.model.strip(),
        encrypted_api_key=encrypted_api_key,
        api_key_source=key_source,
        reasoning_effort=validated.reasoning_effort,
        timeout_seconds=validated.timeout_seconds,
        headers_json=validated.headers_json,
        capabilities_json=validated.capabilities_json,
        is_active=validated.is_active,
    )
    db.add(provider)
    db.flush()
    after = _provider_state(provider)
    _domain_audit(
        db,
        admin,
        action="ai.provider.create",
        entity_type="ai_provider",
        entity_id=provider.id,
        before=None,
        after=after,
    )
    return {"provider_id": provider.id, "configuration": after}


def _apply_provider_update(db: Session, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
    provider_id = payload.get("provider_id")
    expected = payload.get("expected")
    changes = payload.get("changes")
    if (
        not isinstance(provider_id, str)
        or not isinstance(expected, dict)
        or not isinstance(changes, dict)
    ):
        raise HTTPException(status_code=422, detail="AI 供应商审批参数不完整")
    provider = db.scalar(
        select(AIProvider).where(
            AIProvider.id == provider_id,
            AIProvider.workspace_id == admin.workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="AI 供应商不存在")
    before = _provider_state(provider)
    if before != expected:
        raise HTTPException(status_code=409, detail="AI 供应商配置已发生变化，请重新申请")

    name = changes.get("name")
    if isinstance(name, str) and name != provider.name:
        duplicate = db.scalar(
            select(AIProvider.id).where(
                AIProvider.workspace_id == admin.workspace_id,
                AIProvider.name == name,
                AIProvider.id != provider.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="AI 供应商名称已存在")

    for field in (
        "name",
        "protocol",
        "base_url",
        "model",
        "reasoning_effort",
        "timeout_seconds",
        "headers_json",
        "capabilities_json",
        "is_active",
        "api_key_source",
    ):
        if field in changes:
            setattr(provider, field, changes[field])
    if changes.get("clear_api_key") is True:
        provider.encrypted_api_key = None
        provider.api_key_source = "none"
    if changes.get("clear_encrypted_api_key") is True:
        provider.encrypted_api_key = None
    encrypted_api_key = changes.get("encrypted_api_key")
    if isinstance(encrypted_api_key, str):
        provider.encrypted_api_key = encrypted_api_key
        provider.api_key_source = "database"
    provider.version += 1
    db.flush()
    after = _provider_state(provider)
    _domain_audit(
        db,
        admin,
        action="ai.provider.update",
        entity_type="ai_provider",
        entity_id=provider.id,
        before=before,
        after=after,
    )
    return {"provider_id": provider.id, "configuration": after}


def _apply_provider_delete(db: Session, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
    provider_id = payload.get("provider_id")
    expected = payload.get("expected")
    if not isinstance(provider_id, str) or not isinstance(expected, dict):
        raise HTTPException(status_code=422, detail="AI 供应商删除审批参数不完整")
    provider = db.scalar(
        select(AIProvider).where(
            AIProvider.id == provider_id,
            AIProvider.workspace_id == admin.workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="AI 供应商不存在")
    before = _provider_state(provider)
    if before != expected:
        raise HTTPException(status_code=409, detail="AI 供应商配置已发生变化，请重新申请")
    if db.scalar(select(AIRun.id).where(AIRun.provider_id == provider.id)) is not None:
        raise HTTPException(
            status_code=409,
            detail="该供应商已有运行记录，请改为申请停用",
        )
    _domain_audit(
        db,
        admin,
        action="ai.provider.delete",
        entity_type="ai_provider",
        entity_id=provider.id,
        before=before,
        after=None,
    )
    db.delete(provider)
    db.flush()
    return {"provider_id": provider.id, "deleted": True}


def _apply_ai_settings_update(db: Session, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
    expected_version = payload.get("expected_version")
    changes = payload.get("changes")
    if not isinstance(expected_version, int) or not isinstance(changes, dict):
        raise HTTPException(status_code=422, detail="AI 设置审批参数不完整")
    settings = db.get(AIWorkspaceSettings, admin.workspace_id)
    if settings is None:
        raise HTTPException(status_code=404, detail="AI 设置不存在")
    before = {
        "agents_md": settings.agents_md,
        "web_access_enabled": settings.web_access_enabled,
        "version": settings.version,
    }
    next_agents_md = changes.get("agents_md", settings.agents_md)
    next_web_access = changes.get("web_access_enabled", settings.web_access_enabled)
    changed = cast(
        CursorResult[Any],
        db.execute(
            update(AIWorkspaceSettings)
            .where(
                AIWorkspaceSettings.workspace_id == admin.workspace_id,
                AIWorkspaceSettings.version == expected_version,
            )
            .values(
                agents_md=next_agents_md,
                web_access_enabled=next_web_access,
                updated_by_id=admin.id,
                version=expected_version + 1,
            )
            .execution_options(synchronize_session=False)
        ),
    )
    if changed.rowcount != 1:
        raise HTTPException(status_code=409, detail="AI 设置已发生变化，请重新申请")
    after = {
        "agents_md": next_agents_md,
        "web_access_enabled": next_web_access,
        "version": expected_version + 1,
    }
    _domain_audit(
        db,
        admin,
        action="ai.settings.update",
        entity_type="ai_workspace_settings",
        entity_id=admin.workspace_id,
        before=before,
        after=after,
    )
    return after


def _apply_manual_fx_rate(db: Session, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        validated = FxRateCreate.model_validate(payload)
        rate_e12 = to_e12(validated.rate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="手工汇率审批参数无效") from exc
    if rate_e12 <= 0:
        raise HTTPException(status_code=422, detail="汇率必须大于 0")
    base_currency = validated.base_currency.upper()
    quote_currency = validated.quote_currency.upper()
    existing = db.scalar(
        select(FxRate.id).where(
            FxRate.base_currency == base_currency,
            FxRate.quote_currency == quote_currency,
            FxRate.effective_at == validated.effective_at,
            FxRate.source == validated.source,
            FxRate.rate_type == validated.rate_type,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="相同来源的汇率快照已存在")
    rate = FxRate(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate_e12=rate_e12,
        effective_at=validated.effective_at,
        source=validated.source,
        rate_type=validated.rate_type,
    )
    db.add(rate)
    db.flush()
    after = {
        "base_currency": base_currency,
        "quote_currency": quote_currency,
        "rate": validated.rate,
        "effective_at": validated.effective_at.isoformat(),
        "source": validated.source,
        "rate_type": validated.rate_type,
    }
    _domain_audit(
        db,
        admin,
        action="fx_rate.create.manual",
        entity_type="fx_rate",
        entity_id=rate.id,
        before=None,
        after=after,
    )
    return {"fx_rate_id": rate.id, **after}


def _user_state(user: User) -> dict[str, Any]:
    return {
        "username": user.username,
        "email": user.email,
        "display_name": user.display_name,
        "role": str(user.role),
        "is_active": user.is_active,
    }


def _apply_user_permissions(db: Session, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = payload.get("user_id")
    expected = payload.get("expected")
    changes = payload.get("changes")
    if (
        not isinstance(user_id, str)
        or not isinstance(expected, dict)
        or not isinstance(changes, dict)
    ):
        raise HTTPException(status_code=422, detail="用户权限审批参数不完整")
    target = db.scalar(
        select(User).where(User.id == user_id, User.workspace_id == admin.workspace_id)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="用户不存在")
    before = _user_state(target)
    if any(before.get(key) != value for key, value in expected.items()):
        raise HTTPException(status_code=409, detail="用户资料已发生变化，请重新申请")
    if target.id == admin.id and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="不能停用当前账号")

    next_role = UserRole(changes.get("role", str(target.role)))
    next_active = changes.get("is_active", target.is_active)
    removes_active_admin = (
        target.is_active
        and UserRole(target.role) == UserRole.ADMIN
        and (next_role != UserRole.ADMIN or next_active is False)
    )
    if removes_active_admin:
        active_admins = db.scalar(
            select(User.id).where(
                User.workspace_id == admin.workspace_id,
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
                User.id != target.id,
            )
        )
        if active_admins is None:
            raise HTTPException(status_code=409, detail="必须保留至少一名有效管理员")

    if "username" in changes:
        target.username = str(changes["username"]).strip()
        target.display_name = target.username
    elif "display_name" in changes:
        target.display_name = str(changes["display_name"]).strip()
    if "email" in changes:
        target.email = str(changes["email"]).strip().lower()
    target.role = next_role
    target.is_active = bool(next_active)
    if not target.is_active:
        revoke_user_sessions(db, target.id)
    db.flush()
    after = _user_state(target)
    _domain_audit(
        db,
        admin,
        action="user.permissions.update",
        entity_type="user",
        entity_id=target.id,
        before=before,
        after=after,
    )
    return {"user_id": target.id, **after}


@router.get("", response_model=list[ApprovalRequestRead])
def list_approvals(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    approval_status: ApprovalStatus | None = None,
) -> list[ApprovalRequestRead]:
    statement = (
        select(ApprovalRequest)
        .where(ApprovalRequest.workspace_id == user.workspace_id)
        .order_by(ApprovalRequest.created_at.desc())
    )
    if approval_status is not None:
        statement = statement.where(ApprovalRequest.status == approval_status)
    return [approval_view(item) for item in db.scalars(statement)]


@router.get("/{approval_id}", response_model=ApprovalRequestRead)
def get_approval(
    approval_id: str,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalRequestRead:
    return approval_view(_approval(db, user, approval_id))


def _execute_approved_action(db: Session, admin: User, item: ApprovalRequest) -> dict[str, Any]:
    if item.kind == "config.ai_provider.create":
        return _apply_provider_create(db, admin, item.payload_json)
    if item.kind == "config.ai_provider.update":
        return _apply_provider_update(db, admin, item.payload_json)
    if item.kind == "config.ai_provider.delete":
        return _apply_provider_delete(db, admin, item.payload_json)
    if item.kind == "config.ai_settings.update":
        return _apply_ai_settings_update(db, admin, item.payload_json)
    if item.kind == "config.fx_rate.create_manual":
        return _apply_manual_fx_rate(db, admin, item.payload_json)
    if item.kind == "config.user_permissions.update":
        return _apply_user_permissions(db, admin, item.payload_json)
    if item.kind == "record.reverse":
        arguments = item.payload_json
    elif item.kind == "ai_tool:reverse_posted_record":
        arguments = item.payload_json.get("arguments", {})
    else:
        raise HTTPException(status_code=409, detail="该审批类型尚未配置执行器")
    record_id = arguments.get("record_id")
    reason = arguments.get("reason")
    if not isinstance(record_id, str) or not isinstance(reason, str) or not reason.strip():
        raise HTTPException(status_code=422, detail="冲正审批参数不完整")
    record = db.scalar(
        select(BusinessRecord)
        .options(selectinload(BusinessRecord.amounts))
        .where(
            BusinessRecord.id == record_id,
            BusinessRecord.workspace_id == admin.workspace_id,
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="待冲正记录不存在")
    try:
        reversal = reverse_record(
            db,
            record,
            actor_id=admin.id,
            actor_type=ActorType.USER,
            reason=reason,
            commit=False,
        )
    except AccountingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"reversal_record_id": reversal.id}


@router.post("/{approval_id}/approve", response_model=ApprovalRequestRead)
def approve_request(
    approval_id: str,
    payload: ApprovalDecision,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalRequestRead:
    claimed = cast(
        CursorResult[Any],
        db.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.workspace_id == admin.workspace_id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
            .values(status=ApprovalStatus.PROCESSING)
            .execution_options(synchronize_session=False)
        ),
    )
    if claimed.rowcount != 1:
        db.rollback()
        _approval(db, admin, approval_id)
        raise HTTPException(status_code=409, detail="审批请求已经处理")
    db.expire_all()
    item = _approval(db, admin, approval_id)
    try:
        result = _execute_approved_action(db, admin, item)
        item.status = ApprovalStatus.APPROVED
        item.decided_by_id = admin.id
        item.decided_at = datetime.now(UTC)
        item.reason = payload.reason
        _audit(db, admin, item, "approval.approve", result)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="批准操作与当前数据冲突") from exc
    db.refresh(item)
    return approval_view(item)


@router.post("/{approval_id}/reject", response_model=ApprovalRequestRead)
def reject_request(
    approval_id: str,
    payload: ApprovalDecision,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalRequestRead:
    rejected = cast(
        CursorResult[Any],
        db.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.id == approval_id,
                ApprovalRequest.workspace_id == admin.workspace_id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
            .values(
                status=ApprovalStatus.REJECTED,
                decided_by_id=admin.id,
                decided_at=datetime.now(UTC),
                reason=payload.reason,
            )
            .execution_options(synchronize_session=False)
        ),
    )
    if rejected.rowcount != 1:
        db.rollback()
        _approval(db, admin, approval_id)
        raise HTTPException(status_code=409, detail="审批请求已经处理")
    db.expire_all()
    item = _approval(db, admin, approval_id)
    _audit(db, admin, item, "approval.reject", {"reason": payload.reason})
    db.commit()
    db.refresh(item)
    return approval_view(item)
