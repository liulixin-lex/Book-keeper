"""Import sources and batches, source records, matching, rules, pairing."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from bookkeeper.api.deps import AuthDep, DbDep, SettingsDep, run_operation, run_read, run_write
from bookkeeper.db.models import ImportBatch, ImportSource
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.scopes import Scope
from bookkeeper.services import ai_extract, ai_providers, files, imports, matching, reference, rules
from bookkeeper.services.inputs import (
    ApplyRulesIn,
    BatchCreateIn,
    ClassifyIn,
    PairingRuleIn,
    RuleIn,
    SourceIn,
    SourcePatch,
)

router = APIRouter(prefix="/books/{book_id}", tags=["imports"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReasonIn(Strict):
    reason: str | None = Field(default=None, max_length=200)


class CommitBody(Strict):
    accept_row_errors: bool = False
    exclude: list[str] = Field(default_factory=list)


class IgnoreIn(Strict):
    record_ids: list[str] = Field(min_length=1, max_length=5000)
    reason: str = Field(default="manual", max_length=100)


class LinkIn(Strict):
    transaction: str = Field(description="交易编号或 ID")


class DecideIn(Strict):
    note: str | None = Field(default=None, max_length=200)


class RuleTestIn(Strict):
    rule: dict[str, Any] | None = None
    code: str | None = None
    source: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=200, ge=1, le=2000)


# ------------------------------------------------------------------ sources


@router.get("/import-sources")
def list_sources(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: [imports.source_view(s) for s in imports.list_sources(db, book_id)], auth.ctx)


@router.post("/import-sources:preview")
async def preview_source(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    kind: Annotated[str, Form(description="来源类型")],
    file: Annotated[UploadFile, File(description="样例文件")],
    config: Annotated[str, Form(description="来源配置（JSON），如列映射 columns / wide")] = "{}",
) -> dict[str, Any]:
    """Try a source setup on a sample file before saving it: the file's top rows, the records it would read
    and the rows it could not. Nothing is stored."""
    auth.ctx.require(Scope.LEDGER_READ)
    content = await file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        raise DomainError("FILE_TOO_LARGE", f"样例文件不能超过 {settings.upload_max_bytes // 1024 // 1024} MB。")
    try:
        parsed_config = json.loads(config or "{}")
    except json.JSONDecodeError as exc:
        raise DomainError("VALIDATION_FAILED", f"config 不是合法的 JSON：{exc.msg}。") from exc
    if not isinstance(parsed_config, dict):
        raise DomainError("VALIDATION_FAILED", "config 必须是 JSON 对象。")
    return run_read(db, lambda: imports.preview(kind, parsed_config, content, file.filename or "sample"), auth.ctx)


@router.post("/import-sources", status_code=201)
def create_source(
    book_id: str, body: SourceIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "import_sources.create",
        body.model_dump(mode="json"),
        lambda: imports.source_view(imports.create_source(db, auth.ctx, body.model_dump())),
        status_code=201,
    )


@router.patch("/import-sources/{ref}")
def update_source(
    book_id: str, ref: str, body: SourcePatch, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "import_sources.update",
        body.model_dump(mode="json") | {"ref": ref},
        lambda: imports.source_view(imports.update_source(db, auth.ctx, ref, body.expected_version, changes)),
    )


# ------------------------------------------------------------------ batches


def _batch_detail(db: DbDep, auth: AuthDep, batch_id: str, limit: int = 100) -> dict[str, Any]:
    batch = imports.get_batch(db, auth.ctx, batch_id)
    src = db.get(ImportSource, batch.source_id)
    scales = reference.commodity_scales(db)
    records = imports.batch_records(db, batch.id, book_id=batch.book_id, limit=limit)
    matches, fee = imports.match_info(db, records), imports.fee_info(db, records)
    return imports.batch_view(batch, src) | {
        "records": [
            imports.record_view(r, scales) | {"match": matches.get(r.id), "fee_rule": fee.get(r.id)} for r in records
        ]
    }


@router.post("/import-batches", status_code=201)
def create_batch(
    book_id: str, body: BatchCreateIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Structured records (e.g. read by an AI from screenshots) or an uploaded file_id → staged batch."""

    def apply() -> dict[str, Any]:
        content, filename = None, "records.json"
        if body.file_id:
            stored = files.get_file(db, auth.ctx, body.file_id)
            content = request.app.state.content_store.open(stored.storage_key).read()
            filename = stored.original_name
        records = [r.model_dump(exclude_none=True) for r in body.records] if body.records is not None else None
        if records is None and content is None:
            raise DomainError("VALIDATION_FAILED", "请提供 records 或 file_id。")
        batch = imports.create_batch(
            db,
            auth.ctx,
            source_ref=body.source,
            content=content,
            filename=filename,
            file_id=body.file_id,
            records=records,
            note=body.note,
        )
        return _batch_detail(db, auth, batch.id)

    return run_write(
        request, db, auth.ctx, settings, "import_batches.create", body.model_dump(mode="json"), apply, status_code=201
    )


@router.post("/import-batches:upload", status_code=201)
async def upload_batch(
    book_id: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    source: Annotated[str, Form(description="来源代码或 ID")],
    file: Annotated[
        list[UploadFile], File(description="CSV / XLSX / JSON；兑换记录页与 AI 识别来源可一次传多个 PDF 或截图")
    ],
    note: Annotated[str | None, Form()] = None,
) -> JSONResponse:
    """Upload a statement and stage it as a batch. An AI 识别 source returns at once with a batch 识别中 that the
    worker fills (poll the batch); sending the same files to the same source again returns that batch instead
    of a second paid read."""
    limit = settings.upload_max_bytes + 1
    uploads = [(f.filename or "upload", await f.read(limit), f.content_type or "") for f in file]
    digest = hashlib.sha256(b"".join(hashlib.sha256(c).digest() for _n, c, _m in uploads)).hexdigest()
    payload = {"source": source, "sha256": digest, "note": note}
    with db.begin():
        src = imports.get_source(db, book_id, source)
        kind = src.kind
        earlier = imports.existing_upload(db, src, digest) if kind == imports.AI_KIND else None
        if earlier is not None:
            return JSONResponse(run_read_inline(db, auth, earlier.id), status_code=200)
        configured = kind == imports.AI_KIND and ai_providers.available(db, book_id, "extract", settings)
    if len(uploads) > 1 and kind not in imports.MULTI_FILE_KINDS:
        raise DomainError("VALIDATION_FAILED", "这个来源一次只能传一个文件。")
    if kind == imports.AI_KIND:
        auth.ctx.require(Scope.IMPORT_WRITE)
        ai_extract.check(
            [(n, m.split(";")[0].strip().lower()) for n, _c, m in uploads], settings, configured=configured
        )

    def apply() -> dict[str, Any]:
        stored = [
            files.upload(
                db,
                auth.ctx,
                request.app.state.content_store,
                io.BytesIO(content),
                filename=name,
                mime_type=mime,
                max_bytes=settings.upload_max_bytes,
            )[0]
            for name, content, mime in uploads
        ]
        if kind == imports.AI_KIND:
            batch = imports.start_extraction(
                db,
                auth.ctx,
                source_ref=source,
                file_ids=[f.id for f in stored],
                digest=digest,
                note=note,
                daily_limit=settings.ai_daily_files,
            )
        else:
            batch = imports.create_batch(
                db,
                auth.ctx,
                source_ref=source,
                content=uploads[0][1],
                filename=stored[0].original_name,
                file_id=stored[0].id,
                note=note,
                more_files=[(c, f.original_name) for (_n, c, _m), f in zip(uploads[1:], stored[1:], strict=True)],
            )
        return _batch_detail(db, auth, batch.id)

    return run_write(request, db, auth.ctx, settings, "import_batches.upload", payload, apply, status_code=201)


def run_read_inline(db: DbDep, auth: AuthDep, batch_id: str) -> dict[str, Any]:
    """The envelope for a batch inside an already open transaction."""
    from bookkeeper.api.envelope import envelope

    return envelope(_batch_detail(db, auth, batch_id), auth.ctx)


@router.post("/import-batches/{batch_id}:retry")
def retry_batch(
    book_id: str, batch_id: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    """Read a batch whose AI read failed again, with the same files."""
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "import_batches.retry",
        {"batch_id": batch_id},
        lambda: _batch_detail(db, auth, imports.retry_extraction(db, auth.ctx, batch_id).id),
    )


@router.get("/import-batches")
def list_batches(
    book_id: str, auth: AuthDep, db: DbDep, status: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict[str, Any]:
    """批次列表，新的在前。每批带 `open_records`：尚未入账的记录数（待补全的，以及已补全、等完成导入的）。"""
    auth.ctx.require(Scope.LEDGER_READ)
    from sqlalchemy import select

    def load() -> list[dict[str, Any]]:
        imports.expire_stalled(db, auth.ctx.require_book())
        stmt = select(ImportBatch).where(ImportBatch.book_id == book_id)
        if status:
            stmt = stmt.where(ImportBatch.status == status)
        rows = list(db.execute(stmt.order_by(ImportBatch.created_at.desc()).limit(limit)).scalars())
        waiting = imports.open_counts(db, [b.id for b in rows])
        return [imports.batch_view(b) | {"open_records": waiting.get(b.id, 0)} for b in rows]

    return run_read(db, load, auth.ctx)


@router.get("/import-batches/{batch_id}")
def get_batch(
    book_id: str, batch_id: str, auth: AuthDep, db: DbDep, limit: Annotated[int, Query(ge=0, le=5000)] = 100
) -> dict[str, Any]:
    return run_read(db, lambda: _batch_detail(db, auth, batch_id, limit), auth.ctx)


@router.post("/import-batches/{batch_id}:commit")
def commit_batch(
    book_id: str, batch_id: str, body: CommitBody, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    raw = body.model_dump(mode="json", exclude_none=True) | {"batch_id": batch_id}
    return run_operation(request, db, auth.ctx, settings, "imports.commit", raw)


@router.post("/import-batches/{batch_id}:revert")
def revert_batch(
    book_id: str,
    batch_id: str,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    body: ReasonIn | None = None,
) -> JSONResponse:
    raw = {"batch_id": batch_id, "reason": body.reason if body else None}
    return run_operation(request, db, auth.ctx, settings, "imports.revert", raw)


# ------------------------------------------------------------------ source records & matching


class DecideMatchesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    same: bool = Field(description="true：都是已记过的那笔（作为凭证关联）；false：都不是（单独入账）")
    record_ids: list[str] | None = Field(default=None, description="只处理这些记录；省略则处理整批")


@router.post("/import-batches/{batch_id}:decide-matches")
def decide_matches(
    book_id: str,
    batch_id: str,
    body: DecideMatchesIn,
    request: Request,
    auth: AuthDep,
    db: DbDep,
    settings: SettingsDep,
) -> JSONResponse:
    """Answer all of a batch's "may already be booked" questions at once."""
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "import_batches.decide_matches",
        body.model_dump() | {"batch_id": batch_id},
        lambda: imports.decide_batch_matches(db, auth.ctx, batch_id, body.same, body.record_ids),
    )


@router.get("/source-records")
def search_records(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    status: str | None = None,
    source: str | None = None,
    batch_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)

    def load() -> list[dict[str, Any]]:
        source_id = imports.get_source(db, book_id, source).id if source else None
        scales = reference.commodity_scales(db)
        rows = imports.batch_records(
            db,
            batch_id,
            book_id=book_id,
            status=status,
            source=source_id,
            date_from=date_from,
            date_to=date_to,
            text=q,
            limit=limit,
            offset=offset,
        )
        matches, fee = imports.match_info(db, rows), imports.fee_info(db, rows)
        return [imports.record_view(r, scales) | {"match": matches.get(r.id), "fee_rule": fee.get(r.id)} for r in rows]

    return run_read(db, load, auth.ctx)


@router.patch("/source-records/{record_id}")
def classify(
    book_id: str, record_id: str, body: ClassifyIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    changes = body.model_dump(exclude_unset=True)
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "source_records.classify",
        changes | {"record_id": record_id},
        lambda: imports.record_view(
            imports.set_classification(db, auth.ctx, record_id, changes), reference.commodity_scales(db)
        ),
    )


@router.post("/source-records:ignore")
def ignore(
    book_id: str, body: IgnoreIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "source_records.ignore",
        body.model_dump(),
        lambda: {"ignored": len(imports.ignore_records(db, auth.ctx, body.record_ids, body.reason))},
    )


@router.post("/source-records/{record_id}:link")
def link(
    book_id: str, record_id: str, body: LinkIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "source_records.link",
        body.model_dump() | {"record_id": record_id},
        lambda: imports.record_view(
            imports.link_record(db, auth.ctx, record_id, body.transaction), reference.commodity_scales(db)
        ),
    )


@router.get("/match-suggestions")
def suggestions(
    book_id: str,
    auth: AuthDep,
    db: DbDep,
    batch_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Pending suggestions (oldest first); ``batch_id`` narrows them to one import."""
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(
        db, lambda: [matching.suggestion_view(s) for s in matching.pending(db, book_id, limit, batch_id)], auth.ctx
    )


@router.post("/match-suggestions/{suggestion_id}:accept")
def accept(
    book_id: str, suggestion_id: str, body: DecideIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "match.accept",
        {"id": suggestion_id, "note": body.note},
        lambda: matching.suggestion_view(imports.decide_match(db, auth.ctx, suggestion_id, True, body.note)),
    )


@router.post("/match-suggestions/{suggestion_id}:reject")
def reject(
    book_id: str, suggestion_id: str, body: DecideIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "match.reject",
        {"id": suggestion_id, "note": body.note},
        lambda: matching.suggestion_view(imports.decide_match(db, auth.ctx, suggestion_id, False, body.note)),
    )


# ------------------------------------------------------------------ rules & pairing


@router.get("/rules")
def list_rules(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    auth.ctx.require(Scope.LEDGER_READ)
    return run_read(db, lambda: [rules.view(r) for r in rules.list_rules(db, book_id)], auth.ctx)


@router.post("/rules", status_code=201)
def save_rule(
    book_id: str, body: RuleIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "rules.save",
        body.model_dump(mode="json"),
        lambda: rules.view(rules.save_rule(db, auth.ctx, body.model_dump())),
        status_code=201,
    )


@router.post("/rules/{ref}:enable")
def enable_rule(
    book_id: str, ref: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "rules.enable",
        {"ref": ref},
        lambda: rules.view(rules.set_active(db, auth.ctx, ref, True)),
    )


@router.post("/rules/{ref}:disable")
def disable_rule(
    book_id: str, ref: str, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "rules.disable",
        {"ref": ref},
        lambda: rules.view(rules.set_active(db, auth.ctx, ref, False)),
    )


@router.post("/rules:test")
def test_rule(book_id: str, body: RuleTestIn, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    return run_read(db, lambda: rules.try_rule(db, auth.ctx, **body.model_dump()), auth.ctx)


@router.post("/rules:apply")
def apply_rules(
    book_id: str, body: ApplyRulesIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_operation(request, db, auth.ctx, settings, "rules.apply", body.model_dump(mode="json"))


@router.get("/pairing-rules")
def list_pairing(book_id: str, auth: AuthDep, db: DbDep) -> dict[str, Any]:
    return run_read(db, lambda: [matching.pairing_view(r) for r in matching.list_pairing_rules(db, book_id)], auth.ctx)


@router.post("/pairing-rules", status_code=201)
def save_pairing(
    book_id: str, body: PairingRuleIn, request: Request, auth: AuthDep, db: DbDep, settings: SettingsDep
) -> JSONResponse:
    return run_write(
        request,
        db,
        auth.ctx,
        settings,
        "pairing_rules.save",
        body.model_dump(mode="json"),
        lambda: matching.pairing_view(matching.save_pairing_rule(db, auth.ctx, body.model_dump())),
        status_code=201,
    )
