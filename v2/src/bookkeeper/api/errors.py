"""RFC 9457 problem details for every error."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from bookkeeper.domain.errors import ERROR_SPECS, DomainError, FieldError
from bookkeeper.logging import request_id_var

log = logging.getLogger("bookkeeper.api")
PROBLEM = "application/problem+json"


def problem_body(error: DomainError, base_url: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": f"{base_url.rstrip('/')}/errors/{error.code}",
        "title": error.spec.title,
        "status": error.status,
        "code": error.code,
        "detail": error.detail,
        "retryable": error.retryable,
        "next_action": error.next_action,
        "errors": [e.__dict__ for e in error.errors],
        "candidates": error.candidates,
        "request_id": request_id_var.get(),
    }
    for key, value in error.extra.items():
        body.setdefault(key, value)
    return body


def problem_response(error: DomainError, base_url: str) -> JSONResponse:
    headers = {}
    if error.code in {"RATE_LIMITED", "SNAPSHOT_STALE", "IDEMPOTENCY_IN_PROGRESS"}:
        headers["Retry-After"] = str(error.extra.get("retry_after", 5))
    return JSONResponse(problem_body(error, base_url), status_code=error.status, media_type=PROBLEM, headers=headers)


def _loc_path(loc: tuple[Any, ...]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "request"


def install(app: FastAPI) -> None:
    def base_url() -> str:
        return str(app.state.settings.public_url)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return problem_response(exc, base_url())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            FieldError(_loc_path(tuple(e.get("loc", ()))), e.get("type", "invalid"), e.get("msg", ""))
            for e in exc.errors()
        ]
        return problem_response(
            DomainError("VALIDATION_FAILED", "请求内容不符合要求，请按 errors 修正。", errors=errors),
            base_url(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code)
        if code is None:
            code = "VALIDATION_FAILED" if 400 <= exc.status_code < 500 else "INTERNAL"
        detail = exc.detail if isinstance(exc.detail, str) else ERROR_SPECS[code].title
        return problem_response(DomainError(code, detail), base_url())

    @app.exception_handler(IntegrityError)
    async def integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity error", extra={"error": str(exc.orig)[:500]})
        if getattr(exc.orig, "sqlstate", None) == "23514":
            detail = str(exc.orig).split("\n")[0]
            return problem_response(DomainError("VALIDATION_FAILED", f"数据库拒绝了该写入：{detail}"), base_url())
        return problem_response(DomainError("CONFLICT", "与现有数据冲突，请检查后重试。"), base_url())

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return problem_response(DomainError("INTERNAL", "服务器内部错误，请稍后重试。"), base_url())
