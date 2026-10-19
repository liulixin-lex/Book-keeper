"""AI 识别: screenshots and PDFs → structured records through the provider routed for 识别 (设置 → AI).

Transcription only. One request per file (files run in parallel), a JSON schema for the answer, and nothing
touches the database here: the caller stages the records as an import batch, where they are deduplicated,
classified, matched against the books and finished like any other import. Unreadable rows are reported, never
guessed.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from bookkeeper.ai import adapters
from bookkeeper.ai.adapters import Target
from bookkeeper.config import Settings
from bookkeeper.domain.errors import DomainError
from bookkeeper.importers.redeem import filename_host

MAX_TOKENS = 32_000

_TEXT = {"anyOf": [{"type": "string"}, {"type": "null"}]}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page_kind": {"type": "string"},
        "site": _TEXT,
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "occurred_at": _TEXT,
                    "direction": {"type": "string", "enum": ["in", "out", "neutral"]},
                    "amount": {"type": "string"},
                    "currency": _TEXT,
                    "fee": _TEXT,
                    "order_no": _TEXT,
                    "counterparty": _TEXT,
                    "description": _TEXT,
                    "status": _TEXT,
                    "quantity": _TEXT,
                    "face": _TEXT,
                },
                "required": [
                    "occurred_at",
                    "direction",
                    "amount",
                    "currency",
                    "fee",
                    "order_no",
                    "counterparty",
                    "description",
                    "status",
                    "quantity",
                    "face",
                ],
                "additionalProperties": False,
            },
        },
        "totals": {"type": "array", "items": {"type": "string"}},
        "unreadable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["page_kind", "site", "records", "totals", "unreadable"],
    "additionalProperties": False,
}

SYSTEM = """You transcribe screenshots and PDFs of money records for a small business's bookkeeping app: order
lists from card shops (发卡网), top-up / redeem logs from API relay sites, wallet bills, receipts.

Return every money row that is fully visible, exactly as shown:
- occurred_at: the row's own date and time as "YYYY-MM-DD HH:MM:SS" (or "YYYY-MM-DD" when no time is shown).
  Never use the page's print or capture time. If the year is not shown anywhere, set null.
- amount: the row's money amount as a plain decimal string, no sign, no symbol, no thousands separator.
  currency: CNY for ¥/￥/元, USD for $, GBP for £, otherwise the code shown; null if nothing says.
- direction: "out" when the business pays (a purchase, an order it placed, a fee); "in" when it receives money
  or account credit (income, a refund to it, a top-up or 兑换 credited to its balance); "neutral" otherwise.
- order_no: the order number, transaction id or (partial) code on the row, copied character for character.
- counterparty: the shop, site, merchant or person on the row; description: the product or row text.
- status: the row's status text (已完成, 已退款, 支付成功 …); fee, quantity: when the row shows them.
- face: a face value stated in the product name, e.g. "100" for "100R" or "余额+50", "$20" → "20".
Keep all text in its original language. Skip headers, summaries, buttons and ads.

Never guess. A row cut off at the edge, or with an amount, date or identifier you cannot read for certain,
goes into "unreadable" as a short note instead of "records". Put totals or balances the page itself shows
(共 12 条, 合计 ¥350.00, 当前余额 $34.31) into "totals" as written. page_kind says in a few words what the
page is; site is the domain or platform the page belongs to, when shown. A site's host goes in exactly as the
page shows it, subdomain included: "api.relay-a.example" stays "api.relay-a.example", never shortened to
"relay-a.example"; the same holds for a host in counterparty."""


@dataclass
class Extracted:
    records: list[dict[str, Any]] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    totals: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    model: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)  # per provider call: target, usage, ok — for 用量


def _read(
    targets: list[Target],
    name: str,
    data: bytes,
    mime: str,
    hint: str,
    backend: adapters.Backend | None,
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """One file → the model's transcription, from the first provider that answers."""
    from bookkeeper.services import ai_providers

    note = f"About this source: {hint.strip()}\n\n" if hint.strip() else ""
    request = adapters.Request(
        system=SYSTEM,
        messages=[
            adapters.Message(
                "user",
                [
                    adapters.Part.of_file(name, data, mime),
                    adapters.Part.of_text(f"{note}File: {name}. Transcribe its money rows."),
                ],
            )
        ],
        schema=SCHEMA,
        max_tokens=MAX_TOKENS,
    )
    try:
        target, response = ai_providers.call(targets, request, backend=backend, attempts=calls)
    except DomainError as exc:
        if exc.code == "INPUT_INVALID":
            raise DomainError("INPUT_INVALID", f"{name}：{exc.detail}") from exc
        raise
    if response.stop == "refusal":
        raise DomainError("INPUT_INVALID", f"{name}：AI 拒绝处理这个文件。")
    if response.stop == "max_tokens":
        raise DomainError("INPUT_INVALID", f"{name}：内容太多，一次读不完。请分成几张截图或几页再传。")
    answer: dict[str, Any] = dict(response.data or {})
    answer["_usage"] = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    answer["_model"] = response.model or target.model
    return answer


def _decimal(value: Any) -> str | None:
    text = str(value or "").replace(",", "").strip().lstrip("+")
    try:
        return format(Decimal(text), "f") if text else None
    except InvalidOperation:
        return None


def file_site(name: str, known: Collection[str]) -> str | None:
    """The known site a file is named after, for pages that show no site of their own (an image-only print of a
    redeem page): the name as read, or completed when cut short (importers/redeem.py). Never an unknown host."""
    host = filename_host(name, known)
    sites = {k.lower().removeprefix("www.") for k in known}
    return host if host and host.removeprefix("www.") in sites else None


def _records(
    name: str, answer: dict[str, Any], commodity: str | None, known: Collection[str] = ()
) -> list[dict[str, Any]]:
    """The model's rows in the structured-records shape the `records` parser validates."""
    site = answer.get("site") or file_site(name, known)
    out = []
    for row in answer.get("records") or []:
        face, quantity = _decimal(row.get("face")), _decimal(row.get("quantity"))
        unit = (row.get("currency") or "").upper() or None
        extracted = {k: v for k, v in {"face": face, "quantity": quantity, "file": name, "site": site}.items() if v}
        if commodity:  # e.g. UCR: the amounts are credits on a site, the shown symbol is just their unit
            extracted["unit"] = unit
        out.append(
            {
                "occurred_at": row.get("occurred_at") or "",
                "direction": row.get("direction") or "out",
                "amount": _decimal(row.get("amount")) or "",
                "commodity": commodity or unit or "CNY",
                "external_id": row.get("order_no") or None,
                "order_no": row.get("order_no") or None,
                "fee": _decimal(row.get("fee")),
                "counterparty": row.get("counterparty") or site or None,
                "description": row.get("description") or None,
                "status": row.get("status") or None,
                "extracted": extracted | {"ai": True},
            }
        )
    return out


def check(files: Sequence[tuple[str, str]], settings: Settings, *, configured: bool) -> None:
    """Refuse an upload before anything is stored or spent: no provider, too many files, a type AI can't read."""
    if not configured:
        raise DomainError(
            "AI_UNAVAILABLE", "AI 识别还没配置：在 设置 → AI 添加提供商，或在服务器上设置 BK_AI_API_KEY 后可用。"
        )
    if not files:
        raise DomainError("VALIDATION_FAILED", "请至少选择一个文件。")
    if len(files) > settings.ai_max_files:
        raise DomainError("VALIDATION_FAILED", f"一次最多 {settings.ai_max_files} 个文件，请分批上传。")
    for name, mime in files:
        adapters.Part.of_file(name, b"", mime)


COUNT_RE = re.compile(r"共\s*(\d+)\s*(?:条|笔|单|项|个)")
SUM_RE = re.compile(r"(?:合计|总计|共计|总额|总金额|小计)[^\d\n]{0,8}?([\d,]+(?:\.\d+)?)")


def totals_checks(name: str, totals: Sequence[str], rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare what the page says it holds (共 N 条, 合计 ¥X) with what was read from it. Warnings only: a page
    total may also cover rows outside the screenshot, so the owner judges."""
    out = []
    count = len(rows)
    amount = sum((Decimal(r["amount"]) for r in rows if r.get("amount")), Decimal(0))
    for text in totals:
        if found := COUNT_RE.search(text):
            shown = int(found.group(1))
            out.append(
                {
                    "code": "ai_totals",
                    "severity": "warning",
                    "ok": shown == count,
                    "message": f"{name}：页面写共 {shown} 条，读到 {count} 条"
                    if shown != count
                    else f"{name}：条数与页面一致（{count} 条）",
                }
            )
        if found := SUM_RE.search(text):
            shown_amount = Decimal(found.group(1).replace(",", ""))
            same = abs(shown_amount - amount) < Decimal("0.01")
            out.append(
                {
                    "code": "ai_totals",
                    "severity": "warning",
                    "ok": same,
                    "message": f"{name}：页面合计 {shown_amount}，读到的合计 {amount}"
                    if not same
                    else f"{name}：合计与页面一致（{amount}）",
                }
            )
    return out


def extract(
    files: Sequence[tuple[str, bytes, str]],
    *,
    hint: str = "",
    commodity: str | None = None,
    settings: Settings,
    targets: list[Target],
    backend: adapters.Backend | None = None,
    known_hosts: Collection[str] = (),
    calls: list[dict[str, Any]] | None = None,
) -> Extracted:
    """Read each (name, bytes, mime) file. Rows seen in several files (overlapping screenshots) are kept once.
    ``calls`` collects each provider call (target, usage, ok), also when a read fails, for 用量."""
    check([(name, mime) for name, _data, mime in files], settings, configured=bool(targets))
    calls = calls if calls is not None else []
    with ThreadPoolExecutor(max_workers=min(4, len(files))) as pool:
        answers = list(pool.map(lambda f: _read(targets, f[0], f[1], f[2], hint, backend, calls), files))
    result = Extracted(model=targets[0].model, calls=calls)
    seen: dict[tuple[Any, ...], str] = {}
    for (name, _data, _mime), answer in zip(files, answers, strict=True):
        result.model = answer.get("_model") or result.model
        for counter in ("input_tokens", "output_tokens"):
            result.usage[counter] += int(answer["_usage"][counter])
        result.unreadable += [f"{name}：{u}" for u in answer.get("unreadable") or []]
        result.totals += [f"{name}：{t}" for t in answer.get("totals") or []]
        rows = _records(name, answer, commodity, known_hosts)
        result.checks += totals_checks(name, answer.get("totals") or [], rows)
        for rec in rows:
            key = (rec["occurred_at"], rec["amount"], rec["direction"], rec["order_no"], rec["description"])
            if seen.get(key, name) != name:
                continue  # the same row on an overlapping screenshot
            seen[key] = name
            result.records.append(rec)
    return result
