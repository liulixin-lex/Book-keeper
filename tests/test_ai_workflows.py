import json
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.commands import is_write_intent, parse_command
from app.ai.schemas import AiRequest, AiResponse, AiToolCall
from app.ai.workflow_schemas import (
    ProposalPatch,
    WorkflowConfirm,
    WorkflowCreate,
    WorkflowGuidanceInput,
)
from app.ai.workflows import (
    WorkflowError,
    _source_text,
    analyze_workflow,
    confirm_workflow,
    create_workflow,
    guide_workflow,
    patch_proposal,
    validate_workflow,
    workflow_view,
)
from app.api.ai import _check_mode_permission
from app.config import Settings
from app.enums import AIMode, AIProtocol, AIWorkflowStatus, ReasoningEffort, UserRole
from app.models import (
    AIProvider,
    ApprovalRequest,
    BusinessRecord,
    Category,
    Counterparty,
    JournalEntry,
    LedgerProposal,
    User,
    Workspace,
)
from app.schemas import IncomeCreate, MoneyInput
from app.services.accounting import AccountingError, create_income


def _bookkeeper(db: Session, workspace: Workspace) -> User:
    user = User(
        workspace_id=workspace.id,
        username="ai-workflow-bookkeeper",
        email="ai-workflow@example.test",
        display_name="AI Workflow Bookkeeper",
        password_hash="not-used-in-unit-test",
        role=UserRole.BOOKKEEPER,
    )
    db.add(user)
    db.commit()
    return user


def _provider(db: Session, workspace: Workspace) -> Counterparty:
    category = db.scalar(
        select(Category).where(
            Category.workspace_id == workspace.id,
            Category.name == "其他支出",
        )
    )
    assert category is not None
    provider = Counterparty(
        workspace_id=workspace.id,
        name="AI Workflow Provider",
        roles_json=["supplier"],
        expense_category_id=category.id,
        metadata_json={},
    )
    db.add(provider)
    db.commit()
    return provider


def _expense_source(provider: Counterparty, *, amount: str = "18.50") -> str:
    return json.dumps(
        {
            "proposals": [
                {
                    "record_type": "expense",
                    "accounting_date": "2026-08-29",
                    "description": "AI workflow unit expense",
                    "currency": "CNY",
                    "gross": None,
                    "cost": amount,
                    "fee": "1.50",
                    "cash": None,
                    "amount_cny": None,
                    "fx_rate": None,
                    "channel": "unit-test",
                    "provider_id": provider.id,
                    "provider_name": provider.name,
                    "category_id": None,
                    "external_id": f"workflow-expense-{amount}",
                    "record_id": None,
                    "reason": None,
                    "source_refs": [],
                }
            ]
        },
        ensure_ascii=False,
    )


class GuidanceAdapter:
    def __init__(self) -> None:
        self.request: AiRequest | None = None
        self.system_prompt = ""

    async def complete(
        self,
        request: AiRequest,
        *,
        system_prompt: str,
        tools: tuple[Any, ...],
        enable_web_search: bool = False,
    ) -> AiResponse:
        del tools, enable_web_search
        self.request = request
        self.system_prompt = system_prompt
        return AiResponse(
            response_id="guidance-response",
            tool_calls=[
                AiToolCall(
                    id="guidance-call",
                    name="submit_workflow_guidance",
                    arguments={
                        "reply": "资料中的金额可以识别，但日期仍需确认。",
                        "clarifying_questions": ["这笔支出发生在哪一天？"],
                    },
                )
            ],
        )


@pytest.mark.asyncio
async def test_guidance_is_structured_and_assistant_reply_is_not_extraction_evidence(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    ai_provider = AIProvider(
        workspace_id=workspace.id,
        name="Guidance provider",
        protocol=AIProtocol.RESPONSES,
        base_url="https://example.test/v1",
        model="guidance-model",
        reasoning_effort=ReasoningEffort.MEDIUM,
        timeout_seconds=10,
        headers_json={},
        capabilities_json={},
    )
    db_session.add(ai_provider)
    db_session.commit()
    adapter = GuidanceAdapter()
    monkeypatch.setattr("app.ai.workflows.adapter_for", lambda _runtime: adapter)

    workflow = create_workflow(
        db_session,
        user,
        WorkflowCreate(
            command="/录入支出",
            initial_text="金额：18.50 CNY，摘要：测试资料",
            provider_id=ai_provider.id,
        ),
    )
    guided = await guide_workflow(
        db_session,
        user,
        workflow.id,
        WorkflowGuidanceInput(
            message="请判断当前资料是否还缺字段",
            provider_id=ai_provider.id,
        ),
        Settings(app_env="test", app_secret_key="workflow-test-secret"),
    )
    view = workflow_view(guided)

    assert adapter.request is not None
    assert adapter.request.temperature == 0
    assert adapter.request.required_tool == "submit_workflow_guidance"
    assert "不得声称已经写入" in adapter.system_prompt
    assert "类别由启用的提供商关系确定" in adapter.system_prompt
    assert "不得询问当前系统字段之外的付款账户" in adapter.system_prompt
    assert "外部单号是可选字段" in adapter.system_prompt
    assert "CNY 汇率固定为 1" in adapter.system_prompt
    assert view.input_count == 2
    assert view.attachment_count == 0
    assert [message.role for message in view.messages] == ["user", "assistant"]
    assert view.messages[1].clarifying_questions == ["这笔支出发生在哪一天？"]
    evidence = _source_text(db_session, guided)
    assert "测试资料" in evidence
    assert "请判断当前资料是否还缺字段" in evidence
    assert "资料中的金额可以识别" not in evidence


@pytest.mark.asyncio
async def test_expense_workflow_writes_only_after_confirm_and_replays_idempotently(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    provider = _provider(db_session, workspace)
    workflow = create_workflow(
        db_session,
        user,
        WorkflowCreate(
            command="/录入支出",
            initial_text=_expense_source(provider),
        ),
    )
    await analyze_workflow(
        db_session,
        user,
        workflow.id,
        Settings(app_env="test", app_secret_key="workflow-test-secret"),
    )
    ready = validate_workflow(db_session, user, workflow.id)
    assert AIWorkflowStatus(ready.status) == AIWorkflowStatus.READY
    assert ready.canonical_hash
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 0

    confirmation = WorkflowConfirm(
        workflow_version=ready.version,
        canonical_hash=ready.canonical_hash,
    )
    first = confirm_workflow(db_session, user, workflow.id, confirmation, "expense-confirm-key")
    second = confirm_workflow(db_session, user, workflow.id, confirmation, "expense-confirm-key")
    assert first == second
    assert first["status"] == "committed"
    assert len(first["records"]) == 1
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 1
    assert first["records"][0]["journal_entry_id"]

    with pytest.raises(WorkflowError, match="Idempotency-Key"):
        confirm_workflow(
            db_session,
            user,
            workflow.id,
            confirmation.model_copy(update={"proposal_ids": ["different"]}),
            "expense-confirm-key",
        )


@pytest.mark.asyncio
async def test_proposal_edit_invalidates_ready_snapshot(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    provider = _provider(db_session, workspace)
    workflow = create_workflow(
        db_session,
        user,
        WorkflowCreate(command="/录入支出", initial_text=_expense_source(provider)),
    )
    await analyze_workflow(
        db_session,
        user,
        workflow.id,
        Settings(app_env="test", app_secret_key="workflow-test-secret"),
    )
    ready = validate_workflow(db_session, user, workflow.id)
    old_hash = ready.canonical_hash
    proposal = db_session.scalar(
        select(LedgerProposal).where(LedgerProposal.workflow_id == workflow.id)
    )
    assert proposal is not None
    edited = patch_proposal(
        db_session,
        user,
        workflow.id,
        proposal.id,
        ProposalPatch(expected_version=proposal.version, changes={"description": "Edited"}),
    )
    assert AIWorkflowStatus(edited.status) == AIWorkflowStatus.DRAFT
    assert edited.canonical_hash is None
    with pytest.raises(WorkflowError, match="快照已失效"):
        confirm_workflow(
            db_session,
            user,
            workflow.id,
            WorkflowConfirm(workflow_version=ready.version, canonical_hash=str(old_hash)),
            "stale-confirm-key",
        )


def test_slash_commands_and_legacy_edit_contract(workspace: Workspace, db_session: Session) -> None:
    command, remainder = parse_command("/录入收入 2026-08-29 收入 10 CNY")
    assert command is not None
    assert command.command == "/录入收入"
    assert remainder.startswith("2026-08-29")
    assert parse_command("帮我记一笔支出")[0] is None
    assert is_write_intent("帮我记一笔支出") is True

    user = _bookkeeper(db_session, workspace)
    with pytest.raises(HTTPException) as rejected:
        _check_mode_permission(
            user, AiRequest(mode=AIMode.EDIT, messages=[{"role": "user", "content": "x"}]).mode
        )
    assert rejected.value.status_code == 409


@pytest.mark.asyncio
async def test_batch_confirm_rolls_back_every_record_when_one_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    provider = _provider(db_session, workspace)
    first = json.loads(_expense_source(provider, amount="10.00"))["proposals"][0]
    second = json.loads(_expense_source(provider, amount="20.00"))["proposals"][0]
    workflow = create_workflow(
        db_session,
        user,
        WorkflowCreate(
            command="/批量录入",
            initial_text=json.dumps({"proposals": [first, second]}, ensure_ascii=False),
        ),
    )
    await analyze_workflow(
        db_session,
        user,
        workflow.id,
        Settings(app_env="test", app_secret_key="workflow-test-secret"),
    )
    ready = validate_workflow(db_session, user, workflow.id)
    assert ready.canonical_hash

    from app.ai import workflows as workflow_service

    actual_create = workflow_service.create_expense
    calls = 0

    def fail_second(*args: object, **kwargs: object) -> BusinessRecord:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AccountingError("simulated second-row failure")
        return actual_create(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(workflow_service, "create_expense", fail_second)
    with pytest.raises(AccountingError, match="second-row"):
        confirm_workflow(
            db_session,
            user,
            workflow.id,
            WorkflowConfirm(
                workflow_version=ready.version,
                canonical_hash=ready.canonical_hash,
            ),
            "atomic-batch-key",
        )
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 0


@pytest.mark.asyncio
async def test_reversal_confirmation_creates_approval_without_reversing_record(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _bookkeeper(db_session, workspace)
    original = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date="2026-08-29",
            description="Income waiting for reversal approval",
            gross=MoneyInput(currency="CNY", amount="50.00"),
            post=True,
        ),
        actor_id=user.id,
    )
    reversal = {
        "record_type": "reversal",
        "accounting_date": None,
        "description": None,
        "currency": None,
        "gross": None,
        "cost": None,
        "fee": None,
        "cash": None,
        "amount_cny": None,
        "fx_rate": None,
        "channel": None,
        "provider_id": None,
        "provider_name": None,
        "category_id": None,
        "external_id": None,
        "record_id": original.id,
        "reason": "Source document was duplicated",
        "source_refs": [],
    }
    workflow = create_workflow(
        db_session,
        user,
        WorkflowCreate(
            command="/冲正",
            initial_text=json.dumps({"proposals": [reversal]}, ensure_ascii=False),
        ),
    )
    await analyze_workflow(
        db_session,
        user,
        workflow.id,
        Settings(app_env="test", app_secret_key="workflow-test-secret"),
    )
    ready = validate_workflow(db_session, user, workflow.id)
    assert ready.canonical_hash
    result = confirm_workflow(
        db_session,
        user,
        workflow.id,
        WorkflowConfirm(
            workflow_version=ready.version,
            canonical_hash=ready.canonical_hash,
        ),
        "reversal-approval-key",
    )
    assert result["status"] == "pending_approval"
    assert db_session.scalar(select(func.count()).select_from(ApprovalRequest)) == 1
    db_session.refresh(original)
    assert str(original.status) == "posted"
    assert original.reversed_by_record_id is None
