"""MCP tools for import, classification, matching and rules (docs/09 §5.3)."""

from __future__ import annotations

import base64
import binascii
import io
from datetime import date
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import ImportBatch, ImportSource, PairingRule
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.scopes import Scope
from bookkeeper.mcp_api.tools import Args, Output, Tool, tool
from bookkeeper.services import files, imports, matching, reference, rules
from bookkeeper.services.context import RequestContext
from bookkeeper.services.inputs import ClassifyIn, PairingRuleIn, RecordIn, RuleIn, SourceIn

MAX_INLINE_FILE = 10 * 1024 * 1024
MIME = {
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".json": "application/json",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}


def _batch_out(session: Session, ctx: RequestContext, batch_id: str, limit: int = 20) -> dict[str, Any]:
    batch = imports.get_batch(session, ctx, batch_id)
    src = session.get(ImportSource, batch.source_id)
    scales = reference.commodity_scales(session)
    records = imports.batch_records(session, batch.id, book_id=batch.book_id, limit=limit)
    matches, fee = imports.match_info(session, records), imports.fee_info(session, records)
    return imports.batch_view(batch, src) | {
        "records": [
            imports.record_view(r, scales) | {"match": matches.get(r.id), "fee_rule": fee.get(r.id)} for r in records
        ]
    }


class SourceArgs(Args):
    action: Literal["list", "create", "update"]
    source: SourceIn | None = Field(default=None, description="action=create")
    code: str | None = Field(default=None, description="action=update：来源代码")
    expected_version: int | None = None
    changes: dict[str, Any] | None = Field(
        default=None, description="action=update：name / timezone / config / is_active"
    )


def _sources(session: Session, ctx: RequestContext, args: SourceArgs) -> Output:
    book_id = ctx.require_book()
    if args.action == "list":
        data = [imports.source_view(s) for s in imports.list_sources(session, book_id)]
        return Output(data, f"{len(data)} 个导入来源")
    if args.action == "create":
        if args.source is None:
            raise DomainError("VALIDATION_FAILED", "action=create 需要 source。")
        src = imports.create_source(session, ctx, args.source.model_dump())
        return Output(imports.source_view(src), f"已新建导入来源 {src.code}")
    if not args.code or args.expected_version is None:
        raise DomainError("VALIDATION_FAILED", "action=update 需要 code 与 expected_version。")
    src = imports.update_source(session, ctx, args.code, args.expected_version, args.changes or {})
    return Output(imports.source_view(src), f"已修改导入来源 {src.code}")


tool(
    Tool(
        "manage_import_source",
        "导入来源",
        "列出、新建、修改导入来源（微信、支付宝、Stripe、卡网订单、上游兑换记录、通用表格、结构化记录），"
        "config 里设置各方向的默认交易类型与输入、提交方式、未分类处理方式、匹配窗口。",
        SourceArgs,
        "write",
        (Scope.IMPORT_WRITE,),
        _sources,
        rest="import_sources_create",
    )
)


class ImportArgs(Args):
    source: str = Field(description="来源代码或 ID")
    records: list[RecordIn] | None = Field(
        default=None, max_length=20000, description="结构化记录：从截图 / PDF 读出的流水、订单、兑换记录"
    )
    file_name: str | None = Field(default=None, description="随附文件名（决定解析方式：.csv / .xlsx / .json）")
    content_base64: str | None = Field(default=None, description="文件内容（base64，≤ 10 MB）")
    note: str | None = None


def _import(session: Session, ctx: RequestContext, args: ImportArgs) -> Output:
    if args.records is None and not args.content_base64:
        raise DomainError("VALIDATION_FAILED", "请提供 records，或 file_name + content_base64。")
    file_id = None
    content = None
    filename = "records.json"
    if args.content_base64:
        try:
            content = base64.b64decode(args.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DomainError("VALIDATION_FAILED", "content_base64 不是有效的 base64。") from exc
        if len(content) > MAX_INLINE_FILE:
            raise DomainError("FILE_TOO_LARGE", "内联文件超过 10 MB，请改用 REST 上传。")
        filename = args.file_name or "upload.csv"
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ".csv"
        if ctx.content_store is not None:
            stored, _created = files.upload(
                session,
                ctx,
                ctx.content_store,
                io.BytesIO(content),
                filename=filename,
                mime_type=MIME.get(suffix, "text/plain"),
                max_bytes=MAX_INLINE_FILE,
            )
            file_id = stored.id
    records = [r.model_dump(exclude_none=True) for r in args.records] if args.records is not None else None
    batch = imports.create_batch(
        session,
        ctx,
        source_ref=args.source,
        content=content,
        filename=filename,
        file_id=file_id,
        records=records,
        note=args.note,
    )
    data = _batch_out(session, ctx, batch.id)
    summary = batch.summary
    blocking = summary.get("blocking") or []
    message = (
        f"批次 {batch.id}：{summary.get('records', 0)} 条，状态 {summary.get('by_status')}"
        + (f"；安全校验未通过：{', '.join(blocking)}" if blocking else "")
        + (f"；待确认匹配 {summary.get('pending_suggestions')}" if summary.get("pending_suggestions") else "")
    )
    return Output(
        data,
        message,
        next_action={
            "tool": "commit_import",
            "args": {"batch_id": batch.id},
            "hint": "先用 search_source_records 处理未分类与待匹配记录，再提交",
        },
    )


tool(
    Tool(
        "import_records",
        "导入账单",
        "把一批流水 / 订单 / 兑换记录读入为待完成批次（还未入账，commit_import 后入账）：可直接给结构化 records，"
        "或附 CSV / XLSX / JSON 文件（base64）。系统去重、按来源默认值与规则分类、匹配已有交易、跨来源配对。",
        ImportArgs,
        "write",
        (Scope.IMPORT_WRITE,),
        _import,
        rest="import_batches_create",
    )
)


class RecordSearchArgs(Args):
    batch_id: str | None = None
    status: str | None = Field(
        default=None, description="new / classified / matched / booked / ignored / duplicate，可逗号分隔"
    )
    source: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


def _search_records(session: Session, ctx: RequestContext, args: RecordSearchArgs) -> Output:
    book_id = ctx.require_book()
    source_id = imports.get_source(session, book_id, args.source).id if args.source else None
    scales = reference.commodity_scales(session)
    rows = imports.batch_records(
        session,
        args.batch_id,
        book_id=book_id,
        status=args.status,
        source=source_id,
        date_from=args.date_from,
        date_to=args.date_to,
        text=args.q,
        limit=args.limit,
        offset=args.offset,
    )
    suggestions = matching.pending(session, book_id, 200)
    by_record: dict[str, list[dict[str, Any]]] = {}
    for s in suggestions:
        by_record.setdefault(s.record_id, []).append(matching.suggestion_view(s))
    matches, fee = imports.match_info(session, rows), imports.fee_info(session, rows)
    data = [
        imports.record_view(r, scales)
        | {"match": matches.get(r.id), "fee_rule": fee.get(r.id), "suggestions": by_record.get(r.id, [])}
        for r in rows
    ]
    return Output(data, f"{len(data)} 条来源记录")


tool(
    Tool(
        "search_source_records",
        "查找来源记录",
        "按批次、状态、来源、日期、文本查找来源记录，附分类结果、缺失字段、规则轨迹；"
        "match 是它对应（或可能重复）的已记交易，suggestions 是待确认的匹配建议。",
        RecordSearchArgs,
        "read",
        (Scope.LEDGER_READ,),
        _search_records,
        rest="source_records_list",
    )
)


class BatchArgs(Args):
    batch_id: str | None = Field(default=None, description="省略则列出最近的批次")
    limit: int = Field(default=50, ge=0, le=1000)


def _get_batch(session: Session, ctx: RequestContext, args: BatchArgs) -> Output:
    if args.batch_id:
        data = _batch_out(session, ctx, args.batch_id, args.limit)
        return Output(data, f"批次 {args.batch_id}（{data['status']}）")
    rows = session.execute(
        select(ImportBatch)
        .where(ImportBatch.book_id == ctx.require_book())
        .order_by(ImportBatch.created_at.desc())
        .limit(args.limit or 20)
    ).scalars()
    batches = list(rows)
    waiting = imports.open_counts(session, [b.id for b in batches])
    data_list = [imports.batch_view(b) | {"open_records": waiting.get(b.id, 0)} for b in batches]
    return Output(data_list, f"{len(data_list)} 个批次")


tool(
    Tool(
        "get_import_batch",
        "导入批次",
        "批次摘要（统计、安全校验、提交结果）与记录；"
        "不给 batch_id 时列出最近批次，每批带 open_records（尚未入账的记录数）。",
        BatchArgs,
        "read",
        (Scope.LEDGER_READ,),
        _get_batch,
        rest="import_batches_get",
    )
)


class ClassifyArgs(Args):
    record_ids: list[str] = Field(min_length=1, max_length=5000)
    set: ClassifyIn | None = Field(
        default=None, description="设置交易类型、往来方、输入（人工设置的字段不会被规则覆盖）"
    )
    ignore_reason: str | None = Field(default=None, description="改为忽略（如 personal、gift、duplicate）")
    reclassify: bool = Field(default=False, description="按当前规则与来源默认值重新分类")


def _classify(session: Session, ctx: RequestContext, args: ClassifyArgs) -> Output:
    if args.ignore_reason:
        done = imports.ignore_records(session, ctx, args.record_ids, args.ignore_reason)
        return Output({"ignored": [r.id for r in done]}, f"已忽略 {len(done)} 条")
    if args.reclassify:
        count = imports.reclassify(session, ctx, record_ids=args.record_ids)
        return Output({"reclassified": count}, f"已重新分类 {count} 条")
    if args.set is None:
        raise DomainError("VALIDATION_FAILED", "请提供 set、ignore_reason 或 reclassify=true。")
    changes = args.set.model_dump(exclude_unset=True)
    scales = reference.commodity_scales(session)
    data = [
        imports.record_view(imports.set_classification(session, ctx, rid, changes), scales) for rid in args.record_ids
    ]
    incomplete = [d["id"] for d in data if d["status"] != "classified"]
    return Output(data, f"已分类 {len(data)} 条" + (f"，仍缺字段 {len(incomplete)} 条" if incomplete else ""))


tool(
    Tool(
        "classify_records",
        "分类来源记录",
        "批量设置交易类型 / 往来方 / 输入，忽略记录，或按规则重新分类。",
        ClassifyArgs,
        "write",
        (Scope.IMPORT_WRITE,),
        _classify,
        rest="source_records_classify",
    )
)


class Decision(Args):
    suggestion_id: str
    accept: bool
    note: str | None = None


class ResolveArgs(Args):
    decisions: list[Decision] = Field(default_factory=list, max_length=500)
    link: dict[str, str] | None = Field(
        default=None, description='手工关联：{"record_id": "...", "transaction": "T2026-000123"}'
    )


def _resolve(session: Session, ctx: RequestContext, args: ResolveArgs) -> Output:
    results = [
        matching.suggestion_view(imports.decide_match(session, ctx, d.suggestion_id, d.accept, d.note))
        for d in args.decisions
    ]
    linked = None
    if args.link:
        rec = imports.link_record(session, ctx, args.link["record_id"], args.link["transaction"])
        linked = {"record_id": rec.id, "transaction_id": rec.transaction_id}
    return Output(
        {"decisions": results, "linked": linked},
        f"处理建议 {len(results)} 条" + ("，已手工关联 1 条" if linked else ""),
    )


tool(
    Tool(
        "resolve_match",
        "处理匹配",
        "接受 / 拒绝匹配建议，或把记录手工关联到已有交易。拒绝表示“不是同一笔”：该记录的其余猜测一并否掉、"
        "不再提示；已完成导入里的记录随即入账。",
        ResolveArgs,
        "write",
        (Scope.IMPORT_WRITE,),
        _resolve,
        rest="match_suggestions_accept",
    )
)


class RuleArgs(Args):
    action: Literal["list", "save", "enable", "disable", "test"]
    rule: RuleIn | None = Field(default=None, description="action=save / test")
    code: str | None = Field(default=None, description="action=enable / disable / test（已有规则）")
    source: str | None = Field(default=None, description="action=test：限定来源")
    date_from: date | None = None
    date_to: date | None = None


def _rules(session: Session, ctx: RequestContext, args: RuleArgs) -> Output:
    book_id = ctx.require_book()
    if args.action == "list":
        data = [rules.view(r) for r in rules.list_rules(session, book_id)]
        return Output(data, f"{len(data)} 条规则")
    if args.action == "save":
        if args.rule is None:
            raise DomainError("VALIDATION_FAILED", "action=save 需要 rule。")
        row = rules.save_rule(session, ctx, args.rule.model_dump())
        return Output(
            rules.view(row),
            f"已保存规则 {row.code}（版本 {row.version}）",
            next_action={"tool": "apply_rules", "hint": "对未入账记录重新分类", "args": {}},
        )
    if args.action == "test":
        result = rules.try_rule(
            session,
            ctx,
            rule=args.rule.model_dump() if args.rule else None,
            code=args.code,
            source=args.source,
            date_from=args.date_from,
            date_to=args.date_to,
        )
        return Output(result, f"检查 {result['checked']} 条，命中 {result['hits']} 条")
    if not args.code:
        raise DomainError("VALIDATION_FAILED", f"action={args.action} 需要 code。")
    row = rules.set_active(session, ctx, args.code, args.action == "enable")
    return Output(rules.view(row), f"已{'启用' if row.is_active else '停用'}规则 {row.code}")


tool(
    Tool(
        "manage_rule",
        "分类规则",
        "列出、保存（同 code 覆盖为新版本）、启用 / 停用、试运行分类规则（试运行不写入）。",
        RuleArgs,
        "write",
        (Scope.RULES_WRITE,),
        _rules,
        rest="rules_save",
    )
)


class PairingArgs(Args):
    action: Literal["list", "save"]
    rule: PairingRuleIn | None = None


def _pairing(session: Session, ctx: RequestContext, args: PairingArgs) -> Output:
    if args.action == "list":
        rows = session.execute(select(PairingRule).where(PairingRule.book_id == ctx.require_book())).scalars()
        data = [matching.pairing_view(r) for r in rows]
        return Output(data, f"{len(data)} 条配对规则")
    if args.rule is None:
        raise DomainError("VALIDATION_FAILED", "action=save 需要 rule。")
    row = matching.save_pairing_rule(session, ctx, args.rule.model_dump())
    return Output(matching.pairing_view(row), f"已保存配对规则 {row.code}")


tool(
    Tool(
        "manage_pairing_rule",
        "配对规则",
        "跨来源配对（如卡网订单 ↔ 上游兑换记录）：按往来方与面值分组，在时间窗口内求总时间差最小的全局最优配对。",
        PairingArgs,
        "write",
        (Scope.RULES_WRITE,),
        _pairing,
        rest="pairing_rules_save",
    )
)


class SaveRuleArgs(Args):
    record_id: str = Field(description="已改好分类的来源记录（src_…）")
    dry_run: bool = False
    idempotency_key: str | None = None


def _save_rule(session: Session, ctx: RequestContext, args: SaveRuleArgs) -> Output:
    out = rules.rule_from_record(session, ctx, args.record_id)
    return Output(out, f"已存为规则「{out['rule']['name']}」，本批重新分类 {out['reclassified']} 条")


tool(
    Tool(
        "save_rule_from_record",
        "存为规则",
        "把一条已改好分类的导入记录存成分类规则（按对方或商品关键词匹配），并立即重新分类同批的其他记录。"
        "同样的记录文字再存一次会更新同一条规则。先用 classify_records 改好分类再调用。",
        SaveRuleArgs,
        "write",
        (Scope.RULES_WRITE,),
        _save_rule,
        rest="source_records_save_rule",
    )
)
