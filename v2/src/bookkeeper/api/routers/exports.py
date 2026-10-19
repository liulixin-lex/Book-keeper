"""Ledger exports: CSV, XLSX, Beancount, JSON downloads."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep
from bookkeeper.services import exports as service

router = APIRouter(prefix="/books/{book_id}", tags=["exports"])


@router.get("/exports/{fmt}")
def export_ledger(
    book_id: str,
    fmt: Literal["csv", "xlsx", "beancount", "json"],
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    date_from: date | None = None,
    date_to: date | None = None,
) -> FileResponse:
    """Journal lines of the range (all when omitted) in entry order; the Beancount file passes bean-check."""
    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=tmp_dir, prefix="export-")
    try:
        with os.fdopen(fd, "wb") as fh, db.begin():
            info = service.export_to(db, auth.ctx, fmt, fh, date_from, date_to)
    except BaseException:
        os.unlink(tmp_name)
        raise
    disposition = f"attachment; filename*=UTF-8''{quote(info['filename'])}"
    return FileResponse(
        tmp_name,
        media_type=info["media_type"],
        headers={"Content-Disposition": disposition, "X-Export-Lines": str(info["lines"])},
        background=BackgroundTask(os.unlink, tmp_name),
    )
