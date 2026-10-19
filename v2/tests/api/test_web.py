"""The API process serves the built frontend: app shell for client routes, immutable assets, API paths untouched."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from bookkeeper.config import Settings
from bookkeeper.main import create_app

SCRIPT = 'document.documentElement.dataset.theme = "dark";'


def make_web(tmp_path: Path) -> Path:
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text(f"<!doctype html><html><head><script>{SCRIPT}</script></head><body></body></html>")
    (web / "assets" / "app-1a2b.js").write_text("console.log(1)")
    (web / "favicon.svg").write_text("<svg/>")
    return web


def test_web_shell_assets_and_reserved_paths(tmp_path: Path) -> None:
    app = create_app(
        Settings(database_url="postgresql+psycopg://web@localhost/none", web_dir=make_web(tmp_path)),
        configure_logs=False,
    )
    client = TestClient(app)

    for path in ("/", "/today", "/transactions?tx=T2026-000001", "/settings/ai"):
        page = client.get(path)
        assert page.status_code == 200 and "<script>" in page.text, path
        assert page.headers["cache-control"] == "no-cache"
    digest = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    csp = client.get("/").headers["content-security-policy"]
    assert f"'sha256-{digest}'" in csp and "frame-ancestors 'none'" in csp

    asset = client.get("/assets/app-1a2b.js")
    assert asset.status_code == 200 and "immutable" in asset.headers["cache-control"]
    assert client.get("/favicon.svg").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404

    for reserved in ("/api/v1/nope", "/oauth/nope", "/.well-known/nope"):
        assert client.get(reserved).status_code == 404, reserved
    assert "<script>" in client.get("/%2e%2e/pyproject.toml").text  # traversal falls back to the shell
    app.state.engine.dispose()


def test_no_web_dir_leaves_root_unrouted(tmp_path: Path) -> None:
    app = create_app(Settings(database_url="postgresql+psycopg://web@localhost/none"), configure_logs=False)
    assert TestClient(app).get("/today").status_code == 404
    app.state.engine.dispose()
