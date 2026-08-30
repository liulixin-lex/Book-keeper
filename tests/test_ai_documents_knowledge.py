from io import BytesIO
from pathlib import Path

import openpyxl  # type: ignore[import-untyped]
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.ai.documents import add_and_extract_upload, extract_document
from app.ai.knowledge import knowledge_status, process_next_index_job, search_knowledge
from app.ai.workflow_schemas import WorkflowCreate
from app.ai.workflows import create_workflow
from app.config import Settings
from app.enums import UserRole
from app.models import KnowledgeDocument, KnowledgeIndexJob, User, Workspace
from app.schemas import IncomeCreate, MoneyInput
from app.services.accounting import create_income


def _user(db: Session, workspace: Workspace) -> User:
    user = User(
        workspace_id=workspace.id,
        username="knowledge-bookkeeper",
        email="knowledge-bookkeeper@example.test",
        display_name="Knowledge Bookkeeper",
        password_hash="not-used",
        role=UserRole.BOOKKEEPER,
    )
    db.add(user)
    db.commit()
    return user


def test_xlsx_extraction_does_not_execute_formulas(tmp_path: Path) -> None:
    path = tmp_path / "formula.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Bills"
    sheet["A1"] = "Amount"
    sheet["A2"] = 10
    sheet["A3"] = 20
    sheet["A4"] = "=SUM(A2:A3)"
    workbook.save(path)
    workbook.close()

    content, structure, parser = extract_document(path)
    assert parser == "xlsx"
    assert "Amount" in content
    formula = next(item for item in structure["cells"] if item["cell"] == "A4")
    assert formula["formula"] == "=SUM(A2:A3)"
    assert formula["formula_result_missing"] is True
    assert structure["formulas_executed"] is False


@pytest.mark.asyncio
async def test_successful_upload_is_extracted_and_original_removed(
    db_session: Session,
    workspace: Workspace,
    tmp_path: Path,
) -> None:
    user = _user(db_session, workspace)
    settings = Settings(
        app_env="test",
        app_secret_key="document-test-secret",
        ai_upload_dir=tmp_path / "uploads",
    )
    settings.ensure_directories()
    workflow = create_workflow(
        db_session,
        user,
        WorkflowCreate(command="/批量录入"),
    )
    upload = UploadFile(
        file=BytesIO("日期,摘要,金额\n2026-08-29,测试支出,12.50\n".encode()),
        filename="bills.csv",
        headers=Headers({"content-type": "text/csv"}),
    )
    item = await add_and_extract_upload(db_session, user, workflow, upload, settings)
    assert item.status == "extracted"
    assert item.temporary_path is None
    assert item.sha256
    assert item.extraction is not None
    assert "测试支出" in item.extraction.content_text
    assert list((tmp_path / "uploads").rglob("*.csv")) == []


def test_knowledge_outbox_retries_without_corrupting_index(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _user(db_session, workspace)
    record_id = db_session.scalar(
        select(KnowledgeIndexJob.entity_id).where(KnowledgeIndexJob.workspace_id == workspace.id)
    )
    if record_id is None:
        from app.models import BusinessRecord

        record_id = db_session.scalar(
            select(BusinessRecord.id).where(BusinessRecord.workspace_id == workspace.id)
        )
    assert record_id is None

    # An outbox job with a missing entity retries instead of corrupting the index.
    db_session.add(
        KnowledgeIndexJob(
            workspace_id=workspace.id,
            entity_type="business_record",
            entity_id="missing-record",
            action="upsert",
            status="pending",
        )
    )
    db_session.commit()
    settings = Settings(app_env="test", app_secret_key="knowledge-test-secret")
    assert process_next_index_job(db_session, settings) is True
    job = db_session.scalar(select(KnowledgeIndexJob))
    assert job is not None
    assert job.status == "pending"
    assert job.attempts == 1
    assert db_session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 0
    status = knowledge_status(db_session, workspace.id)
    assert status["fallback_available"] is True
    assert status["vector_backend"] in {"sqlite-vec", "json-cosine-fallback"}
    assert search_knowledge(db_session, user, "missing", settings)["results"] == []


def test_knowledge_outbox_builds_live_sql_evidence_without_embedding_service(
    db_session: Session,
    workspace: Workspace,
) -> None:
    user = _user(db_session, workspace)
    record = create_income(
        db_session,
        workspace,
        IncomeCreate(
            accounting_date="2026-08-29",
            description="Knowledge searchable transfer income",
            gross=MoneyInput(currency="CNY", amount="99.00"),
            fee=MoneyInput(currency="CNY", amount="1.00"),
            channel="knowledge-test",
            external_id="knowledge-income-1",
            category_id="test-category-income-main",
            post=True,
        ),
        actor_id=user.id,
    )
    settings = Settings(app_env="test", app_secret_key="knowledge-test-secret")
    assert process_next_index_job(db_session, settings) is True
    document = db_session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.entity_id == record.id)
    )
    assert document is not None
    result = search_knowledge(db_session, user, "knowledge-income-1", settings)
    assert result["authority"] == "live_sql"
    assert result["results"][0]["entity_id"] == record.id
    assert "exact_sql" in result["results"][0]["methods"]
