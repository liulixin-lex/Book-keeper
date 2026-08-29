from __future__ import annotations

from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.commands import COMMANDS
from app.ai.documents import DocumentExtractionError, add_and_extract_upload
from app.ai.knowledge import (
    KnowledgeError,
    create_embedding_provider,
    embedding_provider_view,
    enqueue_full_rebuild,
    knowledge_status,
    search_knowledge,
    test_embedding_provider,
    update_embedding_provider,
)
from app.ai.plugins import BUILTIN_PLUGINS, PLUGIN_INDEX
from app.ai.workflow_schemas import (
    EmbeddingProviderCreate,
    EmbeddingProviderPatch,
    KnowledgeSearch,
    PluginStatePatch,
    ProposalPatch,
    WorkflowAnalyze,
    WorkflowConfirm,
    WorkflowCreate,
    WorkflowGuidanceInput,
    WorkflowTextInput,
    WorkflowValidate,
    WorkflowView,
)
from app.ai.workflows import (
    WorkflowError,
    add_text_input,
    analyze_workflow,
    cancel_workflow,
    confirm_workflow,
    create_workflow,
    get_workflow_view,
    guide_workflow,
    patch_proposal,
    validate_workflow,
    workflow_view,
)
from app.config import Settings, get_settings
from app.db import get_db
from app.dependencies import (
    AuthContext,
    require_admin,
    require_bookkeeper,
    require_csrf,
    require_viewer,
)
from app.models import AIEmbeddingProvider, AIPluginState, AIWorkflow, User

router = APIRouter(prefix="/ai", tags=["ai-workbench"])


def _raise_workflow_error(exc: WorkflowError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _raise_knowledge_error(exc: KnowledgeError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/commands")
def list_commands(_user: Annotated[User, Depends(require_viewer)]) -> dict[str, Any]:
    return {"items": [item.as_dict() for item in COMMANDS]}


@router.post("/workflows", response_model=WorkflowView, status_code=status.HTTP_201_CREATED)
def create_ai_workflow(
    payload: WorkflowCreate,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowView:
    try:
        workflow = create_workflow(db, auth.user, payload)
        return get_workflow_view(db, auth.user, workflow.id)
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.get("/workflows/{workflow_id}", response_model=WorkflowView)
def read_ai_workflow(
    workflow_id: str,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowView:
    try:
        return get_workflow_view(db, user, workflow_id)
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.post("/workflows/{workflow_id}/inputs/text", response_model=WorkflowView)
def add_ai_workflow_text(
    workflow_id: str,
    payload: WorkflowTextInput,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowView:
    try:
        add_text_input(db, auth.user, workflow_id, payload.text)
        return get_workflow_view(db, auth.user, workflow_id)
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.post("/workflows/{workflow_id}/inputs/file", response_model=WorkflowView)
async def add_ai_workflow_file(
    workflow_id: str,
    file: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkflowView:
    workflow = db.scalar(
        select(AIWorkflow).where(
            AIWorkflow.id == workflow_id,
            AIWorkflow.workspace_id == auth.user.workspace_id,
            AIWorkflow.created_by_id == auth.user.id,
        )
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    try:
        item = await add_and_extract_upload(db, auth.user, workflow, file, settings)
        if item.status == "failed":
            raise HTTPException(status_code=422, detail="附件解析失败，请检查文件后重试")
        return get_workflow_view(db, auth.user, workflow_id)
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/guidance", response_model=WorkflowView)
async def guide_ai_workflow(
    workflow_id: str,
    payload: WorkflowGuidanceInput,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkflowView:
    try:
        workflow = await guide_workflow(db, auth.user, workflow_id, payload, settings)
        return workflow_view(workflow)
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.post("/workflows/{workflow_id}/analyze", response_model=WorkflowView)
async def analyze_ai_workflow(
    workflow_id: str,
    payload: WorkflowAnalyze,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WorkflowView:
    try:
        workflow = await analyze_workflow(
            db,
            auth.user,
            workflow_id,
            settings,
            provider_id=payload.provider_id,
        )
        return workflow_view(workflow)
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.patch("/workflows/{workflow_id}/proposals/{proposal_id}", response_model=WorkflowView)
def update_ai_proposal(
    workflow_id: str,
    proposal_id: str,
    payload: ProposalPatch,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowView:
    try:
        return workflow_view(patch_proposal(db, auth.user, workflow_id, proposal_id, payload))
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.post("/workflows/{workflow_id}/validate", response_model=WorkflowView)
def validate_ai_workflow(
    workflow_id: str,
    payload: WorkflowValidate,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowView:
    try:
        return workflow_view(validate_workflow(db, auth.user, workflow_id, payload.proposal_ids))
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.post("/workflows/{workflow_id}/confirm")
def confirm_ai_workflow(
    workflow_id: str,
    payload: WorkflowConfirm,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    try:
        return confirm_workflow(
            db,
            auth.user,
            workflow_id,
            payload,
            idempotency_key,
        )
    except WorkflowError as exc:
        _raise_workflow_error(exc)


@router.post("/workflows/{workflow_id}/cancel", response_model=WorkflowView)
def cancel_ai_workflow(
    workflow_id: str,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _bookkeeper: Annotated[User, Depends(require_bookkeeper)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowView:
    try:
        return workflow_view(cancel_workflow(db, auth.user, workflow_id))
    except WorkflowError as exc:
        _raise_workflow_error(exc)


def _plugin_view(plugin_id: str, state: AIPluginState | None) -> dict[str, Any]:
    manifest = PLUGIN_INDEX[plugin_id]
    return {
        **manifest.model_dump(mode="json"),
        "enabled": manifest.core or state is None or state.enabled,
        "config": state.config_json if state else {},
        "health_status": state.health_status if state else "healthy",
        "last_error": state.last_error if state else None,
    }


@router.get("/plugins")
def list_plugins(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    states = {
        state.plugin_id: state
        for state in db.scalars(
            select(AIPluginState).where(AIPluginState.workspace_id == user.workspace_id)
        ).all()
    }
    return {"items": [_plugin_view(plugin.id, states.get(plugin.id)) for plugin in BUILTIN_PLUGINS]}


@router.patch("/plugins/{plugin_id}")
def update_plugin(
    plugin_id: str,
    payload: PluginStatePatch,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    manifest = PLUGIN_INDEX.get(plugin_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="内置插件不存在")
    if manifest.core and payload.enabled is False:
        raise HTTPException(status_code=409, detail="核心插件不能停用")
    state = db.scalar(
        select(AIPluginState).where(
            AIPluginState.workspace_id == auth.user.workspace_id,
            AIPluginState.plugin_id == plugin_id,
        )
    )
    if state is None:
        state = AIPluginState(
            workspace_id=auth.user.workspace_id,
            plugin_id=plugin_id,
            plugin_version=manifest.version,
            enabled=True,
            updated_by_id=auth.user.id,
        )
        db.add(state)
    if payload.enabled is not None:
        state.enabled = payload.enabled
    if payload.config is not None:
        state.config_json = payload.config
    state.updated_by_id = auth.user.id
    state.health_status = "healthy"
    db.commit()
    db.refresh(state)
    return _plugin_view(plugin_id, state)


def _embedding_provider_or_404(db: Session, user: User, provider_id: str) -> AIEmbeddingProvider:
    provider = db.scalar(
        select(AIEmbeddingProvider).where(
            AIEmbeddingProvider.id == provider_id,
            AIEmbeddingProvider.workspace_id == user.workspace_id,
        )
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="嵌入供应商不存在")
    return provider


@router.get("/embedding-providers")
def list_embedding_providers(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    providers = db.scalars(
        select(AIEmbeddingProvider)
        .where(AIEmbeddingProvider.workspace_id == user.workspace_id)
        .order_by(AIEmbeddingProvider.created_at)
    ).all()
    return {"items": [embedding_provider_view(provider) for provider in providers]}


@router.post("/embedding-providers", status_code=status.HTTP_201_CREATED)
def create_ai_embedding_provider(
    payload: EmbeddingProviderCreate,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    try:
        provider = create_embedding_provider(db, auth.user, payload, settings)
        return embedding_provider_view(provider)
    except KnowledgeError as exc:
        _raise_knowledge_error(exc)


@router.patch("/embedding-providers/{provider_id}")
def update_ai_embedding_provider(
    provider_id: str,
    payload: EmbeddingProviderPatch,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    provider = _embedding_provider_or_404(db, auth.user, provider_id)
    try:
        updated = update_embedding_provider(db, auth.user, provider, payload, settings)
        return embedding_provider_view(updated)
    except KnowledgeError as exc:
        _raise_knowledge_error(exc)


@router.post("/embedding-providers/{provider_id}/test")
def test_ai_embedding_provider(
    provider_id: str,
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    provider = _embedding_provider_or_404(db, auth.user, provider_id)
    return test_embedding_provider(db, provider, settings)


@router.get("/knowledge/status")
def read_knowledge_status(
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return knowledge_status(db, user.workspace_id)


@router.post("/knowledge/rebuild")
def rebuild_knowledge(
    auth: Annotated[AuthContext, Depends(require_csrf)],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    result = enqueue_full_rebuild(db, auth.user.workspace_id)
    db.commit()
    return result


@router.post("/knowledge/search")
def search_ai_knowledge(
    payload: KnowledgeSearch,
    user: Annotated[User, Depends(require_viewer)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    try:
        return search_knowledge(db, user, payload.query, settings, limit=payload.limit)
    except KnowledgeError as exc:
        _raise_knowledge_error(exc)
