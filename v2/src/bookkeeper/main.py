"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, nullcontext

from fastapi import APIRouter, FastAPI
from sqlalchemy.orm import sessionmaker
from starlette.routing import Route

from bookkeeper import __version__
from bookkeeper.api import errors
from bookkeeper.api.middleware import RequestContextMiddleware
from bookkeeper.api.routers import (
    accounts,
    ai,
    analytics,
    audit,
    auth,
    books,
    business,
    exports,
    files,
    health,
    imports,
    jobs,
    ledger,
    meta,
    operations,
    reference,
    tokens,
    transactions,
    users,
)
from bookkeeper.config import Settings, get_settings
from bookkeeper.db.session import make_engine
from bookkeeper.files.storage import ContentStore
from bookkeeper.logging import configure_logging
from bookkeeper.mcp_api import server as mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    manager = getattr(app.state, "mcp_manager", None)
    async with manager.run() if manager is not None else nullcontext():
        yield


def create_app(settings: Settings | None = None, *, configure_logs: bool = True) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_deployable()
    if configure_logs:
        configure_logging(settings.log_level, settings.log_json)
    app = FastAPI(
        title="bookkeeper",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    engine = make_engine(settings.database_url)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    app.state.content_store = ContentStore(settings.files_dir)
    app.state.alembic_head = health.alembic_head()

    app.add_middleware(RequestContextMiddleware)
    errors.install(app)

    app.include_router(health.router)
    api = APIRouter(prefix="/api/v1")
    for router in (
        auth.router,
        users.router,
        books.router,
        tokens.router,
        files.router,
        audit.router,
        jobs.router,
        meta.router,
        reference.router,
        accounts.router,
        business.router,
        transactions.router,
        ledger.router,
        analytics.router,
        operations.router,
        imports.router,
        exports.router,
        ai.router,
    ):
        api.include_router(router)
    app.include_router(api)
    if settings.mcp_enabled:
        manager, mcp_app = mcp_server.build(app.state.sessionmaker, settings, app.state.content_store)
        app.state.mcp_manager = manager
        for path in ("/mcp", "/mcp/"):
            app.router.routes.append(Route(path, endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))
        if settings.oauth_enabled:
            from bookkeeper.mcp_api import oauth as mcp_oauth

            app.router.routes.extend(mcp_oauth.routes(app.state.sessionmaker, settings))
    if settings.web_dir:
        from bookkeeper.api import web

        web.install(app, settings.web_dir)  # last: the catch-all must not shadow API or MCP routes
    return app
