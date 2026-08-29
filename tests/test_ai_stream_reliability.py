from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.schemas import AiRequest, AiToolLoopResponse
from app.api.ai import _claim_interrupted_run, run_ai, run_ai_stream
from app.config import Settings
from app.dependencies import AuthContext
from app.enums import AIMode, AIProtocol, AIStatus, ReasoningEffort, UserRole
from app.models import AIProvider, AIRun, BusinessRecord, JournalEntry, User, Workspace


def _user_and_provider(
    session: Session, workspace: Workspace, *, suffix: str
) -> tuple[User, AIProvider]:
    user = User(
        workspace_id=workspace.id,
        username=f"AI tester {suffix}",
        email=f"ai-{suffix}@example.test",
        display_name="AI tester",
        password_hash="not-used",
        role=UserRole.ADMIN,
        is_active=True,
    )
    provider = AIProvider(
        workspace_id=workspace.id,
        name=f"AI provider {suffix}",
        protocol=AIProtocol.RESPONSES,
        base_url="https://example.test/v1",
        model="mock-model",
        reasoning_effort=ReasoningEffort.MEDIUM,
    )
    session.add_all([user, provider])
    session.commit()
    return user, provider


@pytest.mark.asyncio
async def test_nonstream_idempotency_reuses_the_persisted_read_result(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Workspace,
) -> None:
    user, provider = _user_and_provider(db_session, workspace, suffix="nonstream")
    calls = 0

    async def fake_complete(*_args: Any, **_kwargs: Any) -> AiToolLoopResponse:
        nonlocal calls
        calls += 1
        return AiToolLoopResponse(
            response_id="response-1",
            text="结果",
            provider_rounds=1,
            tool_rounds=0,
            stop_reason="final_response",
        )

    monkeypatch.setattr("app.api.ai.complete_with_tool_loop", fake_complete)
    payload = AiRequest(messages=[{"role": "user", "content": "查询本月经营概览"}])
    settings = Settings(app_env="test", app_secret_key="unit-test-application-secret")
    first = await run_ai(
        provider.id,
        payload,
        user,
        cast(AuthContext, None),
        db_session,
        settings,
        "same-key",
    )
    second = await run_ai(
        provider.id,
        payload,
        user,
        cast(AuthContext, None),
        db_session,
        settings,
        "same-key",
    )

    assert second == first
    assert calls == 1
    assert db_session.scalar(select(func.count()).select_from(AIRun)) == 1


@pytest.mark.asyncio
async def test_legacy_edit_endpoints_reject_before_provider_or_database_write(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Workspace,
) -> None:
    user, provider = _user_and_provider(db_session, workspace, suffix="legacy-edit")
    provider_calls = 0

    async def must_not_run(*_args: Any, **_kwargs: Any) -> AiToolLoopResponse:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("legacy edit must be rejected before provider execution")

    monkeypatch.setattr("app.api.ai.complete_with_tool_loop", must_not_run)
    payload = AiRequest(
        mode=AIMode.EDIT,
        messages=[{"role": "user", "content": "记录费用"}],
        stream=False,
    )
    settings = Settings(app_env="test", app_secret_key="unit-test-application-secret")

    with pytest.raises(HTTPException) as nonstream:
        await run_ai(
            provider.id,
            payload,
            user,
            cast(AuthContext, None),
            db_session,
            settings,
            "legacy-nonstream",
        )
    with pytest.raises(HTTPException) as stream:
        await run_ai_stream(
            provider.id,
            payload.model_copy(update={"stream": True}),
            user,
            cast(AuthContext, None),
            db_session,
            settings,
            "legacy-stream",
        )

    assert nonstream.value.status_code == 409
    assert stream.value.status_code == 409
    assert provider_calls == 0
    assert db_session.scalar(select(func.count()).select_from(AIRun)) == 0
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 0


def test_interrupted_run_resume_uses_single_winner_compare_and_swap(
    db_session: Session, workspace: Workspace
) -> None:
    user, provider = _user_and_provider(db_session, workspace, suffix="resume-cas")
    run = AIRun(
        workspace_id=workspace.id,
        provider_id=provider.id,
        mode=AIMode.CHAT,
        tool_scope="ledger",
        status=AIStatus.FAILED,
        model=provider.model,
        reasoning_effort=provider.reasoning_effort,
        created_by_id=user.id,
        operation="ai.run.stream",
        idempotency_key="resume-cas-key",
        request_hash="resume-cas-hash",
        error="AI 客户端连接已中断",
    )
    db_session.add(run)
    db_session.commit()

    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    with factory() as first, factory() as second:
        assert _claim_interrupted_run(first, run.id) is True
        assert _claim_interrupted_run(second, run.id) is False

    db_session.expire_all()
    persisted = db_session.get(AIRun, run.id)
    assert persisted is not None
    assert AIStatus(persisted.status) == AIStatus.RUNNING
    assert persisted.error is None
