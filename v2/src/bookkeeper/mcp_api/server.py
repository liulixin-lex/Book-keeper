"""Streamable HTTP MCP endpoint at ``/mcp`` (official SDK low-level server, stateless, JSON responses).

Authentication is a Bearer API token with ``mcp_enabled``; the token fixes the book and the scopes,
and tools the token cannot use are not listed. Every call is logged to ``mcp_calls``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp, StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send

from bookkeeper import __version__
from bookkeeper.config import Settings
from bookkeeper.db.models import McpCall
from bookkeeper.domain.errors import DomainError, FieldError
from bookkeeper.domain.ids import new_id
from bookkeeper.mcp_api import content
from bookkeeper.mcp_api.tools import TOOLS, Output, Tool
from bookkeeper.services import idempotency, identity, operations, ratelimit
from bookkeeper.services.context import Actor, RequestContext

log = logging.getLogger("bookkeeper.mcp")
MAX_LOGGED_ARGS = 20_000


@dataclass(frozen=True)
class McpAuth:
    actor: Actor
    book_id: str
    client: str | None
    ip: str | None
    user_agent: str | None
    rate_limit: int


def _header(scope: Scope, name: str) -> str | None:
    key = name.lower().encode("latin-1")
    for k, v in scope.get("headers", []):
        if k == key:
            return str(v.decode("latin-1"))
    return None


async def _reject(send: Send, status: int, code: str, message: str, extra_headers: list[tuple[bytes, bytes]]) -> None:
    body = json.dumps({"error": code, "message": message}, ensure_ascii=False).encode()
    headers = [(b"content-type", b"application/json; charset=utf-8"), *extra_headers]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class AuthMiddleware:
    """Bearer token check before the MCP transport; the result is put on ``scope['state']``."""

    def __init__(self, app: ASGIApp, factory: sessionmaker[Session], settings: Settings) -> None:
        self.app = app
        self.factory = factory
        self.settings = settings
        self.challenge = 'Bearer realm="bookkeeper"'
        if settings.oauth_enabled:  # RFC 9728: tell OAuth-capable clients where to sign in
            base = settings.public_url.rstrip("/")
            self.challenge += f', resource_metadata="{base}/.well-known/oauth-protected-resource/mcp"'

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["method"] == "GET":  # stateless server: no standalone SSE stream (spec allows 405)
            await _reject(
                send,
                405,
                "METHOD_NOT_ALLOWED",
                "本服务为无状态 JSON 模式，请使用 POST。",
                [(b"allow", b"POST, DELETE")],
            )
            return
        authorization = _header(scope, "authorization") or ""
        kind, _, raw = authorization.partition(" ")
        challenge = [(b"www-authenticate", self.challenge.encode())]
        if kind.lower() != "bearer" or not raw.strip():
            await _reject(
                send, 401, "UNAUTHENTICATED", "请在 Authorization 头提供 Bearer 令牌（bk_pat_…）。", challenge
            )
            return
        forwarded = _header(scope, "x-forwarded-for")
        client = scope.get("client")
        ip = forwarded.split(",")[0].strip() if forwarded else (client[0] if client else None)
        user_agent = _header(scope, "user-agent")
        mcp_client = (_header(scope, "x-mcp-client") or user_agent or "")[:100] or None
        try:
            auth = await anyio.to_thread.run_sync(self._authenticate, raw.strip(), ip, mcp_client, user_agent)
        except DomainError as exc:
            headers = challenge if exc.status == 401 else []
            if exc.code == "RATE_LIMITED":
                headers = [(b"retry-after", str(exc.extra.get("retry_after", 5)).encode())]
            await _reject(send, exc.status, exc.code, exc.detail, headers)
            return
        scope.setdefault("state", {})["bk_auth"] = auth
        await self.app(scope, receive, send)

    def _authenticate(self, raw: str, ip: str | None, client: str | None, user_agent: str | None) -> McpAuth:
        with self.factory() as session, session.begin():
            result = identity.authenticate_token(session, raw, None, ip, client)
            token = result.token
            assert token is not None
            if not token.mcp_enabled:
                raise DomainError("FORBIDDEN_SCOPE", "该令牌未启用 MCP 访问（创建令牌时设置 mcp_enabled）。")
            ratelimit.hit(session, f"t:{token.id}", token.rate_limit_per_min)
            return McpAuth(result.actor, token.book_id, client, ip, user_agent, token.rate_limit_per_min)


# ------------------------------------------------------------------ tool execution


def visible(tool: Tool, actor: Actor, settings: Settings) -> bool:
    if tool.kind != "read" and not settings.mcp_write_enabled:
        return False
    if tool.any_of and not set(tool.any_of) & actor.scopes:
        return False
    return all(scope in actor.scopes for scope in tool.scopes)


def tool_schema(tool: Tool) -> types.Tool:
    schema = tool.model.model_json_schema()
    read = tool.kind == "read"
    return types.Tool(
        name=tool.name,
        title=tool.title,
        description=tool.description,
        input_schema=schema,
        annotations=types.ToolAnnotations(
            title=tool.title,
            read_only_hint=read,
            destructive_hint=tool.kind == "high",
            idempotent_hint=read,
            open_world_hint=False,
        ),
    )


def _envelope(
    ok: bool,
    code: str,
    message: str,
    ctx: RequestContext,
    data: Any = None,
    *,
    warnings: list[dict[str, Any]] | None = None,
    next_action: dict[str, Any] | None = None,
    extra_meta: dict[str, Any] | None = None,
    error: DomainError | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"request_id": ctx.request_id, "book_id": ctx.book_id}
    if ctx.change_set_id:
        meta["change_set_id"] = ctx.change_set_id
    if ctx.dry_run:
        meta["dry_run"] = True
    meta |= extra_meta or {}
    body: dict[str, Any] = {
        "ok": ok,
        "code": code,
        "message": message,
        "data": data,
        "warnings": warnings or [],
        "next_action": next_action,
        "meta": meta,
    }
    if error is not None:
        body["retryable"] = error.retryable
        body["errors"] = [e.__dict__ for e in error.errors]
        body["candidates"] = error.candidates
        body["details"] = error.extra or None
    result: dict[str, Any] = json.loads(json.dumps(body, ensure_ascii=False, default=str))
    return result


def _validation_error(exc: ValidationError) -> DomainError:
    errors = [FieldError(".".join(str(p) for p in e["loc"]), "INPUT_INVALID", e["msg"]) for e in exc.errors()]
    first = errors[0]
    return DomainError(
        "VALIDATION_FAILED",
        f"参数有 {len(errors)} 处问题：{first.path} {first.message}。查看工具的 inputSchema 后重试。",
        errors=errors,
    )


class Executor:
    def __init__(self, factory: sessionmaker[Session], settings: Settings, store: Any = None) -> None:
        self.factory = factory
        self.settings = settings
        self.store = store

    def context(self, auth: McpAuth, idempotency_key: str | None = None) -> RequestContext:
        return RequestContext(
            actor=auth.actor,
            channel="mcp",
            book_id=auth.book_id,
            ip=auth.ip,
            user_agent=auth.user_agent,
            idempotency_key=idempotency_key,
            content_store=self.store,
        )

    def call(self, auth: McpAuth, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        started = time.monotonic()
        ctx = self.context(auth, arguments.get("idempotency_key") if isinstance(arguments, dict) else None)
        try:
            tool = TOOLS.get(name)
            if tool is None or not visible(tool, auth.actor, self.settings):
                raise DomainError(
                    "NOT_FOUND" if tool is None else "FORBIDDEN_SCOPE",
                    f"工具 {name} 不存在。" if tool is None else f"当前令牌不能使用工具 {name}。",
                    extra={
                        "available": sorted(t.name for t in TOOLS.values() if visible(t, auth.actor, self.settings))
                    },
                )
            if tool.kind != "read":
                with self.factory() as session, session.begin():
                    ratelimit.hit(session, f"w:{auth.actor.token_id}", ratelimit.WRITE_LIMIT_PER_MIN)
            try:
                args = tool.model.model_validate(arguments)
            except ValidationError as exc:
                raise _validation_error(exc) from exc
            body = self._dispatch(tool, args, ctx)
            ok = True
        except DomainError as exc:
            body = _envelope(False, exc.code, exc.detail, ctx, warnings=None, next_action=exc.next_action, error=exc)
            ok = False
        except Exception:
            log.exception("mcp tool %s failed", name)
            body = _envelope(False, "INTERNAL", "服务器内部错误，已记录。请稍后重试或联系管理员。", ctx)
            ok = False
        self._log(auth, ctx, "tools/call", name, arguments, body, ok, started)
        return body, not ok

    def _dispatch(self, tool: Tool, args: Any, ctx: RequestContext) -> dict[str, Any]:
        if tool.operation:
            op = operations.get(tool.operation)
            op_args = op.parse(args.model_dump(mode="json", exclude={"dry_run", "idempotency_key"}, exclude_unset=True))
            if args.dry_run:
                with self.factory() as session:
                    data = operations.run_dry(session, ctx, op, op_args)
                return _envelope(True, "DRY_RUN", "试算结果（未保存）", ctx, data, warnings=_warnings(data))
            return self._idempotent(ctx, tool, args, lambda s: _from_operation(op.name, op.run(s, ctx, op_args)))
        assert tool.handler is not None
        handler = tool.handler
        if tool.kind == "read":
            with self.factory() as session:
                tx = session.begin()
                try:
                    out = handler(session, ctx, args)
                    if tool.rollback:
                        tx.rollback()
                    else:
                        tx.commit()
                except BaseException:
                    if tx.is_active:
                        tx.rollback()
                    raise
            ctx.change_set_id = None if tool.rollback else ctx.change_set_id
            return _envelope(True, "OK", out.message, ctx, out.data, warnings=out.warnings, next_action=out.next_action)
        if getattr(args, "dry_run", False):
            ctx.dry_run = True
            with self.factory() as session:
                tx = session.begin()
                try:
                    out = handler(session, ctx, args)
                finally:
                    tx.rollback()
                    ctx.change_set_id = None
            return _envelope(True, "DRY_RUN", out.message + "（试算，未保存）", ctx, out.data, warnings=out.warnings)
        return self._idempotent(ctx, tool, args, lambda s: handler(s, ctx, args))

    def _idempotent(self, ctx: RequestContext, tool: Tool, args: Any, run: Any) -> dict[str, Any]:
        """Run a write in one transaction; with an idempotency key, a retry returns the first result."""
        with self.factory() as session, session.begin():
            claim: idempotency.Claim | None = None
            if ctx.idempotency_key:
                payload = args.model_dump(mode="json", exclude={"idempotency_key"})
                req_hash = idempotency.request_hash("MCP", tool.name, payload)
                started = idempotency.begin(
                    session, ctx, f"mcp.{tool.name}", req_hash, self.settings.idempotency_retention_days
                )
                if isinstance(started, idempotency.Replay):
                    replay: dict[str, Any] = dict(started.body)
                    replay["meta"] = {**replay.get("meta", {}), "idempotent_replayed": True}
                    return replay
                claim = started
            out: Output = run(session)
            code = "OK"
            body = _envelope(True, code, out.message, ctx, out.data, warnings=out.warnings, next_action=out.next_action)
            if claim is not None:
                idempotency.complete(session, claim, 200, body)
            return body

    def _log(
        self,
        auth: McpAuth,
        ctx: RequestContext,
        method: str,
        tool: str | None,
        arguments: Any,
        body: dict[str, Any],
        ok: bool,
        started: float,
    ) -> None:
        logged = arguments if isinstance(arguments, dict) else {"_": str(arguments)}
        text = json.dumps(logged, ensure_ascii=False, default=str)
        if len(text) > MAX_LOGGED_ARGS:
            logged = {"_truncated": text[:MAX_LOGGED_ARGS]}
        try:
            with self.factory() as session, session.begin():
                session.add(
                    McpCall(
                        id=new_id("cal"),
                        book_id=auth.book_id,
                        token_id=auth.actor.token_id,
                        user_id=auth.actor.user_id,
                        client=auth.client,
                        method=method,
                        tool=tool,
                        args=logged,
                        ok=ok,
                        result_code=str(body.get("code")),
                        summary=str(body.get("message"))[:500],
                        duration_ms=int((time.monotonic() - started) * 1000),
                        change_set_id=body.get("meta", {}).get("change_set_id"),
                        request_id=ctx.request_id,
                    )
                )
        except Exception:  # logging must never break the call
            log.exception("could not log mcp call")


def _warnings(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        found = data.get("warnings")
        if isinstance(found, list):
            return found
    return []


COUNT_LABELS = {
    "booked": "入账",
    "suspense": "记入待核对",
    "paired": "配对",
    "linked": "关联已有交易",
    "pending_match": "待确认匹配",
    "left_unbooked": "待补全",
    "duplicate": "重复",
    "ignored": "忽略",
    "excluded": "排除",
    "failed": "失败",
    "deleted": "删除",
    "unlinked": "解除关联",
}


def _counts(counts: dict[str, int]) -> str:
    return "，".join(f"{COUNT_LABELS[k]} {v}" for k, v in counts.items() if v and k in COUNT_LABELS) or "无变化"


def _from_operation(name: str, data: dict[str, Any]) -> Output:
    """The receipt's one-line message, by operation."""
    number = data.get("number", "")
    messages = {
        "transactions.create": lambda: f"已记账 {number} {data.get('description', '')}",
        "transactions.batch": lambda: f"成功 {data['created']} 笔，失败 {data['failed']} 笔",
        "transactions.edit": lambda: f"已修改 {number}（版本 {data.get('version')}）",
        "transactions.delete": lambda: f"已删除 {number}；可用 restore_transaction 恢复",
        "transactions.restore": lambda: f"已恢复 {number}",
        "transactions.repost": lambda: (
            f"检查 {data['checked']} 笔：按新规则重算 {data['reposted']} 笔，未变 {data['unchanged']} 笔"
        ),
        "change_sets.undo": lambda: (
            f"已撤销变更集 {data['change_set_id']}：{len(data['actions'])} 项操作，需人工处理 {len(data['manual'])} 项"
        ),
        "imports.commit": lambda: f"导入完成：{_counts(data.get('counts', {}))}",
        "imports.revert": lambda: f"已撤销导入批次 {data.get('batch_id')}：{_counts(data.get('counts', {}))}",
        "rules.apply": lambda: f"按规则重新分类 {data.get('reclassified', 0)} 条记录",
    }
    message = messages[name]() if name in messages else "完成"
    return Output(data, message.strip(), _warnings(data))


# ------------------------------------------------------------------ server wiring


def build(
    factory: sessionmaker[Session], settings: Settings, store: Any = None
) -> tuple[StreamableHTTPSessionManager, ASGIApp]:
    executor = Executor(factory, settings, store)

    def auth_of(ctx: Any) -> McpAuth:
        request = ctx.request
        auth = getattr(getattr(request, "state", None), "bk_auth", None) if request is not None else None
        if auth is None:
            raise DomainError("UNAUTHENTICATED", "缺少认证信息。")
        assert isinstance(auth, McpAuth)
        return auth

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        auth = auth_of(ctx)
        tools = [tool_schema(t) for t in TOOLS.values() if visible(t, auth.actor, settings)]
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        auth = auth_of(ctx)
        body, is_error = await anyio.to_thread.run_sync(executor.call, auth, params.name, params.arguments or {})
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)], structured_content=body, is_error=is_error
        )

    async def list_resources(ctx: Any, params: Any) -> types.ListResourcesResult:
        auth_of(ctx)
        return types.ListResourcesResult(resources=content.resources())

    async def list_templates(ctx: Any, params: Any) -> types.ListResourceTemplatesResult:
        auth_of(ctx)
        return types.ListResourceTemplatesResult(resource_templates=content.resource_templates())

    async def read_resource(ctx: Any, params: types.ReadResourceRequestParams) -> types.ReadResourceResult:
        auth = auth_of(ctx)
        uri = str(params.uri)
        text, mime = await anyio.to_thread.run_sync(content.read, executor, auth, uri)
        return types.ReadResourceResult(contents=[types.TextResourceContents(uri=uri, mime_type=mime, text=text)])

    async def list_prompts(ctx: Any, params: Any) -> types.ListPromptsResult:
        auth_of(ctx)
        return types.ListPromptsResult(prompts=content.prompts())

    async def get_prompt(ctx: Any, params: types.GetPromptRequestParams) -> types.GetPromptResult:
        auth_of(ctx)
        return content.get_prompt(params.name, dict(params.arguments or {}))

    server: Server[Any] = Server(
        "bookkeeper",
        version=__version__,
        title="bookkeeper 记账",
        instructions=content.INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_list_resource_templates=list_templates,
        on_read_resource=read_resource,
        on_list_prompts=list_prompts,
        on_get_prompt=get_prompt,
    )
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return manager, AuthMiddleware(StreamableHTTPASGIApp(manager), factory, settings)
