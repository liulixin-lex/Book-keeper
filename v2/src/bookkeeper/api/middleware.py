"""Request id and access logging."""

from __future__ import annotations

import logging
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from bookkeeper.domain.ids import new_id
from bookkeeper.logging import request_id_var

log = logging.getLogger("bookkeeper.access")
_VALID_ID = re.compile(r"^[A-Za-z0-9_.:\-]{8,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_ID.match(incoming) else new_id("req")
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response
