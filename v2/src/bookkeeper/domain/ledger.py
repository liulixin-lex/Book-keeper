"""Journal line construction and validation (docs/05-posting-engine.md §6–§9)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from bookkeeper.domain.errors import DomainError, FieldError
from bookkeeper.domain.fx import FxQuote, convert_minor

BASE_ONLY_ROLES = frozenset({"rounding", "fx_realization"})
ENGINE_VERSION = "ledger-1"
RATE_QUANTUM = Decimal("1e-12")  # numeric(28,12) in the database
QUANTITY_QUANTUM = Decimal("1e-8")  # numeric(28,8)
MAX_RATE = Decimal("1e15")


def quantize_rate(rate: Decimal) -> Decimal:
    """Rates are stored with 12 decimals; quantize before use so stored == hashed == applied."""
    value = rate.quantize(RATE_QUANTUM, rounding=ROUND_HALF_EVEN)
    if not Decimal(0) < value < MAX_RATE:
        raise DomainError("INPUT_INVALID", f"汇率 {rate} 超出允许范围。")
    return value


@dataclass(frozen=True)
class AccountInfo:
    id: str
    code: str
    name: str
    classification: str
    normal_side: str
    role: str | None = None
    is_group: bool = False
    is_active: bool = True
    allowed_commodities: tuple[str, ...] | None = None
    open_date: date | None = None
    close_date: date | None = None
    manual_entry_allowed: bool = True
    required_dimensions: tuple[str, ...] = ()
    forbidden_dimensions: tuple[str, ...] = ()
    balance_rule: str = "any"


@dataclass(frozen=True)
class LineInput:
    account: AccountInfo
    side: str
    amount_minor: int
    commodity: str
    fx_rate: Decimal | None = None
    base_amount_minor: int | None = None
    counterparty_id: str | None = None
    counterparty_account_id: str | None = None
    dimensions: Mapping[str, str] = field(default_factory=dict)
    memo: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    line_role: str = "manual"


@dataclass(frozen=True)
class BuildSettings:
    base_commodity: str
    scales: Mapping[str, int]
    effective_date: date
    rounding_mode: str = "half_up"
    tolerance_per_line: int = 1
    enforce_manual_flag: bool = True
    allow_conversion: bool = False
    fx_realization: str = "immediate"
    trading_account: AccountInfo | None = None
    fx_gain_loss_account: AccountInfo | None = None
    rounding_account: AccountInfo | None = None
    offset_account: AccountInfo | None = None  # opening balances: per-commodity balancing line
    quote_for: Callable[[str], FxQuote | None] = lambda _commodity: None


@dataclass(frozen=True)
class BuiltLine:
    line_no: int
    account_id: str
    account_code: str
    commodity: str
    amount: int
    base_amount: int
    fx_rate: Decimal | None = None
    fx_rate_id: str | None = None
    fx_source: str | None = None
    counterparty_id: str | None = None
    counterparty_account_id: str | None = None
    dimensions: tuple[tuple[str, str], ...] = ()
    memo: str | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    line_role: str = "manual"


@dataclass(frozen=True)
class BuildResult:
    lines: tuple[BuiltLine, ...]
    warnings: tuple[dict[str, str], ...] = ()
    fx: tuple[dict[str, Any], ...] = ()


def _warning(code: str, message: str, path: str = "") -> dict[str, str]:
    return {"code": code, "message": message, "path": path}


def validate_account(
    account: AccountInfo,
    commodity: str,
    on: date,
    path: str,
    *,
    manual: bool,
    dims: Mapping[str, str],
) -> list[FieldError]:
    errors: list[FieldError] = []
    label = f"科目 {account.code} {account.name}"
    if account.is_group:
        errors.append(FieldError(path, "ACCOUNT_NOT_POSTABLE", f"{label} 是分组科目，只能记到明细科目"))
    if not account.is_active:
        errors.append(FieldError(path, "ACCOUNT_NOT_POSTABLE", f"{label} 已停用"))
    if account.allowed_commodities is not None and commodity not in account.allowed_commodities:
        allowed = "、".join(account.allowed_commodities)
        errors.append(FieldError(path, "ACCOUNT_NOT_POSTABLE", f"{label} 只允许 {allowed}，不允许 {commodity}"))
    if account.open_date and on < account.open_date:
        errors.append(FieldError(path, "ACCOUNT_NOT_POSTABLE", f"{label} 于 {account.open_date} 开户"))
    if account.close_date and on > account.close_date:
        errors.append(FieldError(path, "ACCOUNT_NOT_POSTABLE", f"{label} 已于 {account.close_date} 销户"))
    if manual and not account.manual_entry_allowed:
        errors.append(FieldError(path, "ACCOUNT_NOT_POSTABLE", f"{label} 不允许手工记账"))
    for dim in account.required_dimensions:
        if dim not in dims:
            errors.append(FieldError(path, "DIMENSION_REQUIRED", f"{label} 必须填写维度 {dim}"))
    for dim in account.forbidden_dimensions:
        if dim in dims:
            errors.append(FieldError(path, "DIMENSION_FORBIDDEN", f"{label} 不允许维度 {dim}"))
    return errors


def build_lines(inputs: Sequence[LineInput], settings: BuildSettings) -> BuildResult:
    """Turn line inputs into balanced journal lines, or raise DomainError with every problem."""
    base = settings.base_commodity
    errors: list[FieldError] = []
    if len(inputs) < (1 if settings.offset_account else 2):
        errors.append(FieldError("lines", "INPUT_INVALID", "分录至少需要两行"))
    for i, line in enumerate(inputs):
        path = f"lines.{i}"
        if line.side not in ("debit", "credit"):
            errors.append(FieldError(f"{path}.side", "INPUT_INVALID", "方向必须是 debit 或 credit"))
        if line.amount_minor <= 0:
            errors.append(FieldError(f"{path}.amount", "INPUT_INVALID", "金额必须大于 0"))
        if line.commodity not in settings.scales:
            errors.append(FieldError(f"{path}.amount", "INPUT_INVALID", f"未知币种 {line.commodity}"))
        if line.quantity is not None and line.quantity != line.quantity.quantize(QUANTITY_QUANTUM):
            errors.append(FieldError(f"{path}.quantity", "INPUT_INVALID", "统计数量最多 8 位小数"))
        if (line.quantity is None) != (line.quantity_unit is None):
            errors.append(FieldError(f"{path}.quantity", "INPUT_INVALID", "统计数量与单位须同时填写"))
        if line.commodity == base and (line.fx_rate is not None or line.base_amount_minor is not None):
            errors.append(FieldError(f"{path}.fx_rate", "INPUT_INVALID", "本位币行不能指定汇率"))
        errors += validate_account(
            line.account,
            line.commodity,
            settings.effective_date,
            f"{path}.account",
            manual=settings.enforce_manual_flag,
            dims=line.dimensions,
        )
    _raise(errors)

    warnings: list[dict[str, str]] = []
    quotes: dict[str, FxQuote] = {}
    fx_info: dict[str, dict[str, Any]] = {}
    built: list[BuiltLine] = []
    base_scale = settings.scales[base]
    for i, line in enumerate(inputs):
        sign = 1 if line.side == "debit" else -1
        amount = sign * line.amount_minor
        fx_rate = fx_rate_id = fx_source = None
        if line.commodity == base:
            base_amount = amount
        else:
            scale = settings.scales[line.commodity]
            if line.base_amount_minor is not None:
                base_amount = sign * line.base_amount_minor
                fx_rate = quantize_rate(
                    (Decimal(line.base_amount_minor) / Decimal(line.amount_minor)).scaleb(scale - base_scale)
                )
                fx_source = "actual"
            elif line.fx_rate is not None:
                fx_rate, fx_source = quantize_rate(line.fx_rate), "actual"
                base_amount = convert_minor(amount, scale, fx_rate, base_scale, settings.rounding_mode)
            else:
                quote = quotes.get(line.commodity)
                if quote is None:
                    quote = settings.quote_for(line.commodity)
                    if quote is None:
                        errors.append(
                            FieldError(
                                f"lines.{i}.amount",
                                "FX_RATE_MISSING",
                                f"{settings.effective_date} 没有 {line.commodity}→{base} 汇率，"
                                "请先录入汇率或在行上指定汇率",
                            )
                        )
                        continue
                    quotes[line.commodity] = quote
                    for w in quote.warnings:
                        code, _, detail = w.partition(":")
                        warnings.append(_warning(code, f"{line.commodity} 汇率使用 {detail}", f"lines.{i}"))
                fx_rate, fx_rate_id, fx_source = (
                    quantize_rate(quote.rate),
                    quote.rate_id,
                    quote.source,
                )
                base_amount = convert_minor(amount, scale, fx_rate, base_scale, settings.rounding_mode)
                fx_info[line.commodity] = {
                    "commodity": line.commodity,
                    "rate": format(fx_rate.normalize(), "f"),
                    "source": quote.source,
                    "rate_date": quote.rate_date.isoformat() if quote.rate_date else None,
                    "rate_id": quote.rate_id,
                    "via": quote.via,
                }
        built.append(
            BuiltLine(
                line_no=0,
                account_id=line.account.id,
                account_code=line.account.code,
                commodity=line.commodity,
                amount=amount,
                base_amount=base_amount,
                fx_rate=fx_rate,
                fx_rate_id=fx_rate_id,
                fx_source=fx_source,
                counterparty_id=line.counterparty_id,
                counterparty_account_id=line.counterparty_account_id,
                dimensions=tuple(sorted(line.dimensions.items())),
                memo=line.memo,
                quantity=line.quantity,
                quantity_unit=line.quantity_unit,
                line_role=line.line_role,
            )
        )
    _raise(errors)

    if settings.offset_account is not None:
        offset = settings.offset_account
        totals: dict[str, list[int]] = {}
        for b in built:
            pair = totals.setdefault(b.commodity, [0, 0])
            pair[0] += b.amount
            pair[1] += b.base_amount
        for commodity, (total, base_total) in totals.items():
            if total != 0 or base_total != 0:
                built.append(
                    BuiltLine(
                        line_no=0,
                        account_id=offset.id,
                        account_code=offset.code,
                        commodity=commodity,
                        amount=-total,
                        base_amount=-base_total,
                        line_role="opening_offset" if total != 0 else "rounding",
                    )
                )

    sums: dict[str, int] = {}
    base_sums: dict[str, int] = {}
    for b in built:
        sums[b.commodity] = sums.get(b.commodity, 0) + b.amount
        base_sums[b.commodity] = base_sums.get(b.commodity, 0) + b.base_amount
    unbalanced = [c for c, total in sums.items() if total != 0]
    foreign = [c for c in sums if c != base]

    if len(unbalanced) == 1:
        c = unbalanced[0]
        raise DomainError(
            "NOT_BALANCED",
            f"{c} 借贷不平衡，差额 {_fmt(sums[c], settings.scales[c])} {c}。",
            errors=[FieldError("lines", "NOT_BALANCED", "各币种的借方合计必须等于贷方合计")],
        )
    if len(unbalanced) >= 2:
        if not settings.allow_conversion:
            raise DomainError(
                "NOT_BALANCED",
                f"多个币种各自不平衡（{'、'.join(unbalanced)}）。如为结汇或换汇，请设置 allow_conversion。",
                errors=[FieldError("allow_conversion", "NOT_BALANCED", "跨币种分录需显式确认")],
            )
        trading = _require(settings.trading_account, "货币兑换（trading）")
        for c in unbalanced:
            built.append(
                BuiltLine(
                    line_no=0,
                    account_id=trading.id,
                    account_code=trading.code,
                    commodity=c,
                    amount=-sums[c],
                    base_amount=-base_sums[c],
                    line_role="trading",
                )
            )
        trading_net = -sum(base_sums[c] for c in unbalanced)
        if trading_net != 0 and settings.fx_realization == "immediate":
            fx_account = _require(settings.fx_gain_loss_account, "汇兑损益（fx_gain_loss）")
            carrier = next(c for c in unbalanced if c != base)
            built.append(
                BuiltLine(
                    line_no=0,
                    account_id=fx_account.id,
                    account_code=fx_account.code,
                    commodity=carrier,
                    amount=0,
                    base_amount=trading_net,
                    line_role="fx_realization",
                )
            )
            built.append(
                BuiltLine(
                    line_no=0,
                    account_id=trading.id,
                    account_code=trading.code,
                    commodity=carrier,
                    amount=0,
                    base_amount=-trading_net,
                    line_role="fx_realization",
                )
            )
    else:
        diff = sum(b.base_amount for b in built)
        if diff != 0:
            limit = settings.tolerance_per_line * len(built)
            if abs(diff) > limit or not foreign:
                raise DomainError(
                    "NOT_BALANCED",
                    f"本位币借贷差额 {_fmt(diff, base_scale)} {base}，超过尾差容差 {_fmt(limit, base_scale)}。",
                )
            rounding = _require(settings.rounding_account, "尾差（rounding）")
            built.append(
                BuiltLine(
                    line_no=0,
                    account_id=rounding.id,
                    account_code=rounding.code,
                    commodity=foreign[0],
                    amount=0,
                    base_amount=-diff,
                    line_role="rounding",
                )
            )
            warnings.append(_warning("ROUNDING_APPLIED", f"本位币尾差 {_fmt(-diff, base_scale)} 记入尾差科目"))

    numbered = tuple(replace(b, line_no=n) for n, b in enumerate(built, start=1))
    assert_balanced(numbered)
    return BuildResult(numbered, tuple(warnings), tuple(fx_info.values()))


def assert_balanced(lines: Sequence[BuiltLine]) -> None:
    sums: dict[str, int] = {}
    for line in lines:
        sums[line.commodity] = sums.get(line.commodity, 0) + line.amount
    if any(sums.values()) or sum(line.base_amount for line in lines) != 0 or len(lines) < 2:
        raise DomainError("NOT_BALANCED", "内部错误：生成的分录不平衡。")
    for line in lines:
        if line.amount == 0 and (line.base_amount == 0 or line.line_role not in BASE_ONLY_ROLES):
            raise DomainError("NOT_BALANCED", "内部错误：出现无效的零金额行。")


def reverse_lines(lines: Sequence[BuiltLine]) -> tuple[BuiltLine, ...]:
    """Mirror image of an entry; quantities flip with amounts so quantity sums stay correct."""
    return tuple(
        replace(
            line,
            amount=-line.amount,
            base_amount=-line.base_amount,
            quantity=-line.quantity if line.quantity is not None else None,
        )
        for line in lines
    )


def entry_hash_payload(
    *,
    book_id: str,
    seq: int,
    entry_id: str,
    number: str,
    transaction_id: str,
    kind: str,
    journal_code: str,
    effective_date: date,
    recorded_at: datetime,
    reverses_entry_id: str | None,
    template_id: str | None,
    fee_rule_ids: Sequence[str],
    lines: Sequence[BuiltLine],
) -> dict[str, Any]:
    return {
        "book_id": book_id,
        "seq": seq,
        "id": entry_id,
        "number": number,
        "transaction_id": transaction_id,
        "kind": kind,
        "journal_code": journal_code,
        "effective_date": effective_date,
        "recorded_at": recorded_at,
        "reverses_entry_id": reverses_entry_id,
        "template_id": template_id,
        "fee_rule_ids": list(fee_rule_ids),
        "lines": [
            {
                "line_no": line.line_no,
                "account_id": line.account_id,
                "commodity": line.commodity,
                "amount": line.amount,
                "base_amount": line.base_amount,
                "fx_rate": line.fx_rate,
                "quantity": line.quantity,
                "quantity_unit": line.quantity_unit,
                "counterparty_id": line.counterparty_id,
                "counterparty_account_id": line.counterparty_account_id,
                "dimensions": [list(pair) for pair in sorted(line.dimensions)],
                "memo": line.memo,
                "line_role": line.line_role,
            }
            for line in sorted(lines, key=lambda x: x.line_no)
        ],
    }


def _require(account: AccountInfo | None, label: str) -> AccountInfo:
    if account is None:
        raise DomainError("ACCOUNT_NOT_POSTABLE", f"账套缺少系统科目：{label}。")
    return account


def _raise(errors: list[FieldError]) -> None:
    if errors:
        first = errors[0]
        raise DomainError(
            first.code,
            first.message + ("" if len(errors) == 1 else f"（共 {len(errors)} 处问题）"),
            errors=errors,
        )


def _fmt(minor: int, scale: int) -> str:
    return f"{Decimal(minor).scaleb(-scale):,.{scale}f}"
