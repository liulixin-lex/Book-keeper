"""Ledger exports: CSV, XLSX, Beancount, JSON (docs/07 §5) and the monthly readable archive (docs/10 §3).

Exports read posted journal lines (postings and reversals) in entry order and stream them to a file,
so a whole book never sits in memory. The Beancount file passes ``bean-check``: foreign-currency
postings carry their frozen base amount as a total price (``@@``), so every transaction balances
in the base commodity exactly as in the ledger.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import IO, Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from bookkeeper.db.models import (
    Account,
    Book,
    Counterparty,
    DimensionType,
    DimensionValue,
    JournalEntry,
    JournalLine,
    JournalLineDimension,
    StoredFile,
    Tag,
    Transaction,
    TransactionTag,
    TransactionType,
)
from bookkeeper.domain import labels
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.money import from_minor
from bookkeeper.domain.scopes import Scope
from bookkeeper.files.storage import ContentStore
from bookkeeper.services import audit, files, reference
from bookkeeper.services.context import RequestContext

FORMATS: dict[str, tuple[str, str]] = {
    "csv": ("text/csv", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "beancount": ("text/plain", "beancount"),
    "json": ("application/json", "json"),
}
CSV_COLUMNS = (
    ("entry", "凭证号"),
    ("date", "业务日期"),
    ("kind", "分录类型"),
    ("transaction", "交易号"),
    ("type", "交易类型"),
    ("description", "摘要"),
    ("line_no", "行号"),
    ("account_code", "科目编码"),
    ("account_name", "科目名称"),
    ("commodity", "币种"),
    ("debit", "借方"),
    ("credit", "贷方"),
    ("base_debit", "本位币借方"),
    ("base_credit", "本位币贷方"),
    ("fx_rate", "汇率"),
    ("counterparty", "往来方"),
    ("channel", "渠道"),
    ("line_role", "行用途"),
    ("quantity", "统计数量"),
    ("memo", "行备注"),
    ("external_ref", "外部单号"),
    ("recorded_at", "记录时间"),
)
EXPORT_MAX_BYTES = 2 * 1024**3
ROOTS = {"asset": "Assets", "liability": "Liabilities", "equity": "Equity", "revenue": "Income", "expense": "Expenses"}
_UNSAFE = re.compile(r"[\x00-\x2c\x2e-\x2f\x3a-\x40\x5b-\x60\x7b-\x7f]+")  # ASCII except letters, digits, '-'


@dataclass
class Line:
    entry: str
    date: date
    kind: str
    entry_description: str
    recorded_at: datetime
    transaction: str
    type: str
    description: str
    external_ref: str | None
    line_no: int
    account_id: str
    account_code: str
    account_name: str
    classification: str
    commodity: str
    amount: int
    base_amount: int
    fx_rate: Decimal | None
    counterparty: str | None
    channel: str | None
    line_role: str
    quantity: Decimal | None
    quantity_unit: str | None
    memo: str | None


class Exporter:
    def __init__(self, session: Session, book: Book, date_from: date | None, date_to: date | None) -> None:
        if date_from and date_to and date_from > date_to:
            raise DomainError("VALIDATION_FAILED", "开始日期不能晚于结束日期。")
        self.session = session
        self.book = book
        self.date_from = date_from
        self.date_to = date_to
        self.scales = reference.commodity_scales(session)
        self.base = book.base_commodity
        self.accounts = {a.id: a for a in session.execute(select(Account).where(Account.book_id == book.id)).scalars()}
        self.by_code = {a.code: a for a in self.accounts.values()}
        self._tags: dict[str, list[str]] | None = None

    @property
    def tag_names(self) -> dict[str, list[str]]:
        """Transaction number → tag names, for the transactions in range (loaded once)."""
        if self._tags is None:
            rows = self.session.execute(
                select(Transaction.number, Tag.name)
                .join(TransactionTag, TransactionTag.transaction_id == Transaction.id)
                .join(Tag, Tag.id == TransactionTag.tag_id)
                .where(Transaction.book_id == self.book.id)
                .order_by(TransactionTag.created_at, Tag.name)
            ).all()
            self._tags = {}
            for number, name in rows:
                self._tags.setdefault(number, []).append(name)
        return self._tags

    # ---------------------------------------------------------------- reading

    def _filters(self) -> list[Any]:
        conds: list[Any] = [JournalEntry.book_id == self.book.id]
        if self.date_from:
            conds.append(JournalEntry.effective_date >= self.date_from)
        if self.date_to:
            conds.append(JournalEntry.effective_date <= self.date_to)
        return conds

    def lines(self) -> Iterator[Line]:
        jl, je, t, tt, a = JournalLine, JournalEntry, Transaction, TransactionType, Account
        cp, jld, dv = aliased(Counterparty), aliased(JournalLineDimension), aliased(DimensionValue)
        channel_type = self.session.execute(
            select(DimensionType.id).where(DimensionType.book_id == self.book.id, DimensionType.code == "channel")
        ).scalar_one_or_none()
        stmt = (
            select(
                je.number,
                je.effective_date,
                je.kind,
                je.description,
                je.recorded_at,
                t.number,
                tt.code,
                t.description,
                t.external_ref,
                jl.line_no,
                a.id,
                a.code,
                a.name,
                a.classification,
                jl.commodity,
                jl.amount,
                jl.base_amount,
                jl.fx_rate,
                cp.name,
                dv.name,
                jl.line_role,
                jl.quantity,
                jl.quantity_unit,
                jl.memo,
            )
            .select_from(jl)
            .join(je, je.id == jl.entry_id)
            .join(t, t.id == je.transaction_id)
            .join(tt, tt.id == t.transaction_type_id)
            .join(a, a.id == jl.account_id)
            .outerjoin(cp, cp.id == func.coalesce(jl.counterparty_id, t.counterparty_id))
            .outerjoin(jld, and_(jld.line_id == jl.id, jld.dimension_type_id == channel_type))
            .outerjoin(dv, dv.id == jld.dimension_value_id)
            .where(*self._filters())
            .order_by(je.seq, jl.line_no)
            .execution_options(yield_per=2000)
        )
        for row in self.session.execute(stmt):
            yield Line(*row)  # type: ignore[call-arg]

    def entries(self) -> Iterator[list[Line]]:
        current: list[Line] = []
        for line in self.lines():
            if current and current[0].entry != line.entry:
                yield current
                current = []
            current.append(line)
        if current:
            yield current

    def ledger_seq(self) -> int:
        """Highest entry sequence in the export: same data, same file (exports are deterministic)."""
        return int(
            self.session.execute(
                select(func.coalesce(func.max(JournalEntry.seq), 0)).where(*self._filters())
            ).scalar_one()
        )

    def _decimal(self, minor: int, commodity: str) -> str:
        return format(from_minor(minor, self.scales[commodity]), "f")

    def row(self, line: Line) -> dict[str, Any]:
        def side(minor: int, commodity: str) -> tuple[str, str]:
            value = self._decimal(abs(minor), commodity)
            return (value, "") if minor > 0 else ("", value) if minor < 0 else ("", "")

        debit, credit = side(line.amount, line.commodity)
        base_debit, base_credit = side(line.base_amount, self.base)
        return {
            "entry": line.entry,
            "date": line.date.isoformat(),
            "kind": labels.ENUM_LABELS["entry_kind"].get(line.kind, line.kind),
            "transaction": line.transaction,
            "type": line.type,
            "description": line.entry_description if line.kind != "posting" else line.description,
            "line_no": line.line_no,
            "account_code": line.account_code,
            "account_name": line.account_name,
            "commodity": line.commodity,
            "debit": debit,
            "credit": credit,
            "base_debit": base_debit,
            "base_credit": base_credit,
            "fx_rate": format(line.fx_rate.normalize(), "f") if line.fx_rate is not None else "",
            "counterparty": line.counterparty or "",
            "channel": line.channel or "",
            "line_role": labels.ENUM_LABELS["line_role"].get(line.line_role, line.line_role),
            "quantity": f"{format(line.quantity.normalize(), 'f')} {line.quantity_unit}" if line.quantity else "",
            "memo": line.memo or "",
            "external_ref": line.external_ref or "",
            "recorded_at": line.recorded_at.astimezone(ZoneInfo(self.book.timezone)).isoformat(timespec="seconds"),
        }

    # ---------------------------------------------------------------- writers

    def write_csv(self, out: IO[bytes]) -> int:
        text = io.TextIOWrapper(out, encoding="utf-8-sig", newline="")
        writer = csv.writer(text)
        writer.writerow([title for _key, title in CSV_COLUMNS])
        count = 0
        for line in self.lines():
            row = self.row(line)
            writer.writerow([row[key] for key, _title in CSV_COLUMNS])
            count += 1
        text.flush()
        text.detach()
        return count

    def write_xlsx(self, out: IO[bytes]) -> int:
        from openpyxl import Workbook  # type: ignore[import-untyped]

        wb = Workbook(write_only=True)
        lines_ws = wb.create_sheet("分录")
        lines_ws.append([title for _key, title in CSV_COLUMNS])
        count = 0
        numeric = {"debit", "credit", "base_debit", "base_credit"}
        for line in self.lines():
            row = self.row(line)
            lines_ws.append([Decimal(row[k]) if k in numeric and row[k] else row[k] for k, _t in CSV_COLUMNS])
            count += 1
        accounts_ws = wb.create_sheet("科目")
        accounts_ws.append(["科目编码", "科目名称", "类别", "角色", "启用"])
        for acc in sorted(self.accounts.values(), key=lambda a: a.code):
            accounts_ws.append(
                [
                    acc.code,
                    acc.name,
                    labels.ENUM_LABELS["account_classification"].get(acc.classification, acc.classification),
                    acc.role or "",
                    "是" if acc.is_active else "否",
                ]
            )
        wb.save(out)
        return count

    def write_json(self, out: IO[bytes]) -> int:
        def emit(text: str) -> None:
            out.write(text.encode("utf-8"))

        header = {
            "book": {"id": self.book.id, "name": self.book.name, "base_commodity": self.base},
            "ledger_seq": self.ledger_seq(),
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "amounts": "decimal strings; base_* in the base commodity; debit positive, credit negative",
            "accounts": [
                {"code": a.code, "name": a.name, "classification": a.classification, "role": a.role}
                for a in sorted(self.accounts.values(), key=lambda a: a.code)
            ],
        }
        emit(json.dumps(header, ensure_ascii=False)[:-1] + ', "entries": [')
        count = 0
        for n, group in enumerate(self.entries()):
            first = group[0]
            entry = {
                "number": first.entry,
                "date": first.date.isoformat(),
                "kind": first.kind,
                "description": first.entry_description,
                "transaction": {
                    "number": first.transaction,
                    "type": first.type,
                    "external_ref": first.external_ref,
                    "tags": self.tag_names.get(first.transaction, []),
                },
                "lines": [
                    {
                        "line_no": li.line_no,
                        "account": li.account_code,
                        "commodity": li.commodity,
                        "amount": self._decimal(li.amount, li.commodity),
                        "base_amount": self._decimal(li.base_amount, self.base),
                        "fx_rate": format(li.fx_rate.normalize(), "f") if li.fx_rate is not None else None,
                        "counterparty": li.counterparty,
                        "channel": li.channel,
                        "role": li.line_role,
                        "quantity": format(li.quantity.normalize(), "f") if li.quantity is not None else None,
                        "quantity_unit": li.quantity_unit,
                        "memo": li.memo,
                    }
                    for li in group
                ],
            }
            emit(("," if n else "") + json.dumps(entry, ensure_ascii=False))
            count += len(group)
        emit("]}")
        return count

    # ---------------------------------------------------------------- beancount

    def bean_account(self, account_id: str, suffix: str | None = None) -> str:
        acc = self.accounts[account_id]
        parts = acc.code.split(".")
        components = []
        for depth in range(1, len(parts) + 1):
            code = ".".join(parts[:depth])
            node = self.by_code.get(code)
            name = _UNSAFE.sub("-", node.name).strip("-") if node else ""
            components.append(f"{parts[depth - 1]}-{name}" if name else parts[depth - 1])
        if suffix:
            components.append(suffix)
        return ":".join([ROOTS[acc.classification], *components])

    def _bean_posting(self, line: Line) -> tuple[str, str]:
        """(account, amount text) — base-only lines on balance sheet accounts go to a 汇率重估 sub-account."""
        if line.amount == 0:
            suffix = "汇率重估" if line.classification in ("asset", "liability") else None
            return self.bean_account(
                line.account_id, suffix
            ), f"{self._decimal(line.base_amount, self.base)} {self.base}"
        units = f"{self._decimal(line.amount, line.commodity)} {line.commodity}"
        if line.commodity == self.base:
            return self.bean_account(line.account_id), units
        price = self._decimal(abs(line.base_amount), self.base)
        if line.base_amount and (line.base_amount > 0) != (line.amount > 0):
            raise DomainError("INVALID_STATE", f"分录 {line.entry} 行 {line.line_no} 原币与本位币方向相反，无法导出。")
        return self.bean_account(line.account_id), f"{units} @@ {price} {self.base}"

    def write_beancount(self, out: IO[bytes]) -> int:
        def emit(text: str) -> None:
            out.write((text + "\n").encode("utf-8"))

        conds = self._filters()
        first_day = self.session.execute(select(func.min(JournalEntry.effective_date)).where(*conds)).scalar_one()
        used = self.session.execute(
            select(JournalLine.account_id, Account.classification, func.bool_or(JournalLine.amount == 0))
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .join(Account, Account.id == JournalLine.account_id)
            .where(*conds)
            .group_by(JournalLine.account_id, Account.classification)
        ).all()
        commodities = sorted(
            set(
                self.session.execute(
                    select(JournalLine.commodity)
                    .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                    .where(*conds)
                ).scalars()
            )
            | {self.base}
        )
        emit(f";; {self.book.name} · bookkeeper v2 导出 · 截至分录序号 {self.ledger_seq()}")
        emit(f";; 区间：{self.date_from or '开始'} 至 {self.date_to or '至今'}；外币行以 @@ 记录入账时冻结的本位币金额")
        emit(f'option "title" "{_bean_str(self.book.name)}"')
        emit(f'option "operating_currency" "{self.base}"')
        emit("")
        opened = first_day or self.date_from or datetime.now(ZoneInfo(self.book.timezone)).date()
        for code in commodities:
            emit(f"{opened.isoformat()} commodity {code}")
        names: set[str] = set()
        for account_id, classification, has_base_only in used:
            names.add(self.bean_account(account_id))
            if has_base_only and classification in ("asset", "liability"):
                names.add(self.bean_account(account_id, "汇率重估"))
        for name in sorted(names):
            emit(f"{opened.isoformat()} open {name}")
        count = 0
        for group in self.entries():
            first = group[0]
            narration = first.entry_description if first.kind != "posting" else first.description
            payee = next((li.counterparty for li in group if li.counterparty), None)
            head = (
                f'{first.date.isoformat()} * "{_bean_str(payee)}" "{_bean_str(narration)}"'
                if payee
                else (f'{first.date.isoformat()} * "{_bean_str(narration)}"')
            )
            emit("")
            emit(head)
            emit(f'  entry: "{first.entry}"')
            emit(f'  transaction: "{first.transaction}"')
            emit(f'  type: "{first.type}"')
            if first.kind != "posting":
                emit(f'  kind: "{first.kind}"')
            if first.external_ref:
                emit(f'  external-ref: "{_bean_str(first.external_ref)}"')
            if self.tag_names.get(first.transaction):  # beancount #tags cannot hold CJK, so metadata
                emit(f'  tags: "{_bean_str(", ".join(self.tag_names[first.transaction]))}"')
            for li in group:
                account, amount = self._bean_posting(li)
                emit(f"  {account}  {amount}")
                if li.line_role not in ("manual", "net", "gross", "cost", "pay"):
                    emit(f'    role: "{li.line_role}"')
                if li.quantity is not None:
                    emit(f'    quantity: "{format(li.quantity.normalize(), "f")} {li.quantity_unit}"')
                if li.memo:
                    emit(f'    memo: "{_bean_str(li.memo)}"')
                count += 1
        return count

    def write(self, fmt: str, out: IO[bytes]) -> int:
        return {
            "csv": self.write_csv,
            "xlsx": self.write_xlsx,
            "json": self.write_json,
            "beancount": self.write_beancount,
        }[fmt](out)


def _bean_str(value: str | None) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def filename(book: Book, fmt: str, date_from: date | None, date_to: date | None) -> str:
    span = f"{date_from or 'start'}_{date_to or 'now'}"
    return f"bookkeeper-{book.id}-{span}.{FORMATS[fmt][1]}"


def export_to(
    session: Session,
    ctx: RequestContext,
    fmt: str,
    out: IO[bytes],
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Write one export to ``out``; returns name, media type and line count."""
    ctx.require(Scope.LEDGER_READ)
    if fmt not in FORMATS:
        raise DomainError("VALIDATION_FAILED", f"不支持的导出格式 {fmt}；可用 {', '.join(FORMATS)}。")
    book = session.get(Book, ctx.require_book())
    assert book is not None
    lines = Exporter(session, book, date_from, date_to).write(fmt, out)
    return {"filename": filename(book, fmt, date_from, date_to), "media_type": FORMATS[fmt][0], "lines": lines}


def save(
    session: Session,
    ctx: RequestContext,
    store: ContentStore,
    fmt: str,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Export into the book's file store (for AI clients): returns the file and its download path."""
    store.root.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=store.root, prefix=".export-")
    try:
        with os.fdopen(fd, "wb") as fh:
            info = export_to(session, ctx, fmt, fh, date_from, date_to)
        with open(tmp_name, "rb") as fh:
            blob = store.put(fh, max_bytes=EXPORT_MAX_BYTES)
    finally:
        os.unlink(tmp_name)
    book_id = ctx.require_book()
    item = session.execute(
        select(StoredFile).where(StoredFile.book_id == book_id, StoredFile.sha256 == blob.sha256)
    ).scalar_one_or_none()
    if item is None:
        item = StoredFile(
            id=new_id("fil"),
            book_id=book_id,
            sha256=blob.sha256,
            size_bytes=blob.size_bytes,
            mime_type=info["media_type"],
            original_name=info["filename"],
            storage_key=blob.storage_key,
            uploaded_by=ctx.actor.user_id,
            token_id=ctx.actor.token_id,
        )
        session.add(item)
        session.flush()
        audit.record(session, ctx, "file.export", "file", item.id, after=files.file_view(item) | {"format": fmt})
    return info | {
        "file": files.file_view(item),
        "download": f"/api/v1/books/{book_id}/files/{item.id}/content",
    }


# ------------------------------------------------------------------ monthly archive


def archive_months(session: Session, book: Book, root: Path, today: date) -> list[str]:
    """Write ``<root>/<book>/<YYYY-MM>/ledger.beancount`` and ``journal.csv`` for every finished month
    whose entries changed since the last archive (tracked by the highest entry seq in a manifest)."""
    month_key = func.to_char(JournalEntry.effective_date, "YYYY-MM")
    first_of_month = today.replace(day=1)
    months = session.execute(
        select(month_key, func.max(JournalEntry.seq), func.count())
        .where(JournalEntry.book_id == book.id, JournalEntry.effective_date < first_of_month)
        .group_by(month_key)
    ).all()
    written = []
    for key, max_seq, entries in months:
        folder = root / book.id / key
        manifest = folder / "manifest.json"
        if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")).get("max_seq") == max_seq:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        start = date.fromisoformat(f"{key}-01")
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        exporter = Exporter(session, book, start, end)
        digests = {}
        for name, fmt in (("ledger.beancount", "beancount"), ("journal.csv", "csv")):
            tmp = folder / f".{name}.tmp"
            with tmp.open("wb") as fh:
                exporter.write(fmt, fh)
            tmp.replace(folder / name)
            digests[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        manifest.write_text(
            json.dumps(
                {
                    "book": book.id,
                    "month": key,
                    "max_seq": max_seq,
                    "entries": entries,
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "sha256": digests,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        written.append(key)
    return written
