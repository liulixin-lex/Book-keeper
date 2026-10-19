"""File upload, metadata, download, attachments."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_read, run_write
from bookkeeper.domain.scopes import Scope
from bookkeeper.files.storage import ContentStore
from bookkeeper.services import files as service

router = APIRouter(prefix="/books/{book_id}", tags=["files"])


class AttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str
    entity_type: str = Field(min_length=1, max_length=40)
    entity_id: str = Field(min_length=1, max_length=64)
    role: str = "other"
    note: str | None = Field(default=None, max_length=500)


def _store(request: Request) -> ContentStore:
    store: ContentStore = request.app.state.content_store
    return store


@router.post("/files", status_code=201)
def upload_file(
    book_id: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    state: dict[str, Any] = {}

    def apply() -> dict[str, Any]:
        item, created = service.upload(
            db,
            auth.ctx,
            _store(request),
            file.file,
            filename=file.filename,
            mime_type=file.content_type,
            max_bytes=settings.upload_max_bytes,
        )
        state["created"] = created
        return service.file_view(item) | {"created": created}

    payload = {"filename": file.filename, "content_type": file.content_type, "size": file.size}
    return run_write(request, db, auth.ctx, settings, "files.upload", payload, apply, status_code=201)


@router.get("/files/{file_id}")
def get_file(book_id: str, file_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    return run_read(db, lambda: service.file_view(service.get_file(db, auth.ctx, file_id)), auth.ctx)


@router.get("/files/{file_id}/content")
def download_file(book_id: str, file_id: str, request: Request, auth: AuthDep, db: DbDep) -> FileResponse:
    auth.ctx.require(Scope.FILES_READ)
    with db.begin():
        item = service.get_file(db, auth.ctx, file_id)
    path = _store(request).path_for(item.storage_key)
    disposition = f"attachment; filename*=UTF-8''{quote(item.original_name)}"
    return FileResponse(path, media_type=item.mime_type, headers={"Content-Disposition": disposition})


@router.post("/attachments", status_code=201)
def create_attachment(
    book_id: str,
    body: AttachmentCreate,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    def apply() -> dict[str, Any]:
        item = service.attach(
            db,
            auth.ctx,
            file_id=body.file_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            role=body.role,
            note=body.note,
        )
        return {
            "id": item.id,
            "file_id": item.file_id,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "role": item.role,
        }

    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "attachments.create",
        body.model_dump(),
        apply,
        status_code=201,
    )
