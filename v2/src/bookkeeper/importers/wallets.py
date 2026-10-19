"""WeChat Pay and Alipay bill exports (CSV / XLSX)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from bookkeeper.importers.base import (
    FileSummary,
    ParsedRecord,
    ParseResult,
    RowError,
    clean,
    column_index,
    decode,
    find_header,
    parse_amount,
    parse_datetime,
    read_rows,
)

DIRECTIONS = {"收入": "in", "支出": "out", "/": "neutral", "不计收支": "neutral", "": "neutral"}
TOTAL_RE = re.compile(r"(收入|支出)[:：]\s*(\d+)\s*笔\s*([\d,.]+)\s*元")
PERIOD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[^\d]+(\d{4}-\d{2}-\d{2})")


def _preamble_summary(rows: list[list[str]], header_index: int) -> FileSummary:
    summary = FileSummary()
    text = "\n".join(" ".join(r) for r in rows[:header_index])
    for kind, count, amount in TOTAL_RE.findall(text):
        key = "in" if kind == "收入" else "out"
        summary.declared[f"{key}_count"] = Decimal(count)
        summary.declared[f"{key}_amount"] = Decimal(amount.replace(",", ""))
    period = PERIOD_RE.search(text)
    if period:
        from datetime import date

        summary.period_from, summary.period_to = (
            date.fromisoformat(period.group(1)),
            date.fromisoformat(period.group(2)),
        )
    return summary


class WechatBill:
    code = "wechat_bill"
    version = "1.0.0"
    VALID = (
        "支付成功",
        "已存入零钱",
        "已转账",
        "对方已收钱",
        "已收钱",
        "朋友已收钱",
        "充值完成",
        "提现已到账",
        "已到账",
    )
    REFUND = ("已全额退款", "对方已退还", "已退款")

    def sniff(self, filename: str, head: bytes) -> float:
        text = decode(head[:4096]) if not filename.lower().endswith(".xlsx") else ""
        return 0.99 if "微信支付账单" in text or ("交易单号" in text and "商户单号" in text) else 0.0

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        rows = read_rows(data, filename)
        h = find_header(rows, ["交易时间", "收/支", "金额"])
        header = rows[h]
        idx = {
            "time": column_index(header, "交易时间"),
            "kind": column_index(header, "交易类型"),
            "party": column_index(header, "交易对方"),
            "goods": column_index(header, "商品"),
            "dir": column_index(header, "收/支"),
            "amount": column_index(header, "金额(元)", "金额"),
            "method": column_index(header, "支付方式"),
            "status": column_index(header, "当前状态"),
            "id": column_index(header, "交易单号"),
            "merchant": column_index(header, "商户单号"),
            "note": column_index(header, "备注"),
        }
        result = ParseResult(summary=_preamble_summary(rows, h))
        for offset, row in enumerate(rows[h + 1 :], start=h + 2):
            if not any(row):
                continue
            raw = {header[i]: row[i] for i in range(min(len(header), len(row)))}

            def get(key: str, _row: list[str] = row) -> str:
                i = idx[key]
                return clean(_row[i]) if i is not None and i < len(_row) else ""

            status = get("status")
            if not any(s in status for s in self.VALID + self.REFUND):
                result.skipped.append(RowError(offset, f"状态“{status}”不入账", raw))
                continue
            try:
                amount = parse_amount(get("amount"))
                if amount is None:
                    raise ValueError("金额为空")
                record = ParsedRecord(
                    row_no=offset,
                    occurred_at=parse_datetime(get("time"), tz),
                    direction=DIRECTIONS.get(get("dir"), "neutral"),
                    amount=abs(amount),
                    commodity="CNY",
                    external_id=get("id") or None,
                    counterparty_text=get("party") or None,
                    description=" · ".join(p for p in (get("kind"), get("goods")) if p and p != "/") or None,
                    order_no=get("merchant") if get("merchant") not in ("", "/") else None,
                    status_text=status,
                    extracted={
                        "payment_method": get("method"),
                        "is_refund": any(s in status for s in self.REFUND) or get("kind").endswith("退款"),
                        # a fully refunded payment and its refund row cancel out; both are ignored by default
                        "fully_refunded": "全额退款" in status or "对方已退还" in status,
                    },
                    raw=raw,
                )
            except ValueError as exc:
                result.errors.append(RowError(offset, str(exc), raw))
                continue
            result.records.append(record)
        return result


class AlipayBill:
    code = "alipay_bill"
    version = "1.0.0"
    VALID = ("交易成功", "退款成功", "支付成功", "已收款", "还款成功")

    def sniff(self, filename: str, head: bytes) -> float:
        text = decode(head[:4096]) if not filename.lower().endswith(".xlsx") else ""
        return 0.99 if "支付宝" in text and ("交易订单号" in text or "交易号" in text) else 0.0

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        rows = read_rows(data, filename)
        h = find_header(rows, ["交易时间", "收/支", "金额"])
        header = rows[h]
        idx = {
            "time": column_index(header, "交易时间", "交易创建时间"),
            "category": column_index(header, "交易分类"),
            "party": column_index(header, "交易对方"),
            "party_account": column_index(header, "对方账号"),
            "goods": column_index(header, "商品说明", "商品名称"),
            "dir": column_index(header, "收/支"),
            "amount": column_index(header, "金额", "金额（元）"),
            "method": column_index(header, "收/付款方式"),
            "status": column_index(header, "交易状态"),
            "id": column_index(header, "交易订单号", "交易号"),
            "merchant": column_index(header, "商家订单号", "商户订单号"),
        }
        result = ParseResult(summary=_preamble_summary(rows, h))
        for offset, row in enumerate(rows[h + 1 :], start=h + 2):
            if not any(row) or (row and row[0].startswith("-")):
                continue
            raw = {header[i]: row[i] for i in range(min(len(header), len(row)))}

            def get(key: str, _row: list[str] = row) -> str:
                i = idx[key]
                return clean(_row[i]) if i is not None and i < len(_row) else ""

            status = get("status")
            if not any(s in status for s in self.VALID):
                result.skipped.append(RowError(offset, f"状态“{status}”不入账", raw))
                continue
            try:
                amount = parse_amount(get("amount"))
                if amount is None:
                    raise ValueError("金额为空")
                result.records.append(
                    ParsedRecord(
                        row_no=offset,
                        occurred_at=parse_datetime(get("time"), tz),
                        direction=DIRECTIONS.get(get("dir"), "neutral"),
                        amount=abs(amount),
                        commodity="CNY",
                        external_id=get("id") or None,
                        counterparty_text=get("party") or None,
                        description=get("goods") or None,
                        order_no=get("merchant") or None,
                        status_text=status,
                        extracted={
                            "category": get("category"),
                            "payment_method": get("method"),
                            "is_refund": "退款" in status,
                        },
                        raw=raw,
                    )
                )
            except ValueError as exc:
                result.errors.append(RowError(offset, str(exc), raw))
        return result
