"""Upstream redeem pages printed to PDF (兑换码 › 最近活动): one record per balance top-up.

Relay-station panels list each credit as "余额充值（兑换）", a timestamp, the credited amount and the start of
the code ("PAY-1843..."). Browser print adds the page URL in the footer, which names the site; the source's
``counterparty`` setting or the file name are the fallbacks; a file name cut short ("relay-b.exa（2）.pdf") is completed
from the sites the books know (``known_hosts``, filled in when a batch is staged). Text-only: a scanned PDF has
no text layer and goes through the AI source instead.
"""

from __future__ import annotations

import io
import re
from collections.abc import Collection, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from bookkeeper.importers.base import ParsedRecord, ParseError, ParseResult, RowError

ENTRY = re.compile(r"余额充值\s*[（(]\s*([^）)\n]{1,8})\s*[）)]")
STAMP = re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})")
AMOUNT = re.compile(r"([+-])\s*([$¥￥])\s*([\d,]+(?:\.\d+)?)")
CODE = re.compile(r"(?<![\w-])([A-Za-z0-9][A-Za-z0-9_-]{1,40})(?:\.{2,}|…)")
URL = re.compile(r"https?://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(\S*)")
PAGE_NO = re.compile(r"^\s*\d+\s*/\s*\d+\s*$")
FILE_HOST = re.compile(r"^([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
FILE_EXT = re.compile(r"\.(pdf|png|jpe?g|webp|gif)$", re.IGNORECASE)
UNITS = {"$": "USD", "¥": "CNY", "￥": "CNY"}


def pdf_pages(data: bytes) -> list[tuple[str, str]]:
    """(reading-order text, layout text) per page; layout mode keeps the browser's header and footer."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        return [(p.extract_text() or "", p.extract_text(extraction_mode="layout") or "") for p in reader.pages]
    except (PdfReadError, ValueError, KeyError) as exc:
        raise ParseError(f"PDF 无法读取：{exc}") from exc


def site_host(pages: list[tuple[str, str]], filename: str, known: Collection[str] = ()) -> str | None:
    """The printed page's own URL: the footer link to …/redeem, or the URL beside the page number; else the
    file name (owners tend to name the file after the site). Links inside the page (shops, chat groups) lose."""
    footer = None
    for _text, layout in pages:
        for line in layout.splitlines():
            for match in URL.finditer(line):
                if "redeem" in match.group(2).lower():
                    return match.group(1).lower()
                if footer is None and PAGE_NO.match(line[match.end() :]):
                    footer = match.group(1).lower()
    if footer:
        return footer
    return filename_host(filename, known)


def filename_host(filename: str, known: Collection[str] = ()) -> str | None:
    """The host a file is named after ("relay-b.example（1）.pdf"), completed from the known sites when the name was cut
    short ("relay-b.exa（2）.pdf")."""
    stem = filename.replace("\u200b", "").rsplit("/", 1)[-1]
    found = FILE_HOST.match(FILE_EXT.sub("", stem))
    return completed(found.group(1).lower().rstrip("."), known) if found else None


def completed(host: str, known: Collection[str]) -> str:
    """A host read from a file name may be cut short (relay-b.exa for relay-b.example). When it is not a known site
    but exactly one known site's host starts with it, that site is meant; otherwise (none, several) it stays as
    read."""
    bare = host.removeprefix("www.")
    sites = {k.lower().removeprefix("www."): k.lower() for k in known}
    if not sites or bare in sites:
        return host
    starting = [full for short, full in sites.items() if short.startswith(bare)]
    return starting[0] if len(starting) == 1 else host


class RedeemPage:
    code = "redeem_page"
    version = "1.0.0"

    def sniff(self, filename: str, head: bytes) -> float:
        return 0.5 if head.startswith(b"%PDF") else 0.0

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        if not data.startswith(b"%PDF"):
            raise ParseError("兑换记录页需要 PDF 文件（在浏览器里把兑换码页面打印为 PDF）。")
        pages = pdf_pages(data)
        text = "\n".join(t for t, _layout in pages)
        if not text.strip():
            raise ParseError("这个 PDF 没有文字层（可能是扫描件或截图），请改用 AI 识别来源。")
        host = str(config.get("counterparty") or "") or site_host(pages, filename, config.get("known_hosts") or ())
        result = ParseResult()
        marks = list(ENTRY.finditer(text))
        if not marks:
            raise ParseError("没有找到“余额充值”记录：这不像兑换码页面的“最近活动”列表。")
        for n, (mark, nxt) in enumerate(zip(marks, [*marks[1:], None], strict=True), start=1):
            chunk = text[mark.end() : nxt.start() if nxt else len(text)]
            kind = mark.group(1).strip()
            raw = {"entry": " ".join(f"{mark.group(0)} {chunk}".split())[:200], "file": filename}
            stamp, amount = STAMP.search(chunk), AMOUNT.search(chunk)
            if stamp is None or amount is None:
                result.errors.append(RowError(n, f"{filename} 第 {n} 条缺少{'时间' if stamp is None else '金额'}", raw))
                continue
            if amount.group(1) == "-":
                result.skipped.append(RowError(n, "余额扣减不是充值", raw))
                continue
            y, mo, d, h, mi, sec = (int(g) for g in stamp.groups())
            when = datetime(y, mo, d, h, mi, sec, tzinfo=tz)
            credits = Decimal(amount.group(3).replace(",", ""))
            code = CODE.search(chunk)
            prefix = code.group(1) if code else None
            result.records.append(
                ParsedRecord(
                    row_no=n,
                    occurred_at=when,
                    direction="in",
                    amount=credits,
                    commodity="UCR",
                    external_id=f"{host or 'site'}:{when.strftime('%Y%m%d%H%M%S')}:{credits}:{prefix or ''}",
                    counterparty_text=host,
                    description=f"余额充值（{kind}） {amount.group(2)}{amount.group(3)}",
                    reference=prefix,
                    status_text=kind,
                    extracted={
                        "site": host,
                        "credits": str(credits),
                        "unit": UNITS.get(amount.group(2), "USD"),
                        "entry_kind": kind,
                        "code_prefix": prefix,
                    },
                    raw=raw,
                )
            )
        return result
