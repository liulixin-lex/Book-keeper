"""设置 → AI: providers, task routing and usage. Changing them needs config:write from the web app (not tokens,
not MCP); reading them needs admin:read and never shows a key."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import ai_providers as service

router = APIRouter(prefix="/books/{book_id}/ai", tags=["ai"])


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: float = Field(ge=0, description="美元 / 百万输入 token")
    output: float = Field(ge=0, description="美元 / 百万输出 token")


class Caps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    images: bool | None = None
    pdf: bool | None = None
    structured: bool | None = None
    tools: bool | None = None
    fallback: bool | None = Field(default=None, description="服务端回退（仅 Anthropic 官方，开启后发送 beta 请求头）")


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    max_tokens_param: Literal["max_tokens", "max_completion_tokens"] | None = None


class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["anthropic", "openai_compatible"]
    base_url: str | None = Field(default=None, description="OpenAI 兼容必填，如 https://relay.example.com/v1")
    api_key: str = Field(min_length=1, max_length=500, description="只写：保存后只显示末 4 位")
    models: list[str] = Field(default_factory=list)
    default_model: str | None = None
    timeout_seconds: int = Field(default=120, ge=5, le=600)
    enabled: bool = True
    capabilities: Caps = Field(default_factory=Caps)
    options: Options = Field(default_factory=Options)
    prices: dict[str, Price] = Field(default_factory=dict)


class ProviderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int
    name: str | None = Field(default=None, min_length=1, max_length=60)
    base_url: str | None = None
    api_key: str | None = Field(default=None, max_length=500, description="改了 Base URL 时必填")
    models: list[str] | None = None
    default_model: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=600)
    enabled: bool | None = None
    capabilities: Caps | None = None
    options: Options | None = None
    prices: dict[str, Price] | None = None


class RouteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str
    model: str | None = None


class RoutesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    extract: list[RouteItem] = Field(default_factory=list, description="识别：第一个优先，后面的依次备用")
    agent: list[RouteItem] = Field(default_factory=list, description="AI 助手：第一个优先，后面的依次备用")


def _dump(model: BaseModel, *, unset: bool = False) -> dict[str, Any]:
    data = model.model_dump(mode="json", exclude_unset=unset)
    for key in ("capabilities", "options"):
        if isinstance(data.get(key), dict):
            data[key] = {k: v for k, v in data[key].items() if v is not None}
    return data


@router.get("/status")
def status(book_id: str, auth: AuthDep, db: DbDep, settings: SettingsDep) -> dict[str, Any]:
    """Whether each AI task can run (a provider is routed, or BK_AI_* is set). No configuration details."""

    def load() -> dict[str, Any]:
        return {task: service.available(db, book_id, task, settings) for task in service.TASKS}

    return run_read(db, load, auth.ctx)


@router.get("/providers")
def list_providers(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    """Providers without keys (only the last 4 characters)."""
    auth.ctx.require(Scope.ADMIN_READ)
    return run_read(db, lambda: [service.view(p) for p in service.list_providers(db, book_id)], auth.ctx)


@router.post("/providers", status_code=201)
def create_provider(
    book_id: str, body: ProviderIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Add a provider; the key is sealed with BK_MASTER_KEY. Web app only."""
    payload = _dump(body) | {"api_key": "[set]"}
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "ai.providers.create",
        payload,
        lambda: service.view(service.create_provider(db, auth.ctx, _dump(body), settings)),
        status_code=201,
    )


@router.patch("/providers/{provider_id}")
def update_provider(
    book_id: str,
    provider_id: str,
    body: ProviderPatch,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    """Change a provider; a new Base URL needs the key again. Web app only."""
    changes = _dump(body, unset=True)
    expected = changes.pop("expected_version")
    payload = changes | ({"api_key": "[set]"} if changes.get("api_key") else {}) | {"provider_id": provider_id}
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "ai.providers.update",
        payload,
        lambda: service.view(service.update_provider(db, auth.ctx, provider_id, expected, changes, settings)),
    )


@router.delete("/providers/{provider_id}")
def delete_provider(
    book_id: str, provider_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Remove a provider and drop it from task routing. Web app only."""

    def apply() -> dict[str, Any]:
        service.delete_provider(db, auth.ctx, provider_id)
        return {"deleted": provider_id}

    return run_write(request, db, auth.ctx, settings, "ai.providers.delete", {"provider_id": provider_id}, apply)


@router.post("/providers/{provider_id}:test")
def test_provider(
    book_id: str, provider_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """A tiny request to the provider: does it answer, which models does it list."""
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "ai.providers.test",
        {"provider_id": provider_id},
        lambda: service.probe_provider(db, auth.ctx, provider_id, settings),
    )


@router.get("/routes")
def get_routes(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    """Provider + model per task (识别, AI 助手), in fallback order."""
    auth.ctx.require(Scope.ADMIN_READ)
    return run_read(db, lambda: service.get_routes(db, book_id), auth.ctx)


@router.put("/routes")
def set_routes(
    book_id: str, body: RoutesIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Set the provider + model order per task. Web app only."""
    raw = body.model_dump(mode="json")
    return run_write(
        request, db, auth.ctx, settings, "ai.routes.set", raw, lambda: service.set_routes(db, auth.ctx, raw)
    )


@router.get("/usage")
def usage(book_id: str, auth: AuthDep, db: DbDep, days: int = Query(default=30, ge=1, le=366)) -> dict[str, Any]:
    """Calls, tokens and estimated cost per provider, model and task."""
    auth.ctx.require(Scope.ADMIN_READ)
    return run_read(db, lambda: service.usage_summary(db, book_id, days), auth.ctx)
