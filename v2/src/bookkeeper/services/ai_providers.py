"""AI providers and task routing (设置 → AI): which endpoint and model each AI task uses, with backups in order.

Writes need ``config:write`` from the web app (a signed-in session): API and MCP tokens, even admin ones, cannot
change providers or keys. Keys are sealed (ai/secrets.py) and never leave the server; views show the last 4
characters. Audit entries describe changes without the key. With nothing configured, ``BK_AI_*`` still works
as the default provider.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookkeeper.ai import adapters, secrets
from bookkeeper.ai.adapters import Capabilities, Target, Usage
from bookkeeper.config import Settings
from bookkeeper.db.models import AiProvider, AiUsage, Book
from bookkeeper.domain.errors import DomainError, not_found, version_conflict
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext

KINDS = ("anthropic", "openai_compatible")
TASKS = {"extract": "识别", "agent": "AI 助手"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_CAPS = {
    "anthropic": Capabilities(images=True, pdf=True, structured=True, tools=True, fallback=False),
    "openai_compatible": Capabilities(images=True, pdf=False, structured=True, tools=True, fallback=False),
}
ENV_NAME = "默认（服务器环境变量）"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


def view(p: AiProvider) -> dict[str, Any]:
    """Everything about a provider except its key."""
    return {
        "id": p.id,
        "name": p.name,
        "kind": p.kind,
        "base_url": p.base_url,
        "has_key": bool(p.api_key_sealed),
        "key_hint": f"••••{p.key_last4}" if p.key_last4 else None,
        "models": list(p.models or []),
        "default_model": p.default_model,
        "timeout_seconds": p.timeout_seconds,
        "enabled": p.enabled,
        "capabilities": Capabilities.of(p.capabilities).as_dict(),
        "options": dict(p.options or {}),
        "prices": dict(p.prices or {}),
        "version": p.version,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _web_only(ctx: RequestContext) -> None:
    ctx.require(Scope.CONFIG_WRITE)
    if ctx.actor.token_id is not None or ctx.channel in ("mcp", "agent"):
        raise DomainError("FORBIDDEN_SCOPE", "AI 提供商与密钥只能在网页端（设置 → AI）修改，令牌与 MCP 不能改。")


def _bound(provider_id: str, base_url: str | None) -> str:
    return f"{provider_id}|{base_url or ''}"


def _url(kind: str, value: Any) -> str | None:
    url = str(value or "").strip().rstrip("/") or None
    if url is None:
        if kind == "openai_compatible":
            raise DomainError(
                "VALIDATION_FAILED", "OpenAI 兼容的提供商需要填写 Base URL（如 https://api.example.com/v1）。"
            )
        return None
    parsed = urlparse(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme not in ("https", "http") or not parsed.hostname or (parsed.scheme == "http" and not local):
        raise DomainError("VALIDATION_FAILED", "Base URL 需要以 https:// 开头（本机地址可用 http://）。")
    return url


def _clean(kind: str, data: dict[str, Any], current: AiProvider | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "name" in data:
        name = str(data["name"] or "").strip()
        if not name or len(name) > 60:
            raise DomainError("VALIDATION_FAILED", "名称不能为空，最多 60 个字。")
        out["name"] = name
    if "models" in data:
        models = [str(m).strip() for m in data["models"] or [] if str(m).strip()]
        out["models"] = list(dict.fromkeys(models))
    models = out.get("models", list(current.models) if current else [])
    if "default_model" in data or "models" in data:
        default = str(data.get("default_model", current.default_model if current else "") or "").strip()
        default = default or (models[0] if models else "")
        if not default:
            raise DomainError("VALIDATION_FAILED", "请至少填写一个模型。")
        if models and default not in models:
            raise DomainError("VALIDATION_FAILED", f"默认模型 {default} 不在模型列表里。")
        out["default_model"] = default
        if not models:
            out["models"] = [default]
    if "timeout_seconds" in data:
        timeout = int(data["timeout_seconds"])
        if not 5 <= timeout <= 600:
            raise DomainError("VALIDATION_FAILED", "超时需在 5–600 秒之间（整批识别最多 10 分钟）。")
        out["timeout_seconds"] = timeout
    if "enabled" in data:
        out["enabled"] = bool(data["enabled"])
    if "capabilities" in data:
        base = DEFAULT_CAPS[kind].as_dict() if current is None else Capabilities.of(current.capabilities).as_dict()
        out["capabilities"] = Capabilities.of(base | dict(data["capabilities"] or {})).as_dict()
    if "options" in data:
        options = dict(data["options"] or {})
        effort = options.get("effort")
        if effort not in (None, "", *EFFORTS):
            raise DomainError("VALIDATION_FAILED", f"effort 只能是 {' / '.join(EFFORTS)}。")
        param = options.get("max_tokens_param")
        if param not in (None, "", "max_tokens", "max_completion_tokens"):
            raise DomainError("VALIDATION_FAILED", "max_tokens_param 只能是 max_tokens 或 max_completion_tokens。")
        out["options"] = {k: v for k, v in (("effort", effort), ("max_tokens_param", param)) if v}
    if "prices" in data:
        prices: dict[str, dict[str, float]] = {}
        for model, price in dict(data["prices"] or {}).items():
            try:
                prices[str(model)] = {"input": float(price["input"]), "output": float(price["output"])}
            except (KeyError, TypeError, ValueError) as exc:
                raise DomainError(
                    "VALIDATION_FAILED", f"模型 {model} 的价格需要 input 与 output（美元 / 百万 token）。"
                ) from exc
        out["prices"] = prices
    return out


def list_providers(session: Session, book_id: str) -> list[AiProvider]:
    return list(
        session.execute(select(AiProvider).where(AiProvider.book_id == book_id).order_by(AiProvider.created_at))
        .scalars()
        .all()
    )


def get_provider(session: Session, book_id: str, provider_id: str, *, lock: bool = False) -> AiProvider:
    p = session.get(AiProvider, provider_id, with_for_update=lock)
    if p is None or p.book_id != book_id:
        raise not_found("AI 提供商", provider_id)
    return p


def create_provider(session: Session, ctx: RequestContext, data: dict[str, Any], settings: Settings) -> AiProvider:
    _web_only(ctx)
    book_id = ctx.require_book()
    kind = str(data.get("kind") or "")
    if kind not in KINDS:
        raise DomainError("VALIDATION_FAILED", "类型只能是 anthropic 或 openai_compatible。")
    key = str(data.get("api_key") or "").strip()
    if not key:
        raise DomainError("VALIDATION_FAILED", "请填写 API 密钥。")
    fields = _clean(kind, {"capabilities": {}, **data})
    if "name" not in fields:
        raise DomainError("VALIDATION_FAILED", "请填写名称。")
    if "default_model" not in fields:
        fields |= _clean(kind, {"models": data.get("models") or [], "default_model": data.get("default_model")})
    p = AiProvider(
        id=new_id("aip"),
        book_id=book_id,
        kind=kind,
        base_url=_url(kind, data.get("base_url")),
        created_by=ctx.actor.user_id,
        **fields,
    )
    p.api_key_sealed = secrets.seal(key, settings, _bound(p.id, p.base_url))
    p.key_last4 = secrets.last4(key)
    session.add(p)
    _unique(session, p)
    audit.record(session, ctx, "ai_provider.create", "ai_provider", p.id, after=view(p) | {"key_set": True})
    return p


def update_provider(
    session: Session,
    ctx: RequestContext,
    provider_id: str,
    expected_version: int,
    changes: dict[str, Any],
    settings: Settings,
) -> AiProvider:
    _web_only(ctx)
    p = get_provider(session, ctx.require_book(), provider_id, lock=True)
    if p.version != expected_version:
        raise version_conflict("AI 提供商", expected_version, p.version)
    before = view(p)
    key = str(changes.get("api_key") or "").strip()
    new_url = _url(p.kind, changes["base_url"]) if "base_url" in changes else p.base_url
    if new_url != p.base_url and not key:
        raise DomainError(
            "VALIDATION_FAILED", "修改了 Base URL：请重新填写 API 密钥（已存的密钥不会发到新地址）。", next_action=None
        )
    for name, value in _clean(p.kind, changes, p).items():
        setattr(p, name, value)
    p.base_url = new_url
    if key:
        p.api_key_sealed = secrets.seal(key, settings, _bound(p.id, p.base_url))
        p.key_last4 = secrets.last4(key)
    p.version += 1
    _unique(session, p)
    audit.record(
        session,
        ctx,
        "ai_provider.update",
        "ai_provider",
        p.id,
        before=before,
        after=view(p) | {"key_changed": bool(key)},
    )
    return p


def delete_provider(session: Session, ctx: RequestContext, provider_id: str) -> None:
    _web_only(ctx)
    book_id = ctx.require_book()
    p = get_provider(session, book_id, provider_id, lock=True)
    before = view(p)
    book = session.get(Book, book_id, with_for_update=True)
    assert book is not None
    routes = _routes(book)
    if any(r["provider_id"] == p.id for task in routes.values() for r in task):
        _save_routes(book, {task: [r for r in rows if r["provider_id"] != p.id] for task, rows in routes.items()})
    session.delete(p)
    session.flush()
    audit.record(session, ctx, "ai_provider.delete", "ai_provider", provider_id, before=before)


def _unique(session: Session, p: AiProvider) -> None:
    clash = session.execute(
        select(AiProvider.id).where(AiProvider.book_id == p.book_id, AiProvider.name == p.name, AiProvider.id != p.id)
    ).first()
    if clash:
        raise DomainError("CONFLICT", f"已有名为 {p.name} 的提供商。")
    session.flush()


# ------------------------------------------------------------------ routing


def _routes(book: Book) -> dict[str, list[dict[str, str]]]:
    raw = (book.settings or {}).get("ai", {}).get("routes", {})
    return {task: [dict(r) for r in raw.get(task, [])] for task in TASKS}


def _save_routes(book: Book, routes: dict[str, list[dict[str, str]]]) -> None:
    settings = dict(book.settings or {})
    settings["ai"] = dict(settings.get("ai", {})) | {"routes": routes}
    book.settings = settings
    book.version += 1


def get_routes(session: Session, book_id: str) -> dict[str, list[dict[str, Any]]]:
    book = session.get(Book, book_id)
    assert book is not None
    names = {p.id: p for p in list_providers(session, book_id)}
    return {
        task: [
            r | {"provider_name": names[r["provider_id"]].name if r["provider_id"] in names else None}
            for r in rows
            if r["provider_id"] in names
        ]
        for task, rows in _routes(book).items()
    }


def set_routes(session: Session, ctx: RequestContext, routes: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Each task's providers in order: the first is used, the next ones when it is unavailable."""
    _web_only(ctx)
    book_id = ctx.require_book()
    book = session.get(Book, book_id, with_for_update=True)
    assert book is not None
    providers = {p.id: p for p in list_providers(session, book_id)}
    clean: dict[str, list[dict[str, str]]] = {}
    for task in TASKS:
        rows = []
        for item in routes.get(task) or []:
            pid, model = str(item.get("provider_id") or ""), str(item.get("model") or "").strip()
            if pid not in providers:
                raise DomainError("VALIDATION_FAILED", f"{TASKS[task]}：提供商 {pid} 不存在。")
            p = providers[pid]
            model = model or p.default_model or ""
            if p.models and model not in p.models:
                raise DomainError("VALIDATION_FAILED", f"{TASKS[task]}：{p.name} 没有模型 {model}。")
            rows.append({"provider_id": pid, "model": model})
        if len(rows) > 5:
            raise DomainError("VALIDATION_FAILED", f"{TASKS[task]}最多设 5 个备选。")
        clean[task] = rows
    before = _routes(book)
    _save_routes(book, clean)
    session.flush()
    audit.record(session, ctx, "ai_routes.update", "book", book_id, before={"routes": before}, after={"routes": clean})
    return get_routes(session, book_id)


def env_target(settings: Settings) -> Target | None:
    """BK_AI_* as a provider: the default until 设置 → AI routes the task elsewhere."""
    if not settings.ai_key:
        return None
    return Target(
        provider_id=None,
        provider_name=ENV_NAME,
        kind="anthropic",
        model=settings.ai_model,
        api_key=settings.ai_key,
        timeout=240.0,
        capabilities=Capabilities(fallback=settings.ai_model in FALLBACK_MODELS),
        options={"effort": settings.ai_effort},
    )


def _target(p: AiProvider, model: str, settings: Settings) -> Target:
    assert p.api_key_sealed is not None
    return Target(
        provider_id=p.id,
        provider_name=p.name,
        kind=p.kind,  # type: ignore[arg-type]
        model=model or p.default_model or "",
        api_key=secrets.unseal(p.api_key_sealed, settings, _bound(p.id, p.base_url)),
        base_url=p.base_url,
        timeout=float(p.timeout_seconds),
        capabilities=Capabilities.of(p.capabilities),
        options=dict(p.options or {}),
        prices=dict(p.prices or {}),
    )


def targets(session: Session, book_id: str, task: str, settings: Settings) -> list[Target]:
    """Where a task's calls go, in order: the routed providers that are enabled and have a key, else BK_AI_*."""
    book = session.get(Book, book_id)
    assert book is not None
    providers = {p.id: p for p in list_providers(session, book_id)}
    found = [
        _target(providers[r["provider_id"]], r["model"], settings)
        for r in _routes(book).get(task, [])
        if r["provider_id"] in providers
        and providers[r["provider_id"]].enabled
        and providers[r["provider_id"]].api_key_sealed
    ]
    if found:
        return found
    env = env_target(settings)
    return [env] if env else []


def available(session: Session, book_id: str, task: str, settings: Settings) -> bool:
    try:
        return bool(targets(session, book_id, task, settings))
    except DomainError:
        return False


def call(
    candidates: list[Target],
    request: adapters.Request,
    *,
    backend: adapters.Backend | None = None,
    attempts: list[dict[str, Any]] | None = None,
) -> tuple[Target, adapters.Response]:
    """Try each target in order; an unavailable one hands over to the next. A problem with the input itself
    (the file can't be read) is not the provider's fault and stops at once."""
    if not candidates:
        raise DomainError("AI_UNAVAILABLE", "AI 还没配置：在 设置 → AI 添加提供商，或在服务器上设置 BK_AI_API_KEY。")
    last: DomainError | None = None
    for target in candidates:
        try:
            response = adapters.complete(target, request, backend)
        except DomainError as exc:
            if attempts is not None:
                attempts.append({"target": target, "usage": Usage(), "ok": False, "error": exc.detail})
            if exc.code != "AI_UNAVAILABLE":
                raise
            last = exc
            continue
        if attempts is not None:
            attempts.append({"target": target, "usage": response.usage, "ok": True})
        return target, response
    assert last is not None
    raise last


# ------------------------------------------------------------------ test & usage


def probe_provider(
    session: Session, ctx: RequestContext, provider_id: str, settings: Settings, backend: adapters.Backend | None = None
) -> dict[str, Any]:
    """A tiny request to the default model and the provider's model list: does it answer, what does it offer."""
    _web_only(ctx)
    p = get_provider(session, ctx.require_book(), provider_id)
    target = _target(p, p.default_model or "", settings)
    impl = backend or adapters.backend_for(target)
    result: dict[str, Any] = {"provider_id": p.id, "model": target.model, "capabilities": target.capabilities.as_dict()}
    try:
        result["models"] = impl.list_models(target)[:200]
    except DomainError as exc:
        result["models"] = None
        result["models_error"] = exc.detail
    started = time.monotonic()
    try:
        reply = adapters.complete(
            target,
            adapters.Request(
                system="Reply with the single word OK.",
                messages=[adapters.Message("user", [adapters.Part.of_text("ping")])],
                max_tokens=16,
            ),
            impl,
        )
        result |= {"ok": True, "reply": reply.text[:40], "latency_ms": int((time.monotonic() - started) * 1000)}
        record_usage(session, p.book_id, target, "test", reply.usage, ok=True)
    except DomainError as exc:
        result |= {"ok": False, "error": exc.detail, "latency_ms": int((time.monotonic() - started) * 1000)}
    return result


def record_usage(
    session: Session, book_id: str, target: Target, task: str, usage: Usage, *, ok: bool = True, ref: str | None = None
) -> None:
    spend = adapters.cost(target, usage)
    session.add(
        AiUsage(
            id=new_id("aiu"),
            book_id=book_id,
            provider_id=target.provider_id,
            provider_name=target.provider_name,
            model=target.model,
            task=task,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost=Decimal(str(round(spend, 6))) if spend is not None else None,
            ok=ok,
            ref=ref,
        )
    )


def usage_summary(session: Session, book_id: str, days: int = 30) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(
            AiUsage.provider_name,
            AiUsage.model,
            AiUsage.task,
            func.count(),
            func.sum(AiUsage.input_tokens),
            func.sum(AiUsage.output_tokens),
            func.sum(AiUsage.cost),
            func.count(AiUsage.cost),
        )
        .where(AiUsage.book_id == book_id, AiUsage.created_at >= since)
        .group_by(AiUsage.provider_name, AiUsage.model, AiUsage.task)
        .order_by(AiUsage.provider_name, AiUsage.model, AiUsage.task)
    ).all()
    items = [
        {
            "provider": provider,
            "model": model,
            "task": task,
            "task_label": TASKS.get(task, "测试连接" if task == "test" else task),
            "calls": calls,
            "input_tokens": int(tin or 0),
            "output_tokens": int(tout or 0),
            "cost_usd": float(spend) if spend is not None else None,
            "cost_complete": priced == calls,
        }
        for provider, model, task, calls, tin, tout, spend, priced in rows
    ]
    return {"days": days, "items": items}
