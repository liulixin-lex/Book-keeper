"""Uploads and attachments."""

from __future__ import annotations

import re
from typing import Any, BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import Attachment, StoredFile
from bookkeeper.domain.errors import DomainError, not_found
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Scope
from bookkeeper.files.storage import ContentStore, FileTooLarge
from bookkeeper.services import audit
from bookkeeper.services.context import RequestContext

ALLOWED_MIME = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "application/pdf",
        "text/csv",
        "text/plain",
        "application/json",
        "application/zip",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
ATTACHMENT_ROLES = frozenset({"receipt", "invoice", "statement", "screenshot", "order_export", "contract", "other"})
_UNSAFE_NAME = re.compile(r"[\x00-\x1f/\\]")


def file_view(item: StoredFile) -> dict[str, Any]:
    return {
        "id": item.id,
        "sha256": item.sha256,
        "size_bytes": item.size_bytes,
        "mime_type": item.mime_type,
        "original_name": item.original_name,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def clean_filename(name: str | None) -> str:
    cleaned = _UNSAFE_NAME.sub("_", (name or "file").strip())[:200]
    return cleaned or "file"


def upload(
    session: Session,
    ctx: RequestContext,
    store: ContentStore,
    stream: BinaryIO,
    *,
    filename: str | None,
    mime_type: str | None,
    max_bytes: int,
) -> tuple[StoredFile, bool]:
    """Store a file; returns (file, created).

    The same content in the same book returns the existing file. Blobs are written before the
    transaction commits; a rolled-back upload leaves an unreferenced blob for later cleanup.
    """
    if not (ctx.has(Scope.LEDGER_WRITE) or ctx.has(Scope.IMPORT_WRITE)):
        ctx.require(Scope.LEDGER_WRITE)
    mime = (mime_type or "application/octet-stream").split(";")[0].strip().lower()
    if mime not in ALLOWED_MIME:
        raise DomainError("UNSUPPORTED_MEDIA_TYPE", f"不支持的文件类型 {mime}。")
    try:
        blob = store.put(stream, max_bytes)
    except FileTooLarge as exc:
        raise DomainError("FILE_TOO_LARGE", f"文件超过上限 {max_bytes // (1024 * 1024)} MB。") from exc
    book_id = ctx.require_book()
    existing = session.execute(
        select(StoredFile).where(StoredFile.book_id == book_id, StoredFile.sha256 == blob.sha256)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    item = StoredFile(
        id=new_id("fil"),
        book_id=book_id,
        sha256=blob.sha256,
        size_bytes=blob.size_bytes,
        mime_type=mime,
        original_name=clean_filename(filename),
        storage_key=blob.storage_key,
        uploaded_by=ctx.actor.user_id,
        token_id=ctx.actor.token_id,
    )
    session.add(item)
    session.flush()
    audit.record(session, ctx, "file.upload", "file", item.id, after=file_view(item))
    return item, True


def get_file(session: Session, ctx: RequestContext, file_id: str) -> StoredFile:
    ctx.require(Scope.LEDGER_READ)
    item = session.get(StoredFile, file_id)
    if item is None or item.book_id != ctx.require_book():
        raise not_found("文件", file_id)
    return item


def attach(
    session: Session,
    ctx: RequestContext,
    *,
    file_id: str,
    entity_type: str,
    entity_id: str,
    role: str,
    note: str | None = None,
) -> Attachment:
    ctx.require(Scope.LEDGER_WRITE)
    if role not in ATTACHMENT_ROLES:
        raise DomainError("VALIDATION_FAILED", f"附件用途 {role} 无效。")
    get_file(session, ctx, file_id)
    item = Attachment(
        id=new_id("att"),
        book_id=ctx.require_book(),
        file_id=file_id,
        entity_type=entity_type,
        entity_id=entity_id,
        role=role,
        note=note,
        created_by=ctx.actor.user_id,
    )
    session.add(item)
    session.flush()
    audit.record(
        session,
        ctx,
        "attachment.create",
        "attachment",
        item.id,
        after={
            "file_id": file_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "role": role,
        },
    )
    return item
