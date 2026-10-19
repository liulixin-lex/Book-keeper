"""Migrate the v1 ledger (SQLite) into a v2 book (docs/11).

v1 is only a data source: every business record is re-entered through the v2 services (business
types, posting checks, audit, hash chain) with its actual amounts; nothing is copied into the ledger
tables directly. Everything runs in one transaction — ``dry_run`` rolls back after producing the
report, so the report of a dry run is exactly what a real run would do.
"""

from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Account,
    AccountBalance,
    Book,
    BookMember,
    Counterparty,
    ImportBatch,
    JournalEntry,
    JournalLine,
    LegacyArchive,
    LegacyMap,
    SourceRecord,
    Transaction,
    TransactionSource,
    TransactionType,
    User,
)
from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.ids import new_id
from bookkeeper.domain.scopes import Role, Scope
from bookkeeper.files.storage import ContentStore
from bookkeeper.services import books, checks, files, imports, reference, transactions
from bookkeeper.services.context import Actor, RequestContext

E8 = Decimal(100_000_000)
TZ = ZoneInfo("Asia/Shanghai")
INCOME_CHANNEL = {"链动收入": "liandong", "云猫收入": "yunmao", "Stripe收入": "stripe", "xorpay收入": "xorpay"}
MARKETPLACE_CHANNEL = {"链动小铺": "liandong", "云猫寄售": "yunmao", "16888": "k16888"}
# Platform names v1 used for its channels. An owner's own renames (a vendor's legal name → its brand, a site's
# nickname as an alias) come from a local mappings file (``--mappings``), kept out of the code.
RENAMES: dict[str, tuple[str, str, list[str]]] = {
    "链动小铺": ("链动", "marketplace", []),
    "云猫寄售": ("云猫", "marketplace", []),
    "16888": ("16888", "marketplace", []),
    "xorpay（第三方收款）": ("XorPay", "payment_provider", []),
    "未知站点": ("未识别站点", "upstream_site", []),
}
VENDORS = {
    "OpenAI": "ai_vendor",
    "Anthropic": "ai_vendor",
    "Apple": "ai_vendor",
    "腾讯云": "cloud_vendor",
    "阿里云": "cloud_vendor",
    "OVH": "cloud_vendor",
    "Vultr": "cloud_vendor",
    "DogYun": "cloud_vendor",
    "Webshare": "cloud_vendor",
    "Wallester": "payment_provider",
}
ROLE_MAP = {"admin": Role.OWNER, "owner": Role.OWNER, "bookkeeper": Role.ACCOUNTANT, "accountant": Role.ACCOUNTANT}
EVIDENCE_LINE = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*\$?\s*([\d.]+)\s*(.*)$")
ORDER_NO = re.compile(r"(CAT|LD|USR|PAY-?)[0-9A-Za-z]{6,}")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class Report:
    dry_run: bool
    source: str
    book_id: str | None = None
    counts: Counter[str] = field(default_factory=Counter)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    rounding: list[dict[str, Any]] = field(default_factory=list)
    reclassification: Counter[str] = field(default_factory=Counter)
    counterparties: list[dict[str, Any]] = field(default_factory=list)
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "source": self.source,
            "book_id": self.book_id,
            "counts": dict(self.counts),
            "anomalies": self.anomalies,
            "rounding": self.rounding,
            "rounding_total": str(sum((Decimal(r["difference"]) for r in self.rounding), Decimal(0))),
            "rounding_abs_total": str(sum((abs(Decimal(r["difference"])) for r in self.rounding), Decimal(0))),
            "reclassification": dict(self.reclassification),
            "counterparties": self.counterparties,
            "checks": self.checks,
            "samples": self.samples,
            "warnings": self.warnings,
        }


@dataclass
class LegacyRecord:
    id: str
    record_type: str
    accounting_date: date
    occurred_at: datetime | None
    date_precision: str
    category: str
    counterparty: str | None
    source_channel: str | None
    external_id: str | None
    description: str
    note: str | None
    metadata: dict[str, Any]
    created_by: str | None
    reversed_by: str | None
    components: dict[str, dict[str, tuple[Decimal, Decimal]]]  # role → currency → (amount, amount_cny)
    source_document_id: str | None = None


# ------------------------------------------------------------------ reading v1


def read_legacy(path: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    def rows(sql: str) -> list[dict[str, Any]]:
        return [dict(r) for r in con.execute(sql)]

    components: dict[str, dict[str, dict[str, tuple[Decimal, Decimal]]]] = defaultdict(lambda: defaultdict(dict))
    for c in rows("select record_id, role, currency, amount_e8, amount_cny_e8 from money_components"):
        amount, cny = Decimal(c["amount_e8"]) / E8, Decimal(c["amount_cny_e8"] or 0) / E8
        prev = components[c["record_id"]][c["role"]].get(c["currency"], (Decimal(0), Decimal(0)))
        components[c["record_id"]][c["role"]][c["currency"]] = (prev[0] + amount, prev[1] + cny)
    records = []
    for r in rows(
        "select br.*, c.name as category_name, cp.name as counterparty_name from business_records br "
        "left join categories c on c.id = br.category_id left join counterparties cp on cp.id = br.counterparty_id "
        "order by br.accounting_date, br.occurred_at, br.created_at"
    ):
        occurred = datetime.fromisoformat(r["occurred_at"]).replace(tzinfo=UTC) if r["occurred_at"] else None
        records.append(
            LegacyRecord(
                id=r["id"],
                record_type=r["record_type"],
                accounting_date=date.fromisoformat(r["accounting_date"]),
                occurred_at=occurred,
                date_precision=r["date_precision"] or "day",
                category=r["category_name"] or "",
                counterparty=r["counterparty_name"],
                source_channel=r["source_channel"],
                external_id=r["external_id"],
                description=(r["description"] or "").strip(),
                note=r["note"],
                metadata=json.loads(r["metadata_json"] or "{}"),
                created_by=r["created_by_user_id"],
                reversed_by=r["reversed_by_record_id"],
                components={k: dict(v) for k, v in components[r["id"]].items()},
                source_document_id=r["source_document_id"],
            )
        )
    data = {
        "workspace": rows("select * from workspaces")[0],
        "users": rows("select * from users where deleted_at is null"),
        "counterparties": rows("select * from counterparties"),
        "fx_rates": rows("select * from fx_rates"),
        "records": records,
        "source_documents": rows("select * from source_documents"),
        "journal_entries": rows("select * from journal_entries"),
        "journal_lines": rows(
            "select jl.*, a.code as account_code from journal_lines jl join accounts a on a.id = jl.account_id"
        ),
        "audit_events": rows("select * from audit_events"),
        "accounts": rows("select * from accounts"),
        "categories": rows("select * from categories"),
    }
    con.close()
    return data


# ------------------------------------------------------------------ mapping


@dataclass(frozen=True)
class Names:
    """How v1 counterparty names become v2 ones (docs/14 §7.2, §11.2): the renames above plus an owner's own,
    and other names a site goes by. Load an owner's file with ``Names.load``:
    ``{"renames": {"v1 name": ["new name", "category", ["alias", …]]}, "site_aliases": {"host": ["alias", …]}}``."""

    renames: Mapping[str, tuple[str, str, list[str]]] = field(default_factory=lambda: dict(RENAMES))
    site_aliases: Mapping[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> Names:
        if path is None:
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        own = {
            k: (str(v[0]), str(v[1]), [str(a) for a in (v[2] if len(v) > 2 else [])])
            for k, v in data.get("renames", {}).items()
        }
        aliases = {str(k).lower(): [str(a) for a in v] for k, v in data.get("site_aliases", {}).items()}
        return cls(renames={**RENAMES, **own}, site_aliases=aliases)


def counterparty_name(name: str, names: Names | None = None) -> tuple[str, str, list[str]]:
    """New name, category and aliases for a v1 counterparty (docs/14 §7.2, §11.2)."""
    names = names or Names()
    if name in names.renames:
        new, category, aliases = names.renames[name]
        return new, category, [*aliases, name] if new != name else aliases
    if name in VENDORS:
        return name, VENDORS[name], []
    if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", name.lower()):
        host = name.lower()  # the site is the host itself: api.relay-a.example, never relay-a.example
        return host, "upstream_site", list(names.site_aliases.get(host, []))
    return name, "upstream_site" if name.isascii() else "other", []


def clean_title(text: str) -> str:
    """Product keyword (docs/14 §9.3): drop bracketed parts and symbols, collapse spaces, first 20 chars."""
    text = re.sub(r"【[^】]*】|\[[^\]]*\]|（[^）]*）|\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\s.+\-:/一-鿿]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -/…")
    return text[:20].strip()


def evidence_items(rec: LegacyRecord) -> list[dict[str, Any]]:
    """Lists kept in v1 metadata (redemption lines, orders…) → evidence records."""
    items: list[dict[str, Any]] = []
    md = rec.metadata
    for line in md.get("lines") or []:
        m = EVIDENCE_LINE.match(str(line))
        if m:
            order = ORDER_NO.search(m.group(3))
            items.append(
                {
                    "time": m.group(1),
                    "amount": m.group(2),
                    "commodity": "UCR",
                    "direction": "in",
                    "order_no": order.group(0) if order else None,
                    "note": m.group(3).strip(),
                    "raw": line,
                }
            )
        else:
            items.append({"raw": line, "unparsed": True})
    for entry in md.get("redeem_entries") or []:
        items.append(
            {
                "time": entry[0],
                "amount": str(entry[1]),
                "commodity": "UCR",
                "direction": "in",
                "quantity": entry[2] if len(entry) > 2 else None,
                "raw": entry,
            }
        )
    for key in ("wechat_orders", "orders"):
        for entry in md.get(key) or []:
            items.append(
                {
                    "time": entry[0],
                    "amount": str(entry[1]),
                    "commodity": "CNY",
                    "direction": "out",
                    "order_no": entry[2] if len(entry) > 2 else None,
                    "list": key,
                    "raw": entry,
                }
            )
    return items


@dataclass
class Plan:
    """A v1 record turned into a v2 transaction request."""

    record: LegacyRecord
    data: dict[str, Any]
    category_label: str
    rounding: list[dict[str, Any]]


def _q(value: Decimal, scale: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)


def plan_record(rec: LegacyRecord, scales: dict[str, int], cp_names: dict[str, str], policy: str) -> Plan:
    """Raise DomainError (→ anomaly) when the record cannot be represented faithfully."""
    rounding: list[dict[str, Any]] = []

    def amount(role: str, currency: str | None = None) -> tuple[str, Decimal, Decimal] | None:
        found = rec.components.get(role) or {}
        if not found:
            return None
        if currency is None:
            if len(found) > 1:
                raise DomainError("INPUT_INVALID", f"{role} 含多个币种 {sorted(found)}")
            currency = next(iter(found))
        if currency not in found:
            return None
        value, cny = found[currency]
        code = "UCR" if currency == "UPSTREAM_CREDIT" else currency
        if code not in scales:
            raise DomainError("INPUT_INVALID", f"未知币种 {currency}")
        rounded = _q(value, scales[code])
        if rounded != value:
            if policy != "round":
                raise DomainError("INPUT_INVALID", f"{role} {value} {code} 超出币种精度")
            rounding.append(
                {
                    "record": rec.id,
                    "role": role,
                    "commodity": code,
                    "original": str(value),
                    "rounded": str(rounded),
                    "difference": str(rounded - value),
                }
            )
        return code, rounded, cny

    def money(value: Decimal, code: str) -> dict[str, str]:
        return {"amount": format(value, "f"), "commodity": code}

    party = cp_names.get(rec.counterparty or "", rec.counterparty)
    md = rec.metadata
    evidence_text = " ".join(str(x) for x in (rec.note, rec.description, json.dumps(md, ensure_ascii=False)))
    data: dict[str, Any] = {
        "effective_date": rec.accounting_date,
        "occurred_at": rec.occurred_at,
        "date_precision": rec.date_precision if rec.date_precision in ("timestamp", "day", "month") else "day",
        "notes": rec.note,
        "external_ref": rec.external_id,
        "metadata": {
            "legacy": {
                "id": rec.id,
                "description": rec.description,
                "category": rec.category,
                "counterparty": rec.counterparty,
                "source_channel": rec.source_channel,
                "source_document_id": rec.source_document_id,
                "metadata": md,
            }
        },
    }
    if rec.external_id and not HEX64.match(rec.external_id) and len(rec.external_id) <= 40:
        data["order_no"] = rec.external_id
    if rec.record_type == "income":
        channel = INCOME_CHANNEL.get(rec.category)
        if channel is None:
            raise DomainError("INPUT_INVALID", f"收入分类 {rec.category} 未定义映射")
        gross = amount("gross")
        if gross is None:
            raise DomainError("INPUT_INVALID", "收入缺少毛额")
        code, gross_v, gross_cny = gross
        fee = amount("fee", code)
        fee_v = fee[1] if fee else Decimal(0)
        inputs: dict[str, Any] = {"gross": money(gross_v, code), "fee": money(fee_v, code), "channel": channel}
        net = amount("net")
        if net and net[0] == code and net[1] != gross_v - fee_v:
            rounding.append(
                {
                    "record": rec.id,
                    "role": "net",
                    "commodity": code,
                    "original": str(net[1]),
                    "rounded": str(gross_v - fee_v),
                    "difference": str(gross_v - fee_v - net[1]),
                }
            )
        if code != "CNY":
            if not gross_cny:
                raise DomainError("INPUT_INVALID", "外币收入缺少本位币金额")
            inputs["fx_rate"] = format((gross_cny / gross_v).quantize(Decimal("1e-12")), "f")
        data |= {"type": "sale", "inputs": inputs}
        if party and rec.category != "xorpay收入":
            data["counterparty"] = party
        return Plan(rec, data, f"{rec.category} → sale 5001.01（{channel}）", rounding)
    cost = amount("cost")
    cash = amount("cash")
    if cost is None or cash is None:
        raise DomainError("INPUT_INVALID", "支出缺少成本或现金分量")
    code, cost_v, cost_cny = cost
    cash_code, cash_v, _cash_cny = cash
    if cash_code != code:
        raise DomainError("INPUT_INVALID", f"成本币种 {code} 与现金币种 {cash_code} 不同")
    fee_found = amount("fee", code)
    fee_v = cash_v - cost_v
    if fee_found and fee_found[1] != fee_v:
        if policy == "round" and abs(fee_found[1] - fee_v) <= Decimal("0.01"):
            rounding.append(
                {
                    "record": rec.id,
                    "role": "fee",
                    "commodity": code,
                    "original": str(fee_found[1]),
                    "rounded": str(fee_v),
                    "difference": str(fee_v - fee_found[1]),
                }
            )
        else:
            raise DomainError("INPUT_INVALID", f"现金 {cash_v} ≠ 成本 {cost_v} + 手续费 {fee_found[1]}")
    if fee_v < 0:
        raise DomainError("INPUT_INVALID", f"现金 {cash_v} 小于成本 {cost_v}")
    fx = {"fx_rate": format((cost_cny / cost_v).quantize(Decimal("1e-12")), "f")} if code != "CNY" and cost_v else {}
    if rec.category == "上游充值":
        channel = (
            "liandong"
            if ("链动" in evidence_text or re.search(r"\bLD2\d", evidence_text))
            else "yunmao"
            if ("云猫" in evidence_text or "CAT2" in evidence_text)
            else "site_shop"
            if ("PAY-" in evidence_text or "站内" in evidence_text)
            else "other"
        )
        inputs = {"face": money(cost_v, code), "total": money(cash_v, code), "channel": channel} | fx
        credits = amount("credited_value")
        if credits:
            inputs["credit_quantity"] = format(credits[1], "f")
        data |= {"type": "credit_purchase", "inputs": inputs, "counterparty": party or "未识别站点"}
        items = [i for i in evidence_items(rec) if not i.get("unparsed")]
        if len(items) > 1:
            data["description"] = f"{party} · 额度采购 · {rec.accounting_date.isoformat()} 合计 {len(items)} 笔"
        return Plan(rec, data, f"上游充值 → credit_purchase 5401.01（{channel}）", rounding)
    text = f"{rec.description} {rec.counterparty or ''}"
    if rec.category == "账号购买":
        category, label = "5401.02", "账号"
        channel = MARKETPLACE_CHANNEL.get(rec.counterparty or "", "other")
    elif rec.category == "订阅":
        category, label, channel = (
            ("5603.01", "手续费", "direct") if "手续费" in rec.description else ("5401.03", "AI 服务订阅", "direct")
        )
    elif rec.category == "云服务":
        category, label, channel = "5401.04", "服务器与网络", "direct"
    elif rec.category == "其他支出":
        if "广告" in text:  # the text includes v1's counterparty, e.g. "某广告商（广告）"
            category, label = "5601.01", "广告推广"
        elif "注册" in text:
            category, label = "5602.01", "注册与办公费"
        elif "开户" in text or "xorpay" in text.lower():
            category, label = "5603.01", "手续费"
        else:
            category, label = "5602.99", "其他管理费用"
        channel = "direct"
    else:
        raise DomainError("INPUT_INVALID", f"支出分类 {rec.category} 未定义映射")
    inputs = {"amount": money(cost_v, code), "category": category, "channel": channel} | fx
    if fee_v:
        inputs["fee"] = money(fee_v, code)
    data |= {"type": "expense", "inputs": inputs}
    if party:
        data["counterparty"] = party
    keyword = clean_title(rec.description.replace(rec.counterparty or "", ""))
    if keyword and keyword not in (rec.category, label) and not keyword.startswith("上游充值"):
        data["description"] = f"{party or '未识别往来方'} · {label} · {keyword}"[:60]
    elif party:
        data["description"] = f"{party} · {label}"
    return Plan(rec, data, f"{rec.category} → expense {category}（{label}）", rounding)


# ------------------------------------------------------------------ migration


def _actor(user_id: str | None) -> Actor:
    return Actor(type="migration", user_id=user_id, role=Role.OWNER, scopes=frozenset(Scope), is_superadmin=True)


def migrate(
    session: Session,
    source: Path,
    *,
    book_id: str | None = None,
    book_name: str | None = None,
    owner_email: str | None = None,
    dry_run: bool = True,
    subcent_policy: str = "round",
    sample_size: int = 30,
    files_dir: Path | None = None,
    store: ContentStore | None = None,
    names: Names | None = None,
) -> Report:
    """Run inside one transaction; the caller commits unless ``dry_run`` (then it rolls back)."""
    legacy = read_legacy(source)
    report = Report(dry_run=dry_run, source=str(source))
    system = RequestContext(actor=_actor(None), channel="migration")
    users = _migrate_users(session, system, legacy["users"], report)
    owner_id = _owner(session, users, legacy["users"], owner_email)
    if book_id:
        book = books.get_book(session, book_id)
        if session.execute(
            select(func.count()).select_from(Transaction).where(Transaction.book_id == book.id)
        ).scalar_one():
            raise DomainError("INVALID_STATE", f"目标账套 {book.id} 已有交易；迁移只能写入空账套。")
    else:
        ctx0 = RequestContext(actor=_actor(owner_id), channel="migration")
        book = books.create_book(
            session, ctx0, name=book_name or legacy["workspace"]["name"] or "主账套", owner_user_id=owner_id
        )
    report.book_id = book.id
    ctx = RequestContext(actor=_actor(owner_id), channel="migration", book_id=book.id)
    for legacy_user in legacy["users"]:
        user_id = users.get(legacy_user["id"])
        if user_id and user_id != owner_id:
            role = ROLE_MAP.get(legacy_user["role"], Role.VIEWER)
            if session.get(BookMember, (book.id, user_id)) is None:
                session.add(BookMember(book_id=book.id, user_id=user_id, role=role.value))
        if user_id:
            _map(session, book.id, "users", legacy_user["id"], "user", user_id)
    session.flush()
    reference.create_price_rule(
        session,
        ctx,
        commodity="UCR",
        quote_commodity="CNY",
        rate="1",
        purpose="nominal_valuation",
        valid_from=date(2026, 5, 1),
        note="迁移：1 CNY = 1 上游额度",
    )
    known = set(reference.commodity_scales(session))
    for rate in legacy["fx_rates"]:
        if rate["base_currency"] not in known or rate["quote_currency"] not in known:
            report.counts["fx_rates_skipped"] += 1
            continue
        rate_type = "reference" if rate["rate_type"] == "daily_reference" else "derived"
        reference.upsert_fx_rate(
            session,
            base=rate["base_currency"],
            quote=rate["quote_currency"],
            rate_date=datetime.fromisoformat(rate["effective_at"]).date(),
            rate=Decimal(rate["rate_e12"]) / Decimal(10**12),
            rate_type=rate_type,
            source=f"legacy:{rate['source']}"[:60],
        )
        report.counts["fx_rates"] += 1
    cp_names = _migrate_counterparties(session, ctx, legacy["counterparties"], report, names or Names())
    scales = reference.commodity_scales(session)
    evidence = _evidence_batch(session, ctx, book)
    posted: dict[str, str] = {}
    occurrences: Counter[str] = Counter()
    for rec in legacy["records"]:
        try:
            plan = plan_record(rec, scales, cp_names, subcent_policy)
        except DomainError as exc:
            report.anomalies.append(_anomaly(rec, exc.detail))
            continue
        actor_ctx = RequestContext(
            actor=_actor(users.get(rec.created_by or "") or owner_id), channel="migration", book_id=book.id
        )
        savepoint = session.begin_nested()
        try:
            txn, _entry, _p = transactions.create(session, actor_ctx, {**plan.data})
            savepoint.commit()
        except DomainError as exc:
            savepoint.rollback()
            report.anomalies.append(_anomaly(rec, f"{exc.code}: {exc.detail}"))
            continue
        posted[rec.id] = txn.id
        report.rounding.extend(plan.rounding)
        report.reclassification[plan.category_label] += 1
        report.counts[f"type:{plan.data['type']}"] += 1
        _map(session, book.id, "business_records", rec.id, "transaction", txn.id)
        report.counts["evidence_items"] += _attach_evidence(session, book, evidence, rec, txn, occurrences, report)
    for rec in legacy["records"]:
        if rec.reversed_by and rec.id in posted:
            transactions.delete(session, ctx, posted[rec.id], "旧系统已冲正")
            report.counts["reversed"] += 1
    _attach_source_files(session, ctx, legacy, posted, files_dir, store, report)
    _archive(session, book.id, legacy)
    report.counts["records"] = len(legacy["records"])
    report.counts["migrated"] = len(posted)
    session.flush()
    run_checks(session, ctx, legacy, report, posted, sample_size)
    _funds_note(session, book.id, report)
    return report


def _anomaly(rec: LegacyRecord, reason: str) -> dict[str, Any]:
    return {
        "record": rec.id,
        "date": rec.accounting_date.isoformat(),
        "category": rec.category,
        "counterparty": rec.counterparty,
        "description": rec.description[:60],
        "reason": reason,
    }


def _map(session: Session, book_id: str, table: str, legacy_id: str, entity_type: str, entity_id: str) -> None:
    session.merge(
        LegacyMap(
            book_id=book_id, legacy_table=table, legacy_id=legacy_id, entity_type=entity_type, entity_id=entity_id
        )
    )


def _migrate_users(session: Session, ctx: RequestContext, rows: list[dict[str, Any]], report: Report) -> dict[str, str]:
    """Same e-mail → same user; argon2id hashes are kept (v2 verifies them), others must reset."""
    mapping: dict[str, str] = {}
    for row in rows:
        email = (row["email"] or "").strip().lower()
        if not email:
            continue
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            hash_ok = str(row["password_hash"] or "").startswith("$argon2id$")
            user = User(
                id=new_id("usr"),
                email=email,
                display_name=row["display_name"] or row["username"] or email,
                password_hash=row["password_hash"] if hash_ok else "!reset-required",
                is_active=bool(row["is_active"]),
            )
            session.add(user)
            session.flush()
            report.counts["users_created"] += 1
            if not hash_ok:
                report.warnings.append(f"用户 {email} 的密码哈希不是 argon2id，需重置密码")
        mapping[row["id"]] = user.id
    return mapping


def _owner(session: Session, users: dict[str, str], rows: list[dict[str, Any]], email: str | None) -> str:
    if email:
        user = session.execute(select(User).where(User.email == email.strip().lower())).scalar_one_or_none()
        if user is None:
            raise DomainError("NOT_FOUND", f"所有者 {email} 不存在。")
        return user.id
    admins = [r for r in rows if r["role"] == "admin" and r["id"] in users]
    if not admins:
        raise DomainError("VALIDATION_FAILED", "旧系统没有管理员用户，请用 --owner-email 指定所有者。")
    return users[admins[0]["id"]]


def _migrate_counterparties(
    session: Session, ctx: RequestContext, rows: list[dict[str, Any]], report: Report, naming: Names
) -> dict[str, str]:
    names: dict[str, str] = {}
    created: dict[str, Counterparty] = {}
    for row in sorted(rows, key=lambda r: r["name"]):
        new, category, aliases = counterparty_name(row["name"], naming)
        names[row["name"]] = new
        cp = created.get(new)
        if cp is None:
            domains = [new] if category == "upstream_site" and "." in new else []
            cp = reference.create_counterparty(
                session,
                ctx,
                name=new,
                category=category,
                roles=["supplier"],
                domains=domains,
                aliases=[a for a in aliases if a != new],
            )
            created[new] = cp
            report.counts["counterparties"] += 1
        _map(session, ctx.require_book(), "counterparties", row["id"], "counterparty", cp.id)
        report.counterparties.append({"legacy": row["name"], "new": new, "category": category, "aliases": aliases})
    return names


def _evidence_batch(session: Session, ctx: RequestContext, book: Book) -> ImportBatch:
    src = imports.create_source(
        session,
        ctx,
        {
            "code": "legacy_evidence",
            "name": "历史证据（迁移）",
            "kind": "records",
            "config": {"note": "v1 元数据中的兑换明细、订单列表"},
        },
    )
    batch = ImportBatch(
        id=new_id("imb"),
        book_id=book.id,
        source_id=src.id,
        parser="legacy_v1",
        parser_version="1.0.0",
        status="committed",
        summary={"note": "v1 迁移"},
        committed_at=datetime.now(UTC),
        created_by=ctx.actor.user_id,
    )
    session.add(batch)
    session.flush()
    return batch


def _attach_evidence(
    session: Session,
    book: Book,
    batch: ImportBatch,
    rec: LegacyRecord,
    txn: Transaction,
    occurrences: Counter[str],
    report: Report,
) -> int:
    count = 0
    scales = reference.commodity_scales(session)
    for n, item in enumerate(evidence_items(rec), start=1):
        if item.get("unparsed"):
            report.counts["evidence_unparsed"] += 1
            continue
        try:
            hh, mm, *ss = (int(x) for x in str(item["time"]).split(":"))
            local = datetime.combine(rec.accounting_date, time(hh, mm, ss[0] if ss else 0), TZ)
            amount = Decimal(str(item["amount"]))
            minor = int(_q(amount, scales[item["commodity"]]).scaleb(scales[item["commodity"]]))
        except ValueError, KeyError, ArithmeticError:
            report.counts["evidence_unparsed"] += 1
            continue
        row = SourceRecord(
            id=new_id("srec"),
            book_id=book.id,
            source_id=batch.source_id,
            batch_id=batch.id,
            row_no=n,
            external_id=None,
            fingerprint="",
            occurred_at=local,
            effective_date=rec.accounting_date,
            direction=item["direction"],
            amount_minor=minor,
            commodity=item["commodity"],
            counterparty_text=rec.counterparty,
            description=item.get("note") or item.get("list"),
            order_no=item.get("order_no"),
            extracted={k: v for k, v in item.items() if k in ("quantity", "list", "note")},
            raw={"legacy_record": rec.id, "value": item["raw"]},
            status="booked",
            transaction_id=txn.id,
        )
        base = imports.fingerprint(batch.source_id, row, 0)
        occurrences[base] += 1
        row.fingerprint = imports.fingerprint(batch.source_id, row, occurrences[base])
        session.add(row)
        session.flush()
        session.add(TransactionSource(transaction_id=txn.id, source_record_id=row.id, role="evidence"))
        count += 1
    return count


def _attach_source_files(
    session: Session,
    ctx: RequestContext,
    legacy: dict[str, Any],
    posted: dict[str, str],
    files_dir: Path | None,
    store: ContentStore | None,
    report: Report,
) -> None:
    """v1 kept only the uploader's local path; originals supplied via ``files_dir`` are verified and attached."""
    report.counts["source_files"] = len(legacy["source_documents"])
    if files_dir is None:
        return
    linked: dict[str, list[str]] = defaultdict(list)
    for rec in legacy["records"]:
        if rec.source_document_id and rec.id in posted:
            linked[rec.source_document_id].append(posted[rec.id])
    for doc in legacy["source_documents"]:
        path = files_dir / Path(str(doc["filename"])).name
        if not path.is_file():
            continue
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != doc["sha256"]:
            report.warnings.append(f"原始文件 {doc['filename']} 的 SHA-256 与旧库记录不一致，未附加")
            continue
        report.counts["source_files_matched"] += 1
        report.counts["source_file_links"] += len(linked[doc["id"]])
        if store is None:  # dry run: verify only, write nothing to the file store
            continue
        mime = doc["mime_type"] or mimetypes.guess_type(path.name)[0]
        stored, _created = files.upload(
            session, ctx, store, io.BytesIO(content), filename=path.name, mime_type=mime, max_bytes=len(content) + 1
        )
        for txn_id in linked[doc["id"]]:
            files.attach(
                session,
                ctx,
                file_id=stored.id,
                entity_type="transaction",
                entity_id=txn_id,
                role="statement",
                note="v1 来源文件",
            )


def _funds_note(session: Session, book_id: str, report: Report) -> None:
    """Funds balance per currency; a negative one usually means conversions (Stripe payouts) were never recorded."""
    scales = reference.commodity_scales(session)
    rows = session.execute(
        select(AccountBalance.commodity, func.sum(AccountBalance.balance))
        .join(Account, Account.id == AccountBalance.account_id)
        .where(AccountBalance.book_id == book_id, Account.role == "funds")
        .group_by(AccountBalance.commodity)
        .order_by(AccountBalance.commodity)
    ).all()
    balances = {c: Decimal(int(v)).scaleb(-scales[c]) for c, v in rows if v}
    report.counts["funds_currencies"] = len(balances)
    negative = [c for c, v in balances.items() if v < 0]
    if negative:
        shown = "、".join(f"{c} {v:,}" for c, v in balances.items())
        report.warnings.append(
            f"资金账户按币种余额：{shown}。{'、'.join(negative)} 为负，通常是旧账没有记录结汇 / 换汇"
            "（如 Stripe 英镑到账后换成人民币）；上线后用 transfer 补记结汇即可，本位币合计不受影响。"
        )


def _archive(session: Session, book_id: str, legacy: dict[str, Any]) -> None:
    for table in ("journal_entries", "journal_lines", "audit_events", "source_documents", "accounts", "categories"):
        for row in legacy[table]:
            session.add(
                LegacyArchive(
                    book_id=book_id,
                    legacy_table=table,
                    legacy_id=str(row["id"]),
                    data=json.loads(json.dumps(row, default=str)),
                )
            )
    for rec in legacy["records"]:
        data = {
            **rec.__dict__,
            "components": {r: {c: [str(a), str(b)] for c, (a, b) in v.items()} for r, v in rec.components.items()},
        }
        session.add(
            LegacyArchive(
                book_id=book_id,
                legacy_table="business_records",
                legacy_id=rec.id,
                data=json.loads(json.dumps(data, default=str)),
            )
        )
    session.flush()


# ------------------------------------------------------------------ verification (docs/11 §4)


def run_checks(
    session: Session,
    ctx: RequestContext,
    legacy: dict[str, Any],
    report: Report,
    posted: dict[str, str],
    sample_size: int,
) -> None:
    book_id = ctx.require_book()
    records = {r.id: r for r in legacy["records"]}
    anomalies = {a["record"] for a in report.anomalies}
    report.checks["V1_records"] = _check(
        len(posted) + len(anomalies) == len(records) and not (set(posted) & anomalies),
        f"{len(records)} 条旧记录：迁移 {len(posted)}，未迁移 {len(anomalies)}",
    )
    txns = {t.id: t for t in session.execute(select(Transaction).where(Transaction.id.in_(posted.values()))).scalars()}
    types = dict(
        session.execute(
            select(TransactionType.id, TransactionType.code).where(TransactionType.book_id == book_id)
        ).all()
    )
    mismatches = []
    for legacy_id, txn_id in posted.items():
        rec, txn = records[legacy_id], txns[txn_id]
        expected = _legacy_components(rec)
        actual = _v2_components(txn, types[txn.transaction_type_id])
        if any(
            abs(expected.get(k, Decimal(0)) - actual.get(k, Decimal(0))) > Decimal("0.01")
            for k in set(expected) | set(actual)
        ):
            mismatches.append(
                {
                    "record": legacy_id,
                    "legacy": {k: str(v) for k, v in expected.items()},
                    "v2": {k: str(v) for k, v in actual.items()},
                }
            )
    report.checks["V2_components"] = _check(
        not mismatches, f"分量逐笔比对：{len(mismatches)} 笔不一致（容差 1 分，来自舍入清单）", mismatches[:20]
    )
    legacy_totals = _legacy_journal_totals(legacy)
    v2_totals = _v2_totals(session, book_id)
    rounding_total = sum((abs(Decimal(r["difference"])) for r in report.rounding), Decimal(0)) + Decimal("0.05")
    anomaly_cny = sum((_legacy_cash_cny(records[a]) for a in anomalies), Decimal(0))
    diffs = {k: str(v2_totals.get(k, Decimal(0)) - legacy_totals.get(k, Decimal(0))) for k in legacy_totals}
    v3_ok = all(abs(Decimal(d)) <= rounding_total + anomaly_cny for d in diffs.values())
    report.checks["V3_base_totals"] = _check(
        v3_ok,
        f"本位币合计差额（容差 = 舍入 {rounding_total} + 未迁移 {anomaly_cny}）",
        {
            "legacy": {k: str(v) for k, v in legacy_totals.items()},
            "v2": {k: str(v) for k, v in v2_totals.items()},
            "difference": diffs,
        },
    )
    run = checks.run_checks(
        session,
        ctx,
        ["trial_balance_zero", "hash_chain", "entries_balanced", "balances_cache", "daily_balances", "sequence_gaps"],
        trigger="post_migration",
    )
    report.checks["V4_integrity"] = _check(run.status == "passed", f"账本完整性检查：{run.status}")
    legacy_credits = Decimal(0)
    for rec in legacy["records"]:
        if rec.id in posted:
            for _cur, (value, _cny) in (rec.components.get("credited_value") or {}).items():
                legacy_credits += value
    v2_credits = session.execute(
        select(func.coalesce(func.sum(JournalLine.quantity), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(JournalEntry.book_id == book_id, JournalLine.quantity.is_not(None))
    ).scalar_one()
    report.checks["V5_credits"] = _check(
        legacy_credits == Decimal(str(v2_credits or 0)),
        f"额度数量：旧 {legacy_credits}，新 {v2_credits}",
    )
    list_items = sum(len(evidence_items(r)) for r in legacy["records"] if r.id in posted)
    expanded = report.counts["evidence_items"] + report.counts["evidence_unparsed"]
    matched = report.counts["source_files_matched"]
    missing_files = len(legacy["source_documents"]) - matched
    report.checks["V6_evidence"] = _check(
        list_items == expanded,
        f"明细列表 {list_items} 项：展开 {report.counts['evidence_items']}，"
        f"保留原文 {report.counts['evidence_unparsed']}；"
        f"原始文件 {len(legacy['source_documents'])} 个：已核验 {matched}"
        f"（关联 {report.counts['source_file_links']} 笔），"
        f"未提供 {missing_files}（文件名与哈希已存档）",
    )
    wrong_dates = [lid for lid, tid in posted.items() if txns[tid].effective_date != records[lid].accounting_date]
    report.checks["V7_dates"] = _check(not wrong_dates, f"业务日期不一致 {len(wrong_dates)} 笔", wrong_dates[:20])
    refs = [r.external_id for r in legacy["records"] if r.external_id and r.id in posted]
    kept = sum(
        1
        for lid, tid in posted.items()
        if records[lid].external_id and txns[tid].external_ref == records[lid].external_id
    )
    report.checks["V8_external_refs"] = _check(
        kept == len(refs) == len(set(refs)), f"外部引用 {len(refs)} 个，保留 {kept} 个"
    )
    picked = sorted(posted, key=lambda k: hashlib.sha256(k.encode()).hexdigest())[:sample_size]  # stable sample
    for legacy_id in picked:
        rec, txn = records[legacy_id], txns[posted[legacy_id]]
        report.samples.append(
            {
                "legacy": {
                    "date": rec.accounting_date.isoformat(),
                    "category": rec.category,
                    "counterparty": rec.counterparty,
                    "description": rec.description[:60],
                    "components": {k: {c: str(v[0]) for c, v in d.items()} for k, d in rec.components.items()},
                },
                "v2": {
                    "number": txn.number,
                    "type": types[txn.transaction_type_id],
                    "description": txn.description,
                    "computed": {
                        k: txn.computed.get(k) for k in ("gross", "fee", "net", "face", "total", "amount", "commodity")
                    },
                },
            }
        )
    report.checks["V9_samples"] = _check(True, f"随机抽样 {len(report.samples)} 笔，见 samples")
    legacy_month = _legacy_monthly(legacy)
    v2_month = _v2_monthly(session, book_id)
    month_diffs = {
        m: {
            k: str(v2_month.get(m, {}).get(k, Decimal(0)) - legacy_month[m].get(k, Decimal(0))) for k in legacy_month[m]
        }
        for m in sorted(legacy_month)
    }
    worst = max((abs(Decimal(v)) for d in month_diffs.values() for v in d.values()), default=Decimal(0))
    report.checks["V10_monthly"] = _check(
        worst <= rounding_total + anomaly_cny, f"按月收入 / 成本费用 / 手续费最大差额 {worst}", month_diffs
    )


def _check(ok: bool, message: str, details: Any = None) -> dict[str, Any]:
    return {"ok": ok, "message": message, "details": details}


def _legacy_components(rec: LegacyRecord) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for role, by_currency in rec.components.items():
        for currency, (value, _cny) in by_currency.items():
            if currency != "UPSTREAM_CREDIT":
                out[role] = out.get(role, Decimal(0)) + _q(value, 2)
    if rec.record_type == "expense" and "fee" not in out and "cash" in out and "cost" in out:
        out["fee"] = out["cash"] - out["cost"]
    if rec.record_type == "income":
        out.pop("cash", None)
        out.setdefault("fee", Decimal(0))
        out["net"] = out.get("gross", Decimal(0)) - out["fee"]
    return out


def _v2_components(txn: Transaction, type_code: str) -> dict[str, Decimal]:
    c = txn.computed
    scale = Decimal(100)

    def d(key: str) -> Decimal:
        return Decimal(int(c.get(key) or 0)) / scale

    if type_code == "sale":
        return {"gross": d("gross"), "fee": d("fee"), "net": d("net")}
    if type_code == "credit_purchase":
        return {"cost": d("face"), "fee": d("fee"), "cash": d("total")}
    return {"cost": d("amount"), "fee": d("fee"), "cash": d("total")}


def _legacy_cash_cny(rec: LegacyRecord) -> Decimal:
    role = "gross" if rec.record_type == "income" else "cash"
    return sum((cny for _c, (_v, cny) in (rec.components.get(role) or {}).items()), Decimal(0))


def _legacy_journal_totals(legacy: dict[str, Any]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for line in legacy["journal_lines"]:
        net = (Decimal(line["debit_cny_e8"] or 0) - Decimal(line["credit_cny_e8"] or 0)) / E8
        code = str(line["account_code"])
        if code.startswith("5001") or code.startswith("5051"):
            totals["revenue"] -= net
        elif code.startswith("5603"):
            totals["finance"] += net
            totals["expense_total"] += net
        elif code.startswith("5"):
            totals["expense_total"] += net
        elif code.startswith("1002"):
            totals["funds"] += net
    return {k: v.quantize(Decimal("0.01")) for k, v in totals.items()}


def _v2_totals(session: Session, book_id: str) -> dict[str, Decimal]:
    """Same buckets as v1; expenses reclassified into 财务费用 (fee-like purchases) are reported apart."""
    rows = session.execute(
        select(
            Account.code,
            Account.classification,
            JournalLine.line_role,
            func.coalesce(func.sum(JournalLine.base_amount), 0),
        )
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.book_id == book_id)
        .group_by(Account.code, Account.classification, JournalLine.line_role)
    ).all()
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for code, classification, role, base in rows:
        value = Decimal(int(base)) / 100
        if classification == "revenue":
            totals["revenue"] -= value
        elif classification == "expense":
            totals["expense_total"] += value
            if code.startswith("5603") and role == "cost":
                totals["reclassified_to_finance"] += value
            elif code.startswith("5603"):
                totals["finance"] += value
        elif code == "1012.01":
            totals["funds"] += value
    return dict(totals)


def _legacy_monthly(legacy: dict[str, Any]) -> dict[str, dict[str, Decimal]]:
    entry_month = {e["id"]: str(e["entry_date"])[:7] for e in legacy["journal_entries"]}
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for line in legacy["journal_lines"]:
        month = entry_month.get(line["entry_id"], "?")
        net = (Decimal(line["debit_cny_e8"] or 0) - Decimal(line["credit_cny_e8"] or 0)) / E8
        code = str(line["account_code"])
        if code.startswith("5001") or code.startswith("5051"):
            out[month]["revenue"] -= net
        elif code.startswith("5"):
            out[month]["expense_total"] += net
    return {m: {k: v.quantize(Decimal("0.01")) for k, v in d.items()} for m, d in out.items()}


def _v2_monthly(session: Session, book_id: str) -> dict[str, dict[str, Decimal]]:
    month = func.to_char(JournalLine.effective_date, "YYYY-MM")
    rows = session.execute(
        select(month, Account.classification, func.coalesce(func.sum(JournalLine.base_amount), 0))
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.book_id == book_id, Account.classification.in_(("revenue", "expense")))
        .group_by(month, Account.classification)
    ).all()
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for month, classification, base in rows:
        value = Decimal(int(base)) / 100
        if classification == "revenue":
            out[month]["revenue"] -= value
        else:
            out[month]["expense_total"] += value
    return out


# ------------------------------------------------------------------ report rendering


def render_markdown(report: Report) -> str:
    d = report.as_dict()
    lines = [
        f"# v1 → v2 迁移报告（{'试迁移' if report.dry_run else '正式迁移'}）",
        "",
        f"- 来源：`{report.source}`",
        f"- 账套：`{report.book_id}`",
        f"- 记录：{d['counts'].get('records', 0)}，迁移 {d['counts'].get('migrated', 0)}，"
        f"未迁移 {len(report.anomalies)}",
        f"- 往来方：{d['counts'].get('counterparties', 0)}；汇率：{d['counts'].get('fx_rates', 0)}；"
        f"证据记录：{d['counts'].get('evidence_items', 0)}（未解析 {d['counts'].get('evidence_unparsed', 0)}）",
        f"- 舍入：{len(report.rounding)} 处，净差 {d['rounding_total']}，绝对值合计 {d['rounding_abs_total']}",
        "",
        "## 核对项",
        "",
        "| 编号 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for code, check in report.checks.items():
        lines.append(f"| {code} | {'✅' if check['ok'] else '❌'} | {check['message']} |")
    lines += ["", "## 科目重分类", "", "| 映射 | 笔数 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(report.reclassification.items())]
    lines += ["", "## 未迁移记录（需处理）", ""]
    lines += [
        f"- {a['date']} {a['category']} {a['counterparty'] or ''} {a['description']}：{a['reason']}"
        for a in report.anomalies
    ] or ["无"]
    lines += ["", "## 往来方重命名", "", "| 旧名称 | 新名称 | 分类 |", "|---|---|---|"]
    lines += [
        f"| {c['legacy']} | {c['new']} | {c['category']} |" for c in report.counterparties if c["legacy"] != c["new"]
    ]
    if report.warnings:
        lines += ["", "## 提示", ""] + [f"- {w}" for w in report.warnings]
    return "\n".join(lines) + "\n"
