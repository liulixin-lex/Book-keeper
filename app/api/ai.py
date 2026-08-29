from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.adapters import ProviderRuntime, adapter_for
from app.ai.adapters.base import AIProviderRequestError
from app.ai.crypto import SecretDecryptionError, decrypt_api_key, encrypt_api_key
from app.ai.executor import SQLDomainToolExecutor
from app.ai.schemas import (
    AiEvent,
    AiEventType,
    AIProviderCreate,
    AIProviderTestResult,
    AIProviderUpdate,
    AIProviderView,
    AiRequest,
    AiToolCall,
    AiToolLoopResponse,
    AIWorkspaceSettingsPatch,
    AIWorkspaceSettingsView,
)
from app.ai.service import (
    complete_with_tool_loop,
    load_default_agents_md,
    runtime_from_provider,
    stream_with_tool_loop,
)
from app.ai.tools import canonical_tool_signature
from app.api.approvals import request_approval
from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import AuthContext, require_admin, require_csrf, require_viewer
from app.enums import ActorType, AIMode, AIStatus
from app.models import (
    AIProvider,
    AIRun,
    AIToolCall,
    AIWorkspaceSettings,
    AuditEvent,
    User,
)
from app.schemas import ApprovalRequestRead
from app.services.idempotency import request_digest

router = APIRouter(prefix="/ai", tags=["ai"])


class AiRunResult(AiToolLoopResponse):
    run_id: str


def _provider_or_404(db: Session, provider_id: str, workspace_id: str) -> AIProvider:
    provider = db.scalar(
        select(AIProvider).where(
            AIProvider.id == provider_id,
            AIProvider.workspace_id == workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI 供应商不存在")
    return provider


def _provider_view(provider: AIProvider) -> AIProviderView:
    return AIProviderView(
        id=provider.id,
        workspace_id=provider.workspace_id,
        name=provider.name,
        protocol=provider.protocol,
        base_url=provider.base_url,
        model=provider.model,
        reasoning_effort=provider.reasoning_effort,
        timeout_seconds=provider.timeout_seconds,
        headers_json=provider.headers_json,
        capabilities_json=provider.capabilities_json,
        is_active=provider.is_active,
        version=provider.version,
        has_api_key=provider.api_key_source != "none",
        api_key_source=provider.api_key_source,
        last_tested_at=provider.last_tested_at,
        last_test_status=provider.last_test_status,
        last_test_error=provider.last_test_error,
    )


def _provider_approval_state(provider: AIProvider) -> dict[str, Any]:
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


def _workspace_settings(db: Session, workspace_id: str) -> AIWorkspaceSettings:
    workspace_settings = db.get(AIWorkspaceSettings, workspace_id)
    if workspace_settings is None:
        workspace_settings = AIWorkspaceSettings(
            workspace_id=workspace_id,
            agents_md=load_default_agents_md(),
            web_access_enabled=False,
        )
        db.add(workspace_settings)
        db.flush()
    return workspace_settings


def _audit(
    db: Session,
    *,
    actor: User,
    action: str,
    entity_type: str,
    entity_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=actor.workspace_id,
            actor_type=ActorType.USER,
            actor_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before_json=before,
            after_json=after,
        )
    )


def _check_mode_permission(user: User, mode: AIMode) -> None:
    del user
    if mode == AIMode.EDIT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Edit 直写已停用，请使用斜杠命令工作流生成、校验并确认提案",
        )


async def _probe_provider_runtime(runtime: ProviderRuntime) -> None:
    adapter = adapter_for(runtime)
    await adapter.complete(
        AiRequest(
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_output_tokens=8,
        ),
        system_prompt="Return only OK.",
        tools=(),
        enable_web_search=False,
    )


def _runtime_for_candidate(
    provider: AIProvider,
    payload: AIProviderUpdate,
    settings: Settings,
) -> ProviderRuntime:
    api_key: str | None = None
    if provider.encrypted_api_key:
        api_key = decrypt_api_key(provider.encrypted_api_key, settings.app_secret_key)
    elif provider.api_key_source == "environment":
        api_key = settings.openai_api_key
    if payload.api_key is not None:
        api_key = payload.api_key.get_secret_value()
    elif payload.use_environment_api_key is True:
        api_key = settings.openai_api_key
    elif payload.use_environment_api_key is False or payload.clear_api_key:
        api_key = None
    return ProviderRuntime(
        protocol=payload.protocol or provider.protocol,
        base_url=payload.base_url or provider.base_url,
        model=(payload.model or provider.model).strip(),
        api_key=api_key,
        reasoning_effort=str(payload.reasoning_effort or provider.reasoning_effort),
        timeout_seconds=payload.timeout_seconds or provider.timeout_seconds,
        custom_headers=(
            payload.headers_json if payload.headers_json is not None else provider.headers_json
        ),
        capabilities=(
            payload.capabilities_json
            if payload.capabilities_json is not None
            else provider.capabilities_json
        ),
    )


def _run_request_hash(provider: AIProvider, request: AiRequest) -> str:
    return request_digest(
        {
            "provider_id": provider.id,
            "request": request.model_dump(mode="json"),
        }
    )


def _new_or_existing_run(
    db: Session,
    provider: AIProvider,
    user: User,
    request: AiRequest,
    *,
    operation: str,
    idempotency_key: str | None,
) -> tuple[AIRun, bool]:
    key = idempotency_key.strip() if idempotency_key else None
    digest = _run_request_hash(provider, request)
    if key:
        existing = db.scalar(
            select(AIRun).where(
                AIRun.workspace_id == user.workspace_id,
                AIRun.created_by_id == user.id,
                AIRun.operation == operation,
                AIRun.idempotency_key == key,
            )
        )
        if existing is not None:
            if existing.request_hash != digest:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="同一 Idempotency-Key 不能用于不同 AI 请求",
                )
            return existing, True

    run = AIRun(
        workspace_id=user.workspace_id,
        provider_id=provider.id,
        mode=request.mode,
        tool_scope="ledger",
        status=AIStatus.RUNNING,
        model=provider.model,
        reasoning_effort=provider.reasoning_effort,
        created_by_id=user.id,
        operation=operation,
        idempotency_key=key,
        request_hash=digest,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if not key:
            raise
        existing = db.scalar(
            select(AIRun).where(
                AIRun.workspace_id == user.workspace_id,
                AIRun.created_by_id == user.id,
                AIRun.operation == operation,
                AIRun.idempotency_key == key,
            )
        )
        if existing is None:
            raise
        if existing.request_hash != digest:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="同一 Idempotency-Key 不能用于不同 AI 请求",
            ) from exc
        return existing, True
    db.refresh(run)
    return run, False


def _sse(event: AiEvent) -> str:
    return f"event: {event.type.value}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"


def _execute_tool_in_short_session(
    factory: sessionmaker[Session],
    *,
    user_id: str,
    run_id: str,
    call: AiToolCall,
    resume_write_signatures: frozenset[str] | None = None,
) -> dict[str, Any]:
    with factory() as tool_db:
        run = tool_db.get(AIRun, run_id)
        user = tool_db.get(User, user_id)
        if run is None or user is None:
            return {"ok": False, "error": "ai_run_context_not_found"}
        return SQLDomainToolExecutor(
            tool_db,
            user,
            run,
            defer_writes=True,
            resume_write_signatures=resume_write_signatures,
        ).execute(call)


def _actual_tool_results(db: Session, run_id: str) -> dict[str, dict[str, Any]]:
    return {
        row.signature: row.result_json
        for row in db.scalars(
            select(AIToolCall).where(
                AIToolCall.run_id == run_id,
                AIToolCall.status.in_(("completed", "pending_approval")),
            )
        )
    }


def _replace_deferred_response_results(
    result: dict[str, Any] | None,
    actual_results: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if result is None:
        return None
    updated = deepcopy(result)
    for item in updated.get("tool_results", []):
        if not isinstance(item, dict) or item.get("duplicate") is True:
            continue
        placeholder = item.get("result")
        tool_call = item.get("tool_call")
        if not isinstance(placeholder, dict) or placeholder.get("status") != "deferred":
            continue
        if not isinstance(tool_call, dict):
            continue
        arguments = tool_call.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        signature = canonical_tool_signature(
            str(tool_call.get("name") or ""),
            arguments,
        )
        actual = actual_results.get(signature)
        if actual is not None:
            item["result"] = actual
    return updated


def _replace_deferred_event_results(
    events: list[dict[str, Any]] | None,
    actual_results: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, list[AiEvent]]:
    if events is None:
        return None, []
    updated: list[dict[str, Any]] = []
    committed_events: list[AiEvent] = []
    replaced_signatures: set[str] = set()
    for source in events:
        item = deepcopy(source)
        if item.get("type") == AiEventType.TOOL_RESULT:
            placeholder = item.get("result")
            tool_call = item.get("tool_call")
            if (
                isinstance(placeholder, dict)
                and placeholder.get("status") == "deferred"
                and isinstance(tool_call, dict)
            ):
                arguments = tool_call.get("arguments")
                if not isinstance(arguments, dict):
                    arguments = {}
                signature = canonical_tool_signature(
                    str(tool_call.get("name") or ""),
                    arguments,
                )
                actual = actual_results.get(signature)
                if actual is not None:
                    if signature in replaced_signatures:
                        continue
                    replaced_signatures.add(signature)
                    item["result"] = actual
                    committed_events.append(AiEvent.model_validate(item))
        updated.append(item)
    return updated, committed_events


def _complete_run_with_deferred_writes(
    factory: sessionmaker[Session],
    run_id: str,
    *,
    user_id: str,
    final_text: str,
    usage: dict[str, Any],
    result: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    required_replayed_signatures: set[str] | None = None,
    resume_write_mismatch: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[AiEvent]]:
    """Atomically apply staged domain writes and mark the AI run completed."""
    with factory() as final_db:
        try:
            run = final_db.get(AIRun, run_id)
            user = final_db.get(User, user_id)
            if run is None or user is None:
                raise ValueError("AI run context is no longer available")
            if AIStatus(run.status) != AIStatus.RUNNING:
                raise ValueError("AI run is not active")
            if resume_write_mismatch:
                raise ValueError("A resumed AI run introduced a different write command")
            if required_replayed_signatures:
                raise ValueError("A resumed AI run did not replay every staged write command")
            has_deferred_writes = (
                final_db.scalar(
                    select(AIToolCall.id)
                    .where(
                        AIToolCall.run_id == run_id,
                        AIToolCall.status == "deferred",
                    )
                    .limit(1)
                )
                is not None
            )
            if has_deferred_writes and not final_text.strip():
                raise ValueError("AI did not produce a final response for staged writes")
            SQLDomainToolExecutor(final_db, user, run).finalize_deferred()
            actual_results = _actual_tool_results(final_db, run_id)
            final_result = _replace_deferred_response_results(result, actual_results)
            final_events, committed_events = _replace_deferred_event_results(events, actual_results)
            run.status = AIStatus.COMPLETED
            run.usage_json = usage
            if final_result is not None:
                run.result_json = final_result
            if final_events is not None:
                run.event_log_json = final_events
            run.error = None
            run.completed_at = datetime.now(UTC)
            final_db.commit()
            return final_result, final_events, committed_events
        except Exception:
            final_db.rollback()
            raise


def _save_run_result(
    factory: sessionmaker[Session],
    run_id: str,
    *,
    status_value: AIStatus,
    usage: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    with factory() as run_db:
        run = run_db.get(AIRun, run_id)
        if run is None:
            return
        run.status = status_value
        if usage is not None:
            run.usage_json = usage
        if result is not None:
            run.result_json = result
        if events is not None:
            run.event_log_json = events
        run.error = error
        run.completed_at = (
            datetime.now(UTC) if status_value in {AIStatus.COMPLETED, AIStatus.FAILED} else None
        )
        run_db.commit()


def _claim_interrupted_run(db: Session, run_id: str) -> bool:
    claimed = db.connection().execute(
        update(AIRun)
        .where(
            AIRun.id == run_id,
            AIRun.status == AIStatus.FAILED,
            AIRun.error == "AI 客户端连接已中断",
        )
        .values(status=AIStatus.RUNNING, error=None, completed_at=None)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    return True


@router.get("/providers", response_model=list[AIProviderView])
def list_providers(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AIProviderView]:
    providers = db.scalars(
        select(AIProvider)
        .where(AIProvider.workspace_id == admin.workspace_id)
        .order_by(AIProvider.created_at, AIProvider.id)
    )
    return [_provider_view(provider) for provider in providers]


@router.get("/providers/{provider_id}", response_model=AIProviderView)
def get_provider(
    provider_id: str,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> AIProviderView:
    return _provider_view(_provider_or_404(db, provider_id, admin.workspace_id))


@router.post(
    "/providers",
    response_model=ApprovalRequestRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_provider(
    payload: AIProviderCreate,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApprovalRequestRead:
    api_key = payload.api_key.get_secret_value() if payload.api_key else None
    runtime_api_key = settings.openai_api_key if payload.use_environment_api_key else api_key
    if payload.probe_before_save:
        try:
            await _probe_provider_runtime(
                ProviderRuntime(
                    protocol=payload.protocol,
                    base_url=payload.base_url,
                    model=payload.model.strip(),
                    api_key=runtime_api_key,
                    reasoning_effort=str(payload.reasoning_effort),
                    timeout_seconds=payload.timeout_seconds,
                    custom_headers=payload.headers_json,
                    capabilities=payload.capabilities_json,
                )
            )
        except (AIProviderRequestError, SecretDecryptionError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="AI 供应商能力探测失败，配置未保存",
            ) from exc
    name = payload.name.strip()
    if db.scalar(
        select(AIProvider.id).where(
            AIProvider.workspace_id == admin.workspace_id,
            AIProvider.name == name,
        )
    ):
        raise HTTPException(status_code=409, detail="AI 供应商名称已存在")

    configuration = payload.model_dump(
        mode="json",
        exclude={"api_key", "use_environment_api_key", "probe_before_save"},
    )
    configuration["name"] = name
    configuration["model"] = payload.model.strip()
    configuration["api_key_source"] = (
        "database" if api_key else "environment" if payload.use_environment_api_key else "none"
    )
    if api_key:
        configuration["encrypted_api_key"] = encrypt_api_key(api_key, settings.app_secret_key)
    return request_approval(
        db,
        requester=admin,
        kind="config.ai_provider.create",
        payload={"configuration": configuration},
    )


@router.patch(
    "/providers/{provider_id}",
    response_model=ApprovalRequestRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_provider(
    provider_id: str,
    payload: AIProviderUpdate,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ApprovalRequestRead:
    provider = _provider_or_404(db, provider_id, admin.workspace_id)
    if payload.probe_before_save:
        try:
            await _probe_provider_runtime(_runtime_for_candidate(provider, payload, settings))
        except (AIProviderRequestError, SecretDecryptionError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="AI 供应商能力探测失败，变更未提交审批",
            ) from exc
    changes = payload.model_dump(
        mode="json",
        exclude={"api_key", "use_environment_api_key"},
        exclude_unset=True,
    )
    for field in ("name", "model"):
        value = changes.get(field)
        if isinstance(value, str):
            changes[field] = value.strip()
    if "api_key" in payload.model_fields_set and payload.api_key is not None:
        changes["encrypted_api_key"] = encrypt_api_key(
            payload.api_key.get_secret_value(), settings.app_secret_key
        )
        changes["api_key_source"] = "database"
    if payload.use_environment_api_key is True:
        changes["api_key_source"] = "environment"
        changes["clear_encrypted_api_key"] = True
    elif payload.use_environment_api_key is False:
        changes["api_key_source"] = "none"
        changes["clear_encrypted_api_key"] = True
    if payload.clear_api_key:
        changes["api_key_source"] = "none"
    if changes.get("clear_api_key") is False:
        changes.pop("clear_api_key")
    if not changes:
        raise HTTPException(status_code=422, detail="没有可申请的 AI 供应商变更")
    return request_approval(
        db,
        requester=admin,
        kind="config.ai_provider.update",
        payload={
            "provider_id": provider.id,
            "expected": _provider_approval_state(provider),
            "changes": changes,
        },
    )


@router.delete(
    "/providers/{provider_id}",
    response_model=ApprovalRequestRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_provider(
    provider_id: str,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalRequestRead:
    provider = _provider_or_404(db, provider_id, admin.workspace_id)
    return request_approval(
        db,
        requester=admin,
        kind="config.ai_provider.delete",
        payload={
            "provider_id": provider.id,
            "expected": _provider_approval_state(provider),
        },
    )


@router.post("/providers/{provider_id}/test", response_model=AIProviderTestResult)
async def test_provider(
    provider_id: str,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AIProviderTestResult:
    provider = _provider_or_404(db, provider_id, admin.workspace_id)
    started = perf_counter()
    error: str | None = None
    ok = False
    try:
        runtime = runtime_from_provider(provider, settings.app_secret_key, settings.openai_api_key)
        adapter = adapter_for(runtime)
        await adapter.complete(
            AiRequest(
                messages=[{"role": "user", "content": "Reply with OK."}],
                max_output_tokens=8,
            ),
            system_prompt="Return a short plain-text response.",
            tools=(),
            enable_web_search=False,
        )
        ok = True
    except (AIProviderRequestError, SecretDecryptionError, ValueError):
        error = "连接或协议测试失败"
    latency_ms = round((perf_counter() - started) * 1000)
    provider.last_tested_at = datetime.now(UTC)
    provider.last_test_status = "ok" if ok else "failed"
    provider.last_test_error = error
    _audit(
        db,
        actor=admin,
        action="ai.provider.test",
        entity_type="ai_provider",
        entity_id=provider.id,
        after={"ok": ok, "latency_ms": latency_ms},
    )
    db.commit()
    return AIProviderTestResult(
        ok=ok,
        provider_id=provider.id,
        model=provider.model,
        latency_ms=latency_ms,
        error=error,
    )


@router.get("/settings", response_model=AIWorkspaceSettingsView)
def get_ai_settings(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> AIWorkspaceSettingsView:
    workspace_settings = _workspace_settings(db, user.workspace_id)
    db.commit()
    return AIWorkspaceSettingsView(
        agents_md=workspace_settings.agents_md,
        web_access_enabled=workspace_settings.web_access_enabled,
        version=workspace_settings.version,
    )


@router.patch(
    "/settings",
    response_model=ApprovalRequestRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def update_ai_settings(
    payload: AIWorkspaceSettingsPatch,
    admin: Annotated[User, Depends(require_admin)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
) -> ApprovalRequestRead:
    workspace_settings = _workspace_settings(db, admin.workspace_id)
    if workspace_settings.version != payload.version:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI 设置已被其他用户更新")
    changes: dict[str, Any] = {}
    if payload.agents_md is not None:
        changes["agents_md"] = payload.agents_md.strip()
    if payload.web_access_enabled is not None:
        changes["web_access_enabled"] = payload.web_access_enabled
    return request_approval(
        db,
        requester=admin,
        kind="config.ai_settings.update",
        payload={"expected_version": payload.version, "changes": changes},
    )


@router.post("/providers/{provider_id}/run", response_model=AiRunResult)
async def run_ai(
    provider_id: str,
    payload: AiRequest,
    user: Annotated[User, Depends(require_viewer)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=240)] = None,
) -> AiRunResult:
    _check_mode_permission(user, payload.mode)
    provider = _provider_or_404(db, provider_id, user.workspace_id)
    if not provider.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI 供应商已停用")
    workspace_settings = _workspace_settings(db, user.workspace_id)
    run, reused = _new_or_existing_run(
        db,
        provider,
        user,
        payload,
        operation="ai.run",
        idempotency_key=idempotency_key,
    )
    if reused:
        if run.result_json:
            return AiRunResult.model_validate(run.result_json)
        if AIStatus(run.status) == AIStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=run.error or "AI 请求失败",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="相同 AI 请求正在处理中",
        )
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False)
    try:
        result = await complete_with_tool_loop(
            provider,
            workspace_settings,
            payload,
            application_secret=settings.app_secret_key,
            environment_api_key=settings.openai_api_key,
            execute_tool=lambda call: _execute_tool_in_short_session(
                factory,
                user_id=user.id,
                run_id=run.id,
                call=call,
            ),
        )
    except (AIProviderRequestError, SecretDecryptionError, ValueError) as exc:
        _save_run_result(
            factory,
            run.id,
            status_value=AIStatus.FAILED,
            error="AI 请求失败",
        )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 请求失败") from exc
    response = AiRunResult(run_id=run.id, **result.model_dump())
    try:
        final_result, _, _ = _complete_run_with_deferred_writes(
            factory,
            run.id,
            user_id=user.id,
            final_text=result.text,
            usage=result.usage,
            result=response.model_dump(mode="json"),
        )
    except Exception as exc:
        _save_run_result(
            factory,
            run.id,
            status_value=AIStatus.FAILED,
            error="AI 写入未提交",
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AI 写入校验失败，本轮业务修改未提交",
        ) from exc
    if final_result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI 运行结果未保存",
        )
    return AiRunResult.model_validate(final_result)


@router.post("/providers/{provider_id}/run/stream")
async def run_ai_stream(
    provider_id: str,
    payload: AiRequest,
    user: Annotated[User, Depends(require_viewer)],
    _csrf: Annotated[AuthContext, Depends(require_csrf)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", max_length=240)] = None,
) -> StreamingResponse:
    _check_mode_permission(user, payload.mode)
    provider = _provider_or_404(db, provider_id, user.workspace_id)
    if not provider.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="AI 供应商已停用")
    workspace_settings = _workspace_settings(db, user.workspace_id)
    run, reused = _new_or_existing_run(
        db,
        provider,
        user,
        payload,
        operation="ai.run.stream",
        idempotency_key=idempotency_key,
    )
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False, autoflush=False)

    replay_before_resume: list[dict[str, Any]] = []
    resume_write_signatures: frozenset[str] | None = None
    required_replayed_signatures: set[str] = set()
    if reused:
        is_interrupted = (
            AIStatus(run.status) == AIStatus.FAILED and run.error == "AI 客户端连接已中断"
        )
        if AIStatus(run.status) == AIStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="相同 AI 流式请求正在处理中",
            )
        if is_interrupted:
            replay_before_resume = list(run.event_log_json)
            prior_calls = list(
                db.scalars(
                    select(AIToolCall).where(
                        AIToolCall.run_id == run.id,
                        AIToolCall.status.in_(("completed", "deferred", "pending_approval")),
                    )
                )
            )
            resume_write_signatures = frozenset(call.signature for call in prior_calls)
            required_replayed_signatures = {
                call.signature for call in prior_calls if call.status == "deferred"
            }
            if not _claim_interrupted_run(db, run.id):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="相同 AI 流式请求已被其他连接恢复",
                )
        else:

            async def replay() -> AsyncIterator[str]:
                for item in run.event_log_json:
                    yield _sse(AiEvent.model_validate(item))

            return StreamingResponse(
                replay(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "X-AI-Run-Id": run.id,
                },
            )

    async def generate() -> AsyncIterator[str]:
        event_log = list(replay_before_resume)
        final_seen = False
        final_text_parts: list[str] = []
        resume_write_mismatch = False

        def execute_stream_tool(call: AiToolCall) -> dict[str, Any]:
            nonlocal resume_write_mismatch
            result = _execute_tool_in_short_session(
                factory,
                user_id=user.id,
                run_id=run.id,
                call=call,
                resume_write_signatures=resume_write_signatures,
            )
            signature = canonical_tool_signature(call.name, call.arguments)
            if signature in required_replayed_signatures:
                required_replayed_signatures.discard(signature)
            if result.get("error") == "resume_write_mismatch":
                resume_write_mismatch = True
            return result

        try:
            for item in replay_before_resume:
                yield _sse(AiEvent.model_validate(item))
            async for event in stream_with_tool_loop(
                provider,
                workspace_settings,
                payload,
                application_secret=settings.app_secret_key,
                environment_api_key=settings.openai_api_key,
                execute_tool=execute_stream_tool,
            ):
                serialized_event = event.model_dump(mode="json", exclude_none=True)
                if event.type == AiEventType.TEXT_DELTA and event.text:
                    final_text_parts.append(event.text)
                if event.type == AiEventType.DONE:
                    completed_log = [*event_log, serialized_event]
                    _, finalized_log, committed_events = _complete_run_with_deferred_writes(
                        factory,
                        run.id,
                        user_id=user.id,
                        final_text="".join(final_text_parts),
                        usage=event.usage or {},
                        events=completed_log,
                        required_replayed_signatures=required_replayed_signatures,
                        resume_write_mismatch=resume_write_mismatch,
                    )
                    event_log = finalized_log or completed_log
                    final_seen = True
                    for committed_event in committed_events:
                        yield _sse(committed_event)
                    yield _sse(event)
                    continue
                event_log.append(serialized_event)
                if event.type == AiEventType.TOOL_RESULT:
                    final_text_parts.clear()
                    _save_run_result(
                        factory,
                        run.id,
                        status_value=AIStatus.RUNNING,
                        events=event_log,
                    )
                elif event.type == AiEventType.ERROR:
                    final_seen = True
                    _save_run_result(
                        factory,
                        run.id,
                        status_value=AIStatus.FAILED,
                        usage=event.usage or {},
                        events=event_log,
                        error="AI 流式请求失败",
                    )
                yield _sse(event)
            if not final_seen:
                raise AIProviderRequestError("AI stream did not produce a final event")
        except asyncio.CancelledError:
            if not final_seen:
                _save_run_result(
                    factory,
                    run.id,
                    status_value=AIStatus.FAILED,
                    events=event_log,
                    error="AI 客户端连接已中断",
                )
            raise
        except Exception:
            event = AiEvent(type=AiEventType.ERROR, error="AI 流式请求失败")
            event_log.append(event.model_dump(mode="json", exclude_none=True))
            _save_run_result(
                factory,
                run.id,
                status_value=AIStatus.FAILED,
                events=event_log,
                error="AI 流式请求失败",
            )
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-AI-Run-Id": run.id,
        },
    )
