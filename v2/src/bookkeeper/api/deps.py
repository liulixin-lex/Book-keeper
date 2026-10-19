"""FastAPI dependencies: settings, DB session, authentication, write helper."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from bookkeeper.api import permissions
from bookkeeper.api.envelope import envelope
from bookkeeper.config import Settings
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.security.secrets import constant_time_equals
from bookkeeper.services import idempotency, identity, operations, ratelimit
from bookkeeper.services.context import Actor, Channel, RequestContext

SESSION_COOKIE = "bk_session"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.sessionmaker()
    try:
        yield session
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


@dataclass
class Auth:
    ctx: RequestContext
    auth: identity.Authenticated
    session_token: str | None = None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and value:
        return value.strip()
    return None


def authenticate(request: Request, db: DbDep, settings: SettingsDep) -> Auth:
    book_id = request.path_params.get("book_id")
    ip = _client_ip(request)
    raw_token = _bearer(request)
    raw_session = request.cookies.get(SESSION_COOKIE)
    channel: Channel
    with db.begin():
        if raw_token:
            result = identity.authenticate_token(db, raw_token, book_id, ip, request.headers.get("x-mcp-client"))
            channel = "api"
        elif raw_session:
            result = identity.authenticate_session(db, settings, raw_session, book_id)
            if request.method not in SAFE_METHODS:
                sent = request.headers.get(CSRF_HEADER, "")
                assert result.session is not None
                if not sent or not constant_time_equals(sent, result.session.csrf_secret):
                    raise DomainError("CSRF_FAILED", "缺少或错误的 X-CSRF-Token 请求头。")
            channel = "ui"
        else:
            raise DomainError("UNAUTHENTICATED", "请先登录，或在 Authorization 头中提供 Bearer 令牌。")
        if result.token is not None:
            ratelimit.hit(db, f"t:{result.token.id}", result.token.rate_limit_per_min)
    if book_id is not None and result.actor.role is None:
        raise DomainError("NOT_FOUND", f"账套 {book_id} 不存在或你不是成员。")
    ctx = RequestContext(
        actor=result.actor,
        channel=channel,
        book_id=book_id,
        request_id=getattr(request.state, "request_id", None) or new_id("req"),
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        idempotency_key=request.headers.get("idempotency-key") or None,
        dry_run=request.query_params.get("dry_run", "").lower() in {"1", "true", "yes"},
    )
    permissions.check(request.method, request.url.path, ctx)
    return Auth(ctx=ctx, auth=result, session_token=raw_session if channel == "ui" else None)


AuthDep = Annotated[Auth, Depends(authenticate)]


def anonymous_context(request: Request) -> RequestContext:
    return RequestContext(
        actor=Actor(type="system"),
        channel="ui",
        request_id=getattr(request.state, "request_id", None) or new_id("req"),
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


def run_read(db: Session, fn: Callable[[], Any], ctx: RequestContext | None = None, **meta: Any) -> dict[str, Any]:
    with db.begin():
        data = fn()
        return envelope(data, ctx, meta=meta or None)


def run_write(
    request: Request,
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    operation: str,
    payload: Any,
    fn: Callable[[], Any],
    *,
    status_code: int = 200,
    secret_fields: tuple[str, ...] = (),
) -> JSONResponse:
    """Idempotent, transactional write. ``fn`` must return JSON-serialisable data.

    ``secret_fields`` (keys of ``data``) are returned once and replaced by ``null`` in the
    cached replay, so secrets such as new API tokens are never stored in plaintext.
    """
    if ctx.dry_run:
        db.begin()
        try:
            body = envelope(fn(), ctx)
        finally:
            db.rollback()
        return JSONResponse(body, status_code=200)
    if ctx.actor.token_id:
        with db.begin():
            ratelimit.hit(db, f"w:{ctx.actor.token_id}", ratelimit.WRITE_LIMIT_PER_MIN)
    req_hash = idempotency.request_hash(request.method, request.url.path, payload)
    with db.begin():
        claim = idempotency.begin(db, ctx, operation, req_hash, settings.idempotency_retention_days)
        if isinstance(claim, idempotency.Replay):
            return JSONResponse(claim.body, status_code=claim.status, headers={"Idempotent-Replayed": "true"})
        body = envelope(fn(), ctx)
        cached = body
        if secret_fields and isinstance(body.get("data"), dict):
            cached = {
                **body,
                "data": {**body["data"], **dict.fromkeys(secret_fields)},
                "meta": {**body["meta"], "secret_fields_withheld": list(secret_fields)},
            }
        idempotency.complete(db, claim, status_code, cached)
    return JSONResponse(body, status_code=status_code)


def run_operation(
    request: Request,
    db: Session,
    ctx: RequestContext,
    settings: Settings,
    name: str,
    raw: dict[str, Any],
    *,
    status_code: int = 200,
    view: Callable[[dict[str, Any]], Any] | None = None,
) -> JSONResponse:
    """Run a registered operation as an idempotent write (or a dry run that is rolled back)."""
    op = operations.get(name)
    args = op.parse(raw)

    def apply() -> Any:
        result = op.run(db, ctx, args)
        return view(result) if view else result

    return run_write(request, db, ctx, settings, name, raw, apply, status_code=status_code)
