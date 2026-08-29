from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app import __version__
from app.api.router import api_router
from app.config import get_settings
from app.db import Base, SessionLocal, engine, validate_sqlite_runtime
from app.logging_config import configure_logging
from app.schemas import HealthRead
from app.services.seed import seed_defaults

settings = get_settings()
configure_logging()
logger = logging.getLogger("ledger.api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_sqlite_runtime()
    if settings.is_production and settings.app_secret_key == "development-only-change-me":
        raise RuntimeError("APP_SECRET_KEY must be changed in production")
    if not settings.is_production:
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed_defaults(session)
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        },
    )
    return response


@app.get("/health", response_model=HealthRead, tags=["system"])
def health() -> HealthRead:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return HealthRead(status="ok", sqlite_version=sqlite3.sqlite_version, database="ready")


app.include_router(api_router, prefix=settings.api_prefix)

# Serve Frontend Static Assets if built
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")
