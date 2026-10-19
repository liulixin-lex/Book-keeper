"""Built-in parsers, keyed by source kind."""

from __future__ import annotations

from bookkeeper.importers.base import ParsedRecord, ParseError, Parser, ParseResult, RowError
from bookkeeper.importers.redeem import RedeemPage
from bookkeeper.importers.tabular import (
    CardShopOrders,
    GenericTabular,
    StripeBalance,
    StructuredRecords,
    UpstreamUsageLog,
)
from bookkeeper.importers.wallets import AlipayBill, WechatBill

PARSERS: dict[str, Parser] = {
    p.code: p
    for p in (
        WechatBill(),
        AlipayBill(),
        StripeBalance(),
        CardShopOrders(),
        UpstreamUsageLog(),
        RedeemPage(),
        GenericTabular(),
        StructuredRecords(),
    )
}


def sniff(filename: str, head: bytes) -> tuple[str | None, float]:
    """Best guess for an unlabelled file: (parser code, confidence)."""
    best: tuple[str | None, float] = (None, 0.0)
    for code, parser in PARSERS.items():
        try:
            score = parser.sniff(filename, head)
        except Exception:
            score = 0.0
        if score > best[1]:
            best = (code, score)
    return best


__all__ = ["PARSERS", "ParseError", "ParseResult", "ParsedRecord", "Parser", "RowError", "sniff"]
