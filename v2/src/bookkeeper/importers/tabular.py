"""Stripe balance export, configurable tables (long or wide), card-shop orders, upstream redemption logs,
and structured records supplied directly (e.g. extracted by an AI client from screenshots)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC
from decimal import Decimal
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from bookkeeper.importers.base import (
    FACE_PATTERNS,
    ParsedRecord,
    ParseError,
    ParseResult,
    RowError,
    clean,
    column_index,
    decode,
    extract_face,
    find_header,
    mask_secret,
    parse_amount,
    parse_datetime,
    read_rows,
)


class StripeBalance:
    """Stripe → Balance → Export (balance transactions). Payouts stay inside the funds account."""

    code = "stripe_balance"
    version = "1.0.0"
    DIRECTION: ClassVar[dict[str, str]] = {
        "charge": "in",
        "payment": "in",
        "refund": "out",
        "payment_refund": "out",
        "payout": "neutral",
        "stripe_fee": "out",
        "adjustment": "out",
        "dispute": "out",
    }

    def sniff(self, filename: str, head: bytes) -> float:
        text = decode(head[:2048]).lower() if not filename.lower().endswith(".xlsx") else ""
        return 0.98 if "available on" in text and "net" in text and "fee" in text else 0.0

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        rows = read_rows(data, filename)
        h = find_header(rows, ["id", "Amount", "Fee", "Currency"])
        header = rows[h]
        col = {
            "id": column_index(header, "id"),
            "type": column_index(header, "Type", "Reporting Category"),
            "source": column_index(header, "Source"),
            "amount": column_index(header, "Amount", "Gross"),
            "fee": column_index(header, "Fee"),
            "currency": column_index(header, "Currency"),
            "created": column_index(header, "Created (UTC)", "Created"),
            "description": column_index(header, "Description"),
        }
        result = ParseResult()
        utc = ZoneInfo("UTC")
        for offset, row in enumerate(rows[h + 1 :], start=h + 2):
            if not any(row):
                continue
            raw = {header[i]: row[i] for i in range(min(len(header), len(row)))}

            def get(key: str, _row: list[str] = row) -> str:
                i = col[key]
                return clean(_row[i]) if i is not None and i < len(_row) else ""

            kind = get("type").lower()
            try:
                amount = parse_amount(get("amount"))
                if amount is None:
                    raise ValueError("Amount 为空")
                fee = parse_amount(get("fee")) or Decimal(0)
                direction = self.DIRECTION.get(kind, "in" if amount > 0 else "out")
                result.records.append(
                    ParsedRecord(
                        row_no=offset,
                        occurred_at=parse_datetime(get("created"), utc).astimezone(UTC),
                        direction=direction,
                        amount=abs(amount),
                        commodity=get("currency").upper() or "USD",
                        external_id=get("id") or None,
                        fee_amount=abs(fee) if fee else None,
                        description=get("description") or kind,
                        reference=get("source") or None,
                        status_text=kind,
                        extracted={"stripe_type": kind, "channel": "stripe"},
                        raw=raw,
                    )
                )
            except ValueError as exc:
                result.errors.append(RowError(offset, str(exc), raw))
        return result


LONG_ROLES = (
    "datetime",
    "date",
    "time",
    "amount",
    "income",
    "expense",
    "direction",
    "commodity",
    "counterparty",
    "description",
    "order_no",
    "external_id",
    "reference",
    "fee",
    "balance",
    "status",
    "quantity",
    "account",
    "code",
)


class GenericTabular:
    """Any CSV / XLSX / JSON table described by ``config``.

    Long format (one row = one record)::

        {"columns": {"datetime": "交易时间", "amount": "金额", "direction": "收/支",
                     "counterparty": "对方", "description": "说明", "external_id": "流水号"},
         "direction_values": {"收入": "in", "支出": "out"}, "default_direction": "out",
         "default_commodity": "CNY", "status_include": ["成功"], "sensitive": ["code"],
         "extract": [{"field": "description", "pattern": "(?P<face>\\\\d+)R"}]}

    Wide format (one row per date, one column per channel)::

        {"wide": {"date": "日期", "direction": "in",
                  "columns": {"链动": {"channel": "liandong"}, "云猫": {"channel": "yunmao"},
                              "stripe": {"channel": "stripe", "commodity": "GBP", "fee": "stripe手续费"}}}}
    """

    code = "generic_tabular"
    version = "1.0.0"

    def sniff(self, filename: str, head: bytes) -> float:
        return 0.1  # only when chosen explicitly

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        rows = read_rows(data, filename)
        if not rows:
            raise ParseError("文件为空。")
        if config.get("wide"):
            return self._wide(rows, config["wide"], config, tz)
        return self._long(rows, config, tz)

    def _header(self, rows: list[list[str]], names: Sequence[str], config: Mapping[str, Any]) -> int:
        if "header_row" in config:
            return int(config["header_row"])
        return find_header(rows, [n for n in names if n][:3] or [rows[0][0]])

    def _long(self, rows: list[list[str]], config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        columns: dict[str, str] = dict(config.get("columns") or {})
        unknown = set(columns) - set(LONG_ROLES)
        if unknown:
            raise ParseError(f"不支持的列角色：{', '.join(sorted(unknown))}；可用 {', '.join(LONG_ROLES)}。")
        if not ({"datetime", "date"} & set(columns)) or not ({"amount", "income", "expense"} & set(columns)):
            raise ParseError("列映射至少需要 datetime 或 date，以及 amount 或 income / expense。")
        h = self._header(rows, list(columns.values()), config)
        header = rows[h]
        idx = {role: column_index(header, name) for role, name in columns.items()}
        missing = [columns[r] for r, i in idx.items() if i is None]
        if missing:
            raise ParseError(f"表头中找不到列：{'、'.join(missing)}。")
        values = {str(k): v for k, v in (config.get("direction_values") or {}).items()}
        include = config.get("status_include") or []
        exclude = config.get("status_exclude") or []
        sensitive = set(config.get("sensitive") or ["code"])
        extract = config.get("extract") or []
        face_patterns = config.get("face_patterns") or FACE_PATTERNS
        result = ParseResult()
        for offset, row in enumerate(rows[h + 1 :], start=h + 2):
            if not any(row):
                continue

            def get(role: str, _row: list[str] = row) -> str:
                i = idx.get(role)
                return clean(_row[i]) if i is not None and i < len(_row) else ""

            raw = {header[i]: row[i] for i in range(min(len(header), len(row)))}
            for role in sensitive & set(idx):
                if get(role):
                    raw[columns[role]] = "***" + get(role)[-4:]
            status = get("status")
            if (include and not any(s in status for s in include)) or any(s in status for s in exclude if s):
                result.skipped.append(RowError(offset, f"状态“{status}”不入账", raw))
                continue
            try:
                when = (
                    parse_datetime(get("datetime"), tz, config.get("datetime_format"))
                    if "datetime" in idx
                    else parse_datetime(f"{get('date')} {get('time')}".strip(), tz, config.get("datetime_format"))
                )
                direction, amount = self._amount(get, values, config)
                extracted: dict[str, Any] = {}
                for role in ("quantity", "account"):
                    if get(role):
                        extracted[role] = get(role)
                if get("code"):
                    extracted["code"] = mask_secret(get("code"))
                for item in extract:
                    match = re.search(item["pattern"], get(item.get("field", "description")) or "")
                    if match:
                        extracted.update({k: v for k, v in match.groupdict().items() if v is not None})
                face = extract_face(get("description"), face_patterns) if config.get("extract_face") else None
                if face is not None and "face" not in extracted:
                    extracted["face"] = str(face)
                extracted.update(config.get("constants") or {})
                fee = parse_amount(get("fee")) if "fee" in idx else None
                balance = parse_amount(get("balance")) if "balance" in idx else None
                result.records.append(
                    ParsedRecord(
                        row_no=offset,
                        occurred_at=when,
                        direction=direction,
                        amount=amount,
                        commodity=(get("commodity") or config.get("default_commodity") or "CNY").upper(),
                        external_id=get("external_id") or None,
                        fee_amount=abs(fee) if fee else None,
                        balance_after=balance,
                        counterparty_text=get("counterparty") or config.get("counterparty") or None,
                        description=get("description") or None,
                        order_no=get("order_no") or None,
                        reference=get("reference") or None,
                        status_text=status or None,
                        extracted=extracted,
                        raw=raw,
                    )
                )
            except ValueError as exc:
                result.errors.append(RowError(offset, str(exc), raw))
        return result

    @staticmethod
    def _amount(get: Any, values: Mapping[str, str], config: Mapping[str, Any]) -> tuple[str, Decimal]:
        if get("income") or get("expense"):
            income, expense = parse_amount(get("income")), parse_amount(get("expense"))
            if income:
                return "in", abs(income)
            if expense:
                return "out", abs(expense)
        amount = parse_amount(get("amount"))
        if amount is None:
            raise ValueError("金额为空")
        if get("direction"):
            text = get("direction")
            direction = values.get(text) or next((v for k, v in values.items() if k in text), None)
            if direction is None:
                raise ValueError(f"方向“{text}”未在 direction_values 中定义")
            return direction, abs(amount)
        if config.get("signed"):
            return ("in" if amount > 0 else "out"), abs(amount)
        return str(config.get("default_direction") or "out"), abs(amount)

    def _wide(
        self, rows: list[list[str]], wide: Mapping[str, Any], config: Mapping[str, Any], tz: ZoneInfo
    ) -> ParseResult:
        date_col = wide.get("date") or "日期"
        h = find_header(rows, [date_col])
        header = rows[h]
        date_i = column_index(header, date_col)
        assert date_i is not None
        specs = []
        for name, spec in (wide.get("columns") or {}).items():
            i = column_index(header, name)
            if i is None:
                raise ParseError(f"表头中找不到列：{name}。")
            fee_i = column_index(header, spec["fee"]) if spec.get("fee") else None
            specs.append((name, i, fee_i, spec))
        result = ParseResult()
        for offset, row in enumerate(rows[h + 1 :], start=h + 2):
            if not any(row) or not clean(row[date_i]):
                continue
            raw = {header[i]: row[i] for i in range(min(len(header), len(row)))}
            try:
                when = parse_datetime(row[date_i], tz, config.get("datetime_format"))
            except ValueError as exc:
                result.errors.append(RowError(offset, str(exc), raw))
                continue
            for name, i, fee_i, spec in specs:
                try:
                    amount = parse_amount(row[i]) if i < len(row) else None
                    if not amount:
                        continue
                    fee = parse_amount(row[fee_i]) if fee_i is not None and fee_i < len(row) else None
                    extracted = {k: v for k, v in spec.items() if k not in ("fee", "commodity", "direction")}
                    result.records.append(
                        ParsedRecord(
                            row_no=offset,
                            occurred_at=when,
                            direction=spec.get("direction") or wide.get("direction") or "in",
                            amount=abs(amount),
                            commodity=(spec.get("commodity") or config.get("default_commodity") or "CNY").upper(),
                            external_id=f"{when.date().isoformat()}:{name}",
                            fee_amount=abs(fee) if fee else None,
                            description=f"{name} {when.date().isoformat()} 合计",
                            extracted=extracted | {"column": name, "daily_total": True},
                            raw=raw,
                        )
                    )
                except ValueError as exc:
                    result.errors.append(RowError(offset, f"{name}：{exc}", raw))
        return result


class CardShopOrders(GenericTabular):
    """Card-shop order lists (链动 / 云猫 / 16888…): product name → face value; site mapping by rules."""

    code = "card_shop_orders"
    version = "1.0.0"
    DEFAULT_COLUMNS: ClassVar[dict[str, tuple[str, ...]]] = {
        "order_no": ("订单号", "订单编号", "order", "order_no"),
        "description": ("商品名称", "商品", "name", "product"),
        "amount": ("实付金额", "金额", "总价", "amount", "price"),
        "datetime": ("付款时间", "支付时间", "下单时间", "时间", "time", "paid_at"),
        "status": ("订单状态", "状态", "status"),
        "quantity": ("数量", "qty", "quantity"),
        "code": ("卡密", "兑换码", "code"),
    }

    def sniff(self, filename: str, head: bytes) -> float:
        try:
            text = decode(head[:4096])
        except Exception:
            return 0.0
        return 0.85 if "订单号" in text and ("商品" in text or "卡密" in text) else 0.0

    def _columns(self, header: Sequence[str]) -> dict[str, str]:
        columns: dict[str, str] = {}
        for role, names in self.DEFAULT_COLUMNS.items():
            for name in names:
                i = column_index(header, name)
                if i is not None and header[i] not in columns.values():
                    columns[role] = header[i]
                    break
        return columns

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        rows = read_rows(data, filename)
        merged = dict(config)
        if "columns" not in merged:
            # The header is the row naming the most known columns: exports often open with a title or a
            # summary block that also mentions 订单.
            found = [(self._columns(r), i) for i, r in enumerate(rows[:40])]
            columns, header_i = max(found, key=lambda f: (len(f[0]), -f[1]), default=({}, 0))
            merged["columns"] = columns
            merged.setdefault("header_row", header_i)
        merged.setdefault("default_direction", "out" if merged.get("role", "purchase") == "purchase" else "in")
        merged.setdefault("status_exclude", ["已退款", "退款", "已关闭", "未付款", "待付款", "已取消"])
        merged["extract_face"] = True
        result = super().parse(data, filename, merged, tz)
        shop = config.get("shop") or ""
        records = []
        for r in result.records:
            records.append(
                ParsedRecord(
                    **{
                        **r.__dict__,
                        "external_id": f"{shop}:{r.order_no}" if shop and r.order_no else (r.order_no or r.external_id),
                        "extracted": {**r.extracted, "product": r.description, "shop": shop},
                    }
                )
            )
        result.records = records
        return result


class UpstreamUsageLog(GenericTabular):
    """Upstream site redemption / top-up logs: credits received on the site (evidence for purchases)."""

    code = "upstream_usage_log"
    version = "1.0.0"

    def sniff(self, filename: str, head: bytes) -> float:
        return 0.1

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        merged = dict(config)
        merged.setdefault("default_direction", "in")
        merged.setdefault("default_commodity", "UCR")
        merged.setdefault("columns", {"datetime": "time", "amount": "amount", "account": "account", "code": "code"})
        result = super().parse(data, filename, merged, tz)
        site = config.get("counterparty")
        result.records = [
            ParsedRecord(
                **{
                    **r.__dict__,
                    "counterparty_text": r.counterparty_text or site,
                    "extracted": {**r.extracted, "site": site, "credits": str(r.amount)},
                }
            )
            for r in result.records
        ]
        return result


class StructuredRecords:
    """JSON records already in normalised form — the path for AI clients that read screenshots or PDFs.

    Each record: ``occurred_at`` (ISO, offset optional → source time zone), ``direction`` (in/out/neutral),
    ``amount`` (string), ``commodity``; optional ``external_id``, ``fee``, ``balance_after``,
    ``counterparty``, ``description``, ``order_no``, ``reference``, ``status``, ``extracted`` (object).
    """

    code = "records"
    version = "1.0.0"
    FIELDS: ClassVar[set[str]] = {
        "occurred_at",
        "direction",
        "amount",
        "commodity",
        "external_id",
        "fee",
        "balance_after",
        "counterparty",
        "description",
        "order_no",
        "reference",
        "status",
        "extracted",
    }

    def sniff(self, filename: str, head: bytes) -> float:
        return 0.0

    def parse(self, data: bytes, filename: str, config: Mapping[str, Any], tz: ZoneInfo) -> ParseResult:
        import json

        items = json.loads(decode(data))
        if isinstance(items, dict):
            items = items.get("records", [])
        result = ParseResult()
        for n, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                result.errors.append(RowError(n, "记录必须是对象"))
                continue
            unknown = set(item) - self.FIELDS
            try:
                if unknown:
                    raise ValueError(f"不支持的字段：{', '.join(sorted(unknown))}")
                if isinstance(item.get("amount"), float):
                    raise ValueError("amount 必须是字符串小数，不能是浮点数")
                amount = parse_amount(str(item.get("amount", "")))
                if amount is None:
                    raise ValueError("amount 为空")
                direction = item.get("direction") or config.get("default_direction")
                if direction not in ("in", "out", "neutral"):
                    raise ValueError("direction 必须是 in / out / neutral")
                extracted = dict(item.get("extracted") or {})
                if "code" in extracted and isinstance(extracted["code"], str):
                    extracted["code"] = mask_secret(extracted["code"])
                fee = parse_amount(str(item["fee"])) if item.get("fee") not in (None, "") else None
                balance = (
                    parse_amount(str(item["balance_after"])) if item.get("balance_after") not in (None, "") else None
                )
                result.records.append(
                    ParsedRecord(
                        row_no=n,
                        occurred_at=parse_datetime(str(item.get("occurred_at", "")), tz),
                        direction=direction,
                        amount=abs(amount),
                        commodity=str(item.get("commodity") or config.get("default_commodity") or "CNY").upper(),
                        external_id=str(item["external_id"]) if item.get("external_id") else None,
                        fee_amount=abs(fee) if fee else None,
                        balance_after=balance,
                        counterparty_text=item.get("counterparty") or config.get("counterparty"),
                        description=item.get("description"),
                        order_no=item.get("order_no"),
                        reference=item.get("reference"),
                        status_text=item.get("status"),
                        extracted=extracted,
                        raw={k: v for k, v in item.items() if k != "extracted"},
                    )
                )
            except ValueError as exc:
                result.errors.append(RowError(n, str(exc), {k: str(v)[:200] for k, v in item.items()}))
        return result
