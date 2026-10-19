"""Serve the built web frontend from the API process: hashed assets with long caching, index.html for app routes.

Same origin as the API, so the session cookie and CSRF header need no CORS. Paths owned by the API
(/api, /mcp, /oauth, /.well-known, /healthz, /readyz) never fall through to the app shell.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.staticfiles import StaticFiles

RESERVED = ("api/", "mcp", "oauth/", ".well-known/", "healthz", "readyz")
INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def _csp(index_html: str) -> str:
    hashes = " ".join(
        f"'sha256-{base64.b64encode(hashlib.sha256(m.encode()).digest()).decode()}'"
        for m in INLINE_SCRIPT.findall(index_html)
    )
    return (
        "default-src 'self'; "
        f"script-src 'self' {hashes}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


class _ImmutableAssets(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def install(app: FastAPI, web_dir: Path) -> None:
    index = web_dir / "index.html"
    if not index.is_file():
        return
    html = index.read_text(encoding="utf-8")
    headers = {
        "Cache-Control": "no-cache",
        "Content-Security-Policy": _csp(html),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "same-origin",
    }
    if (web_dir / "assets").is_dir():
        app.mount("/assets", _ImmutableAssets(directory=web_dir / "assets"), name="web-assets")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def app_shell(path: str, request: Request) -> Response:
        if path.startswith(RESERVED):
            raise HTTPException(status_code=404)
        candidate = (web_dir / path).resolve()
        if path and candidate.is_file() and candidate.parent == web_dir.resolve():
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=86400"})
        return HTMLResponse(html, headers=headers)
