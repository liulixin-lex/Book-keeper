from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.enums import AIMode, AIProtocol, ReasoningEffort


class AiEventType(StrEnum):
    START = "start"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DONE = "done"
    ERROR = "error"


class AiMessage(BaseModel):
    role: str = Field(pattern=r"^(system|developer|user|assistant|tool)$")
    content: str | list[dict[str, Any]]


class AiToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AiToolResult(BaseModel):
    tool_call: AiToolCall
    result: dict[str, Any]
    duplicate: bool = False


class AiToolExchange(BaseModel):
    """Internal, protocol-neutral representation of one tool round."""

    assistant_text: str = ""
    tool_calls: list[AiToolCall] = Field(default_factory=list)
    tool_results: list[AiToolResult] = Field(default_factory=list)


class AiEvent(BaseModel):
    type: AiEventType
    response_id: str | None = None
    text: str | None = None
    tool_call: AiToolCall | None = None
    result: dict[str, Any] | None = None
    arguments_delta: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    error: str | None = None
    raw_type: str | None = None


class AiRequest(BaseModel):
    mode: AIMode = AIMode.CHAT
    messages: list[AiMessage] = Field(min_length=1)
    system_prompt: str | None = Field(default=None, max_length=100_000)
    stream: bool = False
    max_output_tokens: int = Field(default=2048, ge=1, le=128_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    response_format: dict[str, Any] | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    required_tool: str | None = Field(default=None, exclude=True)
    tool_exchanges: list[AiToolExchange] = Field(default_factory=list, exclude=True)


class AiResponse(BaseModel):
    response_id: str | None = None
    text: str = ""
    tool_calls: list[AiToolCall] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str | None = None
    raw_status: str | None = None


class AiToolLoopResponse(AiResponse):
    tool_results: list[AiToolResult] = Field(default_factory=list)
    provider_rounds: int = Field(ge=1)
    tool_rounds: int = Field(ge=0)
    stop_reason: str


class AIProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    protocol: AIProtocol
    base_url: str = Field(min_length=8, max_length=1024)
    model: str = Field(min_length=1, max_length=240)
    api_key: SecretStr | None = None
    use_environment_api_key: bool = False
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    headers_json: dict[str, str] = Field(default_factory=dict)
    capabilities_json: dict[str, bool] = Field(default_factory=dict)
    is_active: bool = True
    probe_before_save: bool = Field(default=True, exclude=True)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            raise ValueError("api_key must not be empty")
        return value

    @field_validator("headers_json")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        forbidden = {"authorization", "x-api-key"}
        if any(name.lower() in forbidden for name in value):
            raise ValueError("authentication headers must be configured with api_key")
        return value

    @model_validator(mode="after")
    def validate_key_source(self) -> Self:
        if self.api_key is not None and self.use_environment_api_key:
            raise ValueError("api_key and use_environment_api_key cannot be used together")
        return self


class AIProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    protocol: AIProtocol | None = None
    base_url: str | None = Field(default=None, min_length=8, max_length=1024)
    model: str | None = Field(default=None, min_length=1, max_length=240)
    api_key: SecretStr | None = None
    use_environment_api_key: bool | None = None
    clear_api_key: bool = False
    reasoning_effort: ReasoningEffort | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    headers_json: dict[str, str] | None = None
    capabilities_json: dict[str, bool] | None = None
    is_active: bool | None = None
    probe_before_save: bool = Field(default=True, exclude=True)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            raise ValueError("api_key must not be empty")
        return value

    @field_validator("headers_json")
    @classmethod
    def validate_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        forbidden = {"authorization", "x-api-key"}
        if any(name.lower() in forbidden for name in value):
            raise ValueError("authentication headers must be configured with api_key")
        return value

    @model_validator(mode="after")
    def validate_key_operation(self) -> Self:
        if self.clear_api_key and self.api_key is not None:
            raise ValueError("api_key and clear_api_key cannot be used together")
        if self.use_environment_api_key is True and (
            self.api_key is not None or self.clear_api_key
        ):
            raise ValueError(
                "use_environment_api_key cannot be combined with api_key or clear_api_key"
            )
        if not (self.model_fields_set - {"probe_before_save"}):
            raise ValueError("at least one provider field must be supplied")
        return self


class AIProviderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    name: str
    protocol: AIProtocol
    base_url: str
    model: str
    reasoning_effort: ReasoningEffort
    timeout_seconds: int
    headers_json: dict[str, str]
    capabilities_json: dict[str, bool]
    is_active: bool
    version: int
    has_api_key: bool = False
    api_key_source: str = "none"
    last_tested_at: Any | None = None
    last_test_status: str | None = None
    last_test_error: str | None = None


class AIProviderTestResult(BaseModel):
    ok: bool
    provider_id: str
    model: str
    latency_ms: int
    error: str | None = None


class AIWorkspaceSettingsView(BaseModel):
    agents_md: str
    web_access_enabled: bool
    version: int


class AIWorkspaceSettingsPatch(BaseModel):
    agents_md: str | None = Field(default=None, min_length=1, max_length=200_000)
    web_access_enabled: bool | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.agents_md is None and self.web_access_enabled is None:
            raise ValueError("at least one setting must be supplied")
        return self
