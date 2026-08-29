from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.ai.executor import SQLDomainToolExecutor
from app.ai.schemas import AiToolCall
from app.amounts import to_e8
from app.enums import (
    AIMode,
    AIProtocol,
    AIStatus,
    ApprovalStatus,
    JournalStatus,
    ReasoningEffort,
    RecordStatus,
    UserRole,
)
from app.models import (
    AIProvider,
    AIRun,
    AIToolCall,
    ApprovalRequest,
    BusinessRecord,
    JournalEntry,
    User,
    Workspace,
)


@dataclass(slots=True)
class ExecutorContext:
    executor: SQLDomainToolExecutor
    user: User
    run: AIRun


def executor_context(
    db_session: Session,
    workspace: Workspace,
    mode: AIMode = AIMode.EDIT,
) -> ExecutorContext:
    user = User(
        workspace_id=workspace.id,
        username=f"AI executor {mode.value} {workspace.id}",
        email=f"ai-{mode.value}-{workspace.id}@example.test",
        display_name="AI executor tester",
        password_hash="not-used-by-this-test",
        role=UserRole.ADMIN,
        is_active=True,
    )
    provider = AIProvider(
        workspace_id=workspace.id,
        name=f"Executor provider {mode.value}",
        protocol=AIProtocol.RESPONSES,
        base_url="https://example.test/v1",
        model="mock-model",
        reasoning_effort=ReasoningEffort.MEDIUM,
    )
    db_session.add_all([user, provider])
    db_session.flush()
    run = AIRun(
        workspace_id=workspace.id,
        provider_id=provider.id,
        mode=mode,
        tool_scope="ledger",
        status=AIStatus.RUNNING,
        model=provider.model,
        reasoning_effort=provider.reasoning_effort,
        created_by_id=user.id,
    )
    db_session.add(run)
    db_session.commit()
    return ExecutorContext(SQLDomainToolExecutor(db_session, user, run), user, run)


def create_income_call(call_id: str = "income-call-1") -> AiToolCall:
    return AiToolCall(
        id=call_id,
        name="create_income",
        arguments={
            "accounting_date": "2026-08-28",
            "description": "AI imported income",
            "channel": "stripe",
            "external_id": f"external-{call_id}",
            "currency": "CNY",
            "gross": "100.00",
            "fee": "5.00",
            "post": True,
        },
    )


def create_expense_call(call_id: str = "expense-call-1") -> AiToolCall:
    return AiToolCall(
        id=call_id,
        name="create_expense",
        arguments={
            "accounting_date": "2026-08-28",
            "description": "AI cloud expense",
            "currency": "CNY",
            "cost": "20.00",
            "cash": "20.00",
            "post": True,
        },
    )


def test_chat_mode_rejects_write_tool_without_business_write(
    db_session: Session, workspace: Workspace
) -> None:
    context = executor_context(db_session, workspace, AIMode.CHAT)

    result = context.executor.execute(create_income_call("chat-write-attempt"))

    assert result["ok"] is False
    assert "not allowed" in result["error"]
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0
    tool_call = db_session.scalar(
        select(AIToolCall).where(
            AIToolCall.run_id == context.run.id,
            AIToolCall.provider_call_id == "chat-write-attempt",
        )
    )
    assert tool_call is not None
    assert tool_call.status == "failed"


def test_chat_mode_runs_read_tools_on_query_only_connection(
    db_session: Session, workspace: Workspace, monkeypatch
) -> None:
    context = executor_context(db_session, workspace, AIMode.CHAT)

    def probe(_arguments):
        enabled = context.executor.session.scalar(text("PRAGMA query_only"))
        return {"ok": True, "query_only": enabled}

    monkeypatch.setattr(context.executor, "tool_get_overview", probe)
    result = context.executor.execute(
        AiToolCall(
            id="query-only-probe",
            name="get_overview",
            arguments={"date_from": "2026-08-01", "date_to": "2026-08-31"},
        )
    )
    assert result == {"ok": True, "query_only": 1}


def test_edit_mode_creates_and_posts_income_and_expense(
    db_session: Session, workspace: Workspace
) -> None:
    context = executor_context(db_session, workspace)

    income_result = context.executor.execute(create_income_call())
    expense_result = context.executor.execute(create_expense_call())

    assert income_result["ok"] is True
    assert expense_result["ok"] is True
    records = list(
        db_session.scalars(
            select(BusinessRecord)
            .where(BusinessRecord.workspace_id == workspace.id)
            .order_by(BusinessRecord.description)
        )
    )
    assert len(records) == 2
    assert all(RecordStatus(record.status) == RecordStatus.POSTED for record in records)
    assert all(record.created_by_ai_run_id == context.run.id for record in records)

    entries = list(
        db_session.scalars(select(JournalEntry).where(JournalEntry.workspace_id == workspace.id))
    )
    assert len(entries) == 2
    assert all(JournalStatus(entry.status) == JournalStatus.POSTED for entry in entries)
    for entry in entries:
        assert sum(line.debit_cny_e8 for line in entry.lines) == sum(
            line.credit_cny_e8 for line in entry.lines
        )

    income = next(record for record in records if record.description == "AI imported income")
    expense = next(record for record in records if record.description == "AI cloud expense")
    income_amounts = {str(item.role): item.amount_cny_e8 for item in income.amounts}
    expense_amounts = {str(item.role): item.amount_cny_e8 for item in expense.amounts}
    assert income_amounts == {
        "gross": to_e8("100"),
        "fee": to_e8("5"),
        "net": to_e8("95"),
        "cash": to_e8("95"),
    }
    assert expense_amounts == {"cost": to_e8("20"), "cash": to_e8("20")}


def test_expense_without_cash_derives_actual_cash_component(
    db_session: Session, workspace: Workspace
) -> None:
    context = executor_context(db_session, workspace)
    call = create_expense_call("expense-without-cash")
    call.arguments.pop("cash")

    result = context.executor.execute(call)

    assert result["ok"] is True
    record = db_session.scalar(
        select(BusinessRecord).where(BusinessRecord.created_by_ai_run_id == context.run.id)
    )
    assert record is not None
    assert RecordStatus(record.status) == RecordStatus.POSTED
    assert {str(item.role): item.amount_cny_e8 for item in record.amounts} == {
        "cost": to_e8("20"),
        "cash": to_e8("20"),
    }


def test_completed_tool_call_is_idempotent(db_session: Session, workspace: Workspace) -> None:
    context = executor_context(db_session, workspace)
    call = create_income_call("idempotent-income")

    first = context.executor.execute(call)
    second_call = call.model_copy(
        update={
            "id": "provider-retried-with-new-id",
            "arguments": dict(reversed(list(call.arguments.items()))),
        }
    )
    second = SQLDomainToolExecutor(db_session, context.user, context.run).execute(second_call)

    assert second == first
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 1
    assert db_session.scalar(select(func.count()).select_from(AIToolCall)) == 1
    persisted_call = db_session.scalar(select(AIToolCall))
    assert persisted_call is not None
    assert len(persisted_call.signature) == 64


def test_concurrent_equivalent_tool_calls_execute_business_write_once(
    db_session: Session, workspace: Workspace
) -> None:
    context = executor_context(db_session, workspace)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def execute(call_id: str) -> dict[str, object]:
        with factory() as session:
            user = session.get(User, context.user.id)
            run = session.get(AIRun, context.run.id)
            assert user is not None and run is not None
            call = create_expense_call(call_id)
            call.arguments = (
                dict(reversed(list(call.arguments.items())))
                if call_id.endswith("2")
                else call.arguments
            )
            barrier.wait(timeout=5)
            return SQLDomainToolExecutor(session, user, run).execute(call)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, ("concurrent-expense-1", "concurrent-expense-2")))

    assert results[0] == results[1]
    assert results[0]["ok"] is True
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 1
    assert db_session.scalar(select(func.count()).select_from(JournalEntry)) == 1
    assert db_session.scalar(select(func.count()).select_from(AIToolCall)) == 1


def test_removed_import_tools_are_rejected(db_session: Session, workspace: Workspace) -> None:
    context = executor_context(db_session, workspace, AIMode.EDIT)
    result = context.executor.execute(
        AiToolCall(
            id="ledger-import-attempt",
            name="get_import_batch",
            arguments={"batch_id": "not-reachable"},
        )
    )
    assert result["ok"] is False
    assert "not allowed" in str(result["error"]).lower()
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 0


def test_concurrent_ai_draft_updates_use_compare_and_swap(
    db_session: Session, workspace: Workspace
) -> None:
    context = executor_context(db_session, workspace)
    create_call = create_income_call("draft-for-cas")
    create_call.arguments["post"] = False
    created = context.executor.execute(create_call)
    record_id = created["record"]["id"]
    second_run = AIRun(
        workspace_id=workspace.id,
        provider_id=context.run.provider_id,
        mode=AIMode.EDIT,
        status=AIStatus.RUNNING,
        model=context.run.model,
        reasoning_effort=context.run.reasoning_effort,
        created_by_id=context.user.id,
    )
    db_session.add(second_run)
    db_session.commit()

    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    with factory() as first_session, factory() as stale_session:
        first_user = first_session.get(User, context.user.id)
        stale_user = stale_session.get(User, context.user.id)
        first_run = first_session.get(AIRun, context.run.id)
        stale_run = stale_session.get(AIRun, second_run.id)
        assert first_user is not None and stale_user is not None
        assert first_run is not None and stale_run is not None

        stale_record = stale_session.get(BusinessRecord, record_id)
        assert stale_record is not None and stale_record.version == 1
        stale_session.commit()

        first_result = SQLDomainToolExecutor(first_session, first_user, first_run).execute(
            AiToolCall(
                id="first-draft-update",
                name="update_draft_record",
                arguments={
                    "record_id": record_id,
                    "expected_version": 1,
                    "changes": {"description": "first writer"},
                },
            )
        )
        stale_result = SQLDomainToolExecutor(stale_session, stale_user, stale_run).execute(
            AiToolCall(
                id="stale-draft-update",
                name="update_draft_record",
                arguments={
                    "record_id": record_id,
                    "expected_version": 1,
                    "changes": {"description": "stale writer"},
                },
            )
        )

    assert first_result["ok"] is True
    assert stale_result["ok"] is False
    assert "version conflict" in stale_result["error"].lower()
    db_session.expire_all()
    persisted = db_session.get(BusinessRecord, record_id)
    assert persisted is not None
    assert persisted.description == "first writer"
    assert persisted.version == 2


def test_reversal_tool_only_creates_one_approval(db_session: Session, workspace: Workspace) -> None:
    context = executor_context(db_session, workspace)
    created = context.executor.execute(create_expense_call("expense-to-reverse"))
    record_id = created["record"]["id"]
    reverse_call = AiToolCall(
        id="reverse-call-1",
        name="reverse_posted_record",
        arguments={"record_id": record_id, "reason": "Duplicate charge"},
    )

    first = context.executor.execute(reverse_call)
    second = SQLDomainToolExecutor(db_session, context.user, context.run).execute(reverse_call)

    assert first == second
    assert first["ok"] is True
    assert first["status"] == "pending_approval"
    original = db_session.get(BusinessRecord, record_id)
    assert original is not None
    assert RecordStatus(original.status) == RecordStatus.POSTED
    assert original.reversed_by_record_id is None
    assert db_session.scalar(select(func.count()).select_from(BusinessRecord)) == 1
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(JournalEntry)
            .where(JournalEntry.reversal_of_id.is_not(None))
        )
        == 0
    )

    approvals = list(
        db_session.scalars(
            select(ApprovalRequest).where(ApprovalRequest.requested_by_ai_run_id == context.run.id)
        )
    )
    assert len(approvals) == 1
    approval = approvals[0]
    assert ApprovalStatus(approval.status) == ApprovalStatus.PENDING
    assert approval.kind == "ai_tool:reverse_posted_record"
    assert approval.payload_json["arguments"] == reverse_call.arguments

    persisted_call = db_session.scalar(
        select(AIToolCall).where(
            AIToolCall.run_id == context.run.id,
            AIToolCall.provider_call_id == reverse_call.id,
        )
    )
    assert persisted_call is not None
    assert persisted_call.status == "pending_approval"
