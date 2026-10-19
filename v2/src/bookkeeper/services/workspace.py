"""Files for the AI assistant (and MCP clients): read uploaded evidence, keep derived work in a workspace.

- Evidence (uploads, exports) stays read-only in the content-addressed file store; reading it gives its SHA-256 so
  derived work can cite exactly what it came from. Nothing here can change or replace an original.
- The workspace holds text files by path (notes, cleaned CSV, drafts). Every write is audited with the previous
  content, so undoing the change set restores the earlier text or removes a new file.
- Text read from evidence is data, never instructions: callers wrap it and say so (docs/19 §3).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.ai import adapters
from bookkeeper.db.models import AgentFile, StoredFile
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.services import audit, files
from bookkeeper.services.context import RequestContext

MAX_CHARS = 200_000
_SEGMENT = re.compile(r"^[\w.\- ()（）]+$")
TEXT_TYPES = ("text/", "application/json", "application/csv")


def clean_path(path: str) -> str:
    """``notes/2026-10.md`` style: up to 5 folders, no ``..``, no leading slash."""
    parts = [p.strip() for p in path.strip().strip("/").split("/")]
    if not parts or len(parts) > 6 or len("/".join(parts)) > 200:
        raise DomainError("VALIDATION_FAILED", "路径太长：最多 6 级、200 个字符，如 notes/10月对账.md。")
    for part in parts:
        if part in ("", ".", "..") or part.startswith(".") or not _SEGMENT.match(part):
            raise DomainError("VALIDATION_FAILED", f"路径里的“{part}”不行：用文字、数字、空格、. - _ ( )，不以点开头。")
    return "/".join(parts)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def view(item: AgentFile, *, content: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "path": item.path,
        "size": len(item.content.encode()),
        "sha256": item.sha256,
        "version": item.version,
        "updated_at": (item.updated_at or item.created_at).isoformat() if item.created_at else None,
    }
    return out | ({"content": item.content} if content else {})


def list_workspace(session: Session, book_id: str, q: str | None = None, limit: int = 50) -> list[AgentFile]:
    stmt = select(AgentFile).where(AgentFile.book_id == book_id)
    if q:
        stmt = stmt.where(AgentFile.path.ilike(f"%{q}%"))
    return list(session.execute(stmt.order_by(AgentFile.path).limit(limit)).scalars())


def list_evidence(session: Session, book_id: str, q: str | None = None, limit: int = 50) -> list[StoredFile]:
    stmt = select(StoredFile).where(StoredFile.book_id == book_id)
    if q:
        stmt = stmt.where(StoredFile.original_name.ilike(f"%{q}%"))
    return list(session.execute(stmt.order_by(StoredFile.created_at.desc()).limit(limit)).scalars())


def get(session: Session, book_id: str, path: str, *, lock: bool = False) -> AgentFile | None:
    stmt = select(AgentFile).where(AgentFile.book_id == book_id, AgentFile.path == clean_path(path))
    return session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()


def read_evidence(session: Session, ctx: RequestContext, file_id: str, max_chars: int) -> dict[str, Any]:
    """An uploaded file as text where it has text; images and scans are flagged for the caller to show the model."""
    item = files.get_file(session, ctx, file_id)
    out: dict[str, Any] = {"file": files.file_view(item) | {"kind": "evidence"}, "untrusted": True}
    store = ctx.content_store
    data = store.path_for(item.storage_key).read_bytes() if store is not None else b""
    if item.mime_type.startswith(TEXT_TYPES) or item.original_name.lower().endswith((".csv", ".txt", ".json")):
        text = data.decode("utf-8", errors="replace")
    elif item.mime_type == adapters.PDF:
        text = adapters.pdf_text(data)
        if not text.strip():
            return out | {"content": "", "attach": item.id, "note": "扫描件，没有文字层：页面已作为图片附上。"}
    elif item.mime_type in adapters.IMAGE_TYPES:
        return out | {"content": "", "attach": item.id, "note": "图片：内容已附上。"}
    else:
        return out | {"content": "", "note": "这种文件不能直接读成文字；账单表格请用 import_records 导入。"}
    return out | {"content": text[:max_chars], "truncated": len(text) > max_chars}


def write(
    session: Session,
    ctx: RequestContext,
    path: str,
    content: str,
    *,
    expected_version: int | None = None,
    run_id: str | None = None,
) -> AgentFile:
    book_id = ctx.require_book()
    if len(content) > MAX_CHARS:
        raise DomainError("VALIDATION_FAILED", f"内容太长：最多 {MAX_CHARS} 个字符，请拆成几个文件。")
    clean = clean_path(path)
    item = get(session, book_id, clean, lock=True)
    before = None
    if item is None:
        if expected_version not in (None, 0):
            raise DomainError("NOT_FOUND", f"工作区没有 {clean}。")
        item = AgentFile(
            id=new_id("agf"),
            book_id=book_id,
            path=clean,
            content=content,
            sha256=_sha(content),
            run_id=run_id,
            created_by=ctx.actor.user_id,
        )
        session.add(item)
    else:
        if expected_version is None:
            raise DomainError(
                "VERSION_CONFLICT",
                f"{clean} 已存在（版本 {item.version}）：覆盖请传 expected_version={item.version}，"
                "或用 patch_file 改一处。",
                extra={"current_version": item.version},
            )
        if expected_version != item.version:
            raise DomainError(
                "VERSION_CONFLICT", f"{clean} 已是版本 {item.version}。", extra={"current_version": item.version}
            )
        before = {"path": item.path, "content": item.content, "version": item.version}
        item.content, item.sha256, item.version = content, _sha(content), item.version + 1
        item.run_id = run_id or item.run_id
    session.flush()
    audit.ensure_change_set(session, ctx, "workspace.write")
    audit.record(session, ctx, "agent_file.write", "agent_file", item.id, before=before, after=view(item))
    return item


def patch(
    session: Session, ctx: RequestContext, path: str, old: str, new: str, *, expected_version: int | None = None
) -> AgentFile:
    item = get(session, ctx.require_book(), path)
    if item is None:
        raise DomainError("NOT_FOUND", f"工作区没有 {clean_path(path)}。")
    found = item.content.count(old) if old else 0
    if found != 1:
        raise DomainError(
            "VALIDATION_FAILED",
            f"要替换的原文在 {item.path} 里出现 {found} 次：需要恰好 1 次，请多带几个字让它唯一。",
        )
    version = item.version if expected_version is None else expected_version
    return write(session, ctx, item.path, item.content.replace(old, new, 1), expected_version=version)


def undo_write(session: Session, entity_id: str, before: dict[str, Any] | None) -> dict[str, Any]:
    """Put a workspace file back as it was before one write (used by change-set undo)."""
    item = session.get(AgentFile, entity_id, with_for_update=True)
    if item is None:
        return {"agent_file": entity_id, "action": "already_gone"}
    if before is None:
        session.delete(item)
        return {"agent_file": item.path, "action": "removed"}
    item.content, item.sha256, item.version = before["content"], _sha(before["content"]), item.version + 1
    return {"agent_file": item.path, "action": "restored", "version": before.get("version")}
