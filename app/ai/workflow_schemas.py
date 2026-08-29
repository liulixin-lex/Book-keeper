from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.enums import AIWorkflowStatus, ProposalFieldStatus


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedLedgerProposal(StrictModel):
    record_type: Literal["income", "expense", "reversal"]
    accounting_date: date | None
    description: str | None
    currency: str | None
    gross: str | None
    cost: str | None
    fee: str | None
    cash: str | None
    amount_cny: str | None
    fx_rate: str | None
    channel: str | None
    provider_id: str | None
    provider_name: str | None
    category_id: str | None
    external_id: str | None
    record_id: str | None
    reason: str | None
    source_refs: list[dict[str, Any]]


class ExtractedLedgerProposalBatch(StrictModel):
    proposals: list[ExtractedLedgerProposal] = Field(min_length=1, max_length=500)


class WorkflowCreate(StrictModel):
    command: str = Field(min_length=2, max_length=80)
    initial_text: str | None = Field(default=None, max_length=200_000)
    provider_id: str | None = None


class WorkflowTextInput(StrictModel):
    text: str = Field(min_length=1, max_length=200_000)


class WorkflowGuidanceInput(StrictModel):
    message: str = Field(min_length=1, max_length=8_000)
    provider_id: str | None = None


class WorkflowGuidanceReply(StrictModel):
    reply: str = Field(min_length=1, max_length=4_000)
    clarifying_questions: list[str] = Field(max_length=12)


class WorkflowAnalyze(StrictModel):
    provider_id: str | None = None


class ProposalPatch(StrictModel):
    expected_version: int = Field(ge=1)
    changes: dict[str, Any]

    @field_validator("changes")
    @classmethod
    def validate_changes(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = set(ExtractedLedgerProposal.model_fields) - {"source_refs", "record_type"}
        unknown = sorted(set(value) - allowed - {"duplicate_override"})
        if unknown:
            raise ValueError(f"unsupported proposal fields: {', '.join(unknown)}")
        if not value:
            raise ValueError("at least one field must be changed")
        return value


class WorkflowValidate(StrictModel):
    proposal_ids: list[str] | None = None


class WorkflowConfirm(StrictModel):
    workflow_version: int = Field(ge=1)
    canonical_hash: str = Field(min_length=64, max_length=64)
    proposal_ids: list[str] | None = None


class FieldEvidence(StrictModel):
    value: Any = None
    status: ProposalFieldStatus
    source_ref: str | None = None
    source_span: str | None = None


class WorkflowEventView(StrictModel):
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class WorkflowMessageView(StrictModel):
    id: str
    sequence: int
    role: Literal["user", "assistant"]
    content: str
    clarifying_questions: list[str]
    created_at: datetime


class ProposalView(StrictModel):
    id: str
    sequence: int
    operation: str
    record_type: str | None
    status: str
    version: int
    fields: dict[str, Any]
    validation: dict[str, Any]
    journal_preview: dict[str, Any]
    duplicate: dict[str, Any]
    entity_versions: dict[str, Any]
    canonical_hash: str | None
    committed_record_id: str | None
    approval_id: str | None


class WorkflowView(StrictModel):
    id: str
    command: str
    status: AIWorkflowStatus
    version: int
    canonical_hash: str | None
    selected_proposal_ids: list[str]
    validation: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime
    input_count: int
    attachment_count: int
    messages: list[WorkflowMessageView]
    proposals: list[ProposalView]
    events: list[WorkflowEventView]


class PluginStatePatch(StrictModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.enabled is None and self.config is None:
            raise ValueError("at least one plugin field must be supplied")
        return self


class EmbeddingProviderCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    base_url: str = Field(min_length=8, max_length=1024)
    model: str = Field(min_length=1, max_length=240)
    dimension: int = Field(gt=0, le=65536)
    api_key: SecretStr | None = None
    use_environment_api_key: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    batch_size: int = Field(default=32, ge=1, le=2048)
    is_active: bool = True

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        return normalized


class EmbeddingProviderPatch(StrictModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    base_url: str | None = Field(default=None, min_length=8, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=240)
    dimension: int | None = Field(default=None, gt=0, le=65536)
    api_key: SecretStr | None = None
    use_environment_api_key: bool | None = None
    clear_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    batch_size: int | None = Field(default=None, ge=1, le=2048)
    is_active: bool | None = None


class KnowledgeSearch(StrictModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=20, ge=1, le=100)
