"""Built-in business transaction types → journal line inputs (docs/14 §5).

Each builder takes resolved inputs and returns lines plus a summary of computed amounts.
Fee handling per type: sale = deducted from gross; credit_purchase / expense = paid on top.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from bookkeeper.domain.errors import DomainError, FieldError
from bookkeeper.domain.fees import FeeRule, fee_on, split_total
from bookkeeper.domain.ledger import AccountInfo, LineInput

BUSINESS_TYPES = ("sale", "sale_refund", "credit_purchase", "expense", "purchase_refund", "transfer")
FEE_DEVIATION_RATIO = Decimal("0.005")


@dataclass(frozen=True)
class Amount:
    minor: int
    commodity: str


@dataclass(frozen=True)
class Context:
    """Everything a builder needs besides the inputs."""

    type_code: str
    channel: str | None
    counterparty: str | None
    on: Any
    fee_rule: Callable[[str], FeeRule | None]  # commodity → applicable rule (loaded lazily)
    fee_account: AccountInfo
    rounding_mode: str = "half_up"


@dataclass
class Built:
    lines: list[LineInput]
    computed: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)
    fee_rule: FeeRule | None = None
    allow_conversion: bool = False
    is_estimate: bool = False


def _line(account: AccountInfo, side: str, amount: Amount, role: str, ctx: Context, **kw: Any) -> LineInput:
    dims = kw.pop("dimensions", None)
    if dims is None:
        dims = {"channel": ctx.channel} if ctx.channel else {}
    return LineInput(
        account=account,
        side=side,
        amount_minor=amount.minor,
        commodity=amount.commodity,
        counterparty_id=kw.pop("counterparty_id", ctx.counterparty),
        dimensions=dims,
        line_role=role,
        **kw,
    )


def _positive(
    value: Amount | None, path: str, label: str, errors: list[FieldError], *, allow_zero: bool = False
) -> None:
    if value is not None and (value.minor < 0 or (value.minor == 0 and not allow_zero)):
        errors.append(FieldError(path, "INPUT_INVALID", f"{label}必须大于 0"))


def _raise(errors: list[FieldError]) -> None:
    if errors:
        raise DomainError("INPUT_INVALID", errors[0].message + "。", errors=errors)


def _same(a: Amount, b: Amount, path: str, errors: list[FieldError]) -> None:
    if a.commodity != b.commodity:
        errors.append(FieldError(path, "INPUT_INVALID", f"币种不一致：{a.commodity} 与 {b.commodity}"))


def _deviation(actual: int, expected: int, base: int) -> bool:
    return abs(actual - expected) > max(1, int(Decimal(abs(base)) * FEE_DEVIATION_RATIO))


def _fee(
    built: Built, actual: Amount | None, base: Amount, ctx: Context, path: str, label: str = "手续费"
) -> tuple[int, int | None]:
    """(fee, expected): the actual fee when given (warning if it deviates from the rule), else the rule's."""
    rule = ctx.fee_rule(base.commodity)
    built.fee_rule = rule
    expected = fee_on(rule, base.minor, ctx.rounding_mode) if rule else None
    if actual is not None:
        if expected is not None and _deviation(actual.minor, expected, base.minor):
            built.warnings.append(
                {
                    "code": "FEE_DEVIATION",
                    "path": path,
                    "message": f"实际{label} {actual.minor} 与规则 {rule.code if rule else ''} "
                    f"计算值 {expected} 不一致",
                }
            )
        return actual.minor, expected
    built.is_estimate = bool(rule and rule.is_estimate)
    return expected or 0, expected


def sale(inputs: dict[str, Any], ctx: Context) -> Built:
    """Dr funds (net) / Dr fee / Cr revenue (gross)."""
    gross: Amount = inputs["gross"]
    actual: Amount | None = inputs.get("fee")
    errors: list[FieldError] = []
    _positive(gross, "inputs.gross", "毛额", errors)
    _positive(actual, "inputs.fee", "手续费", errors, allow_zero=True)
    if actual is not None:
        _same(gross, actual, "inputs.fee", errors)
    if not ctx.channel:
        errors.append(FieldError("inputs.channel", "INPUT_INVALID", "销售收入必须指定渠道（或给往来方设置默认渠道）"))
    _raise(errors)
    rule = ctx.fee_rule(gross.commodity)
    built = Built(lines=[], fee_rule=rule)
    expected = fee_on(rule, gross.minor, ctx.rounding_mode) if rule else None
    if actual is not None:
        fee = actual.minor
        if expected is not None and _deviation(fee, expected, gross.minor):
            built.warnings.append(
                {
                    "code": "FEE_DEVIATION",
                    "path": "inputs.fee",
                    "message": f"实际手续费 {fee} 与规则 {rule.code if rule else ''} 计算值 {expected} 不一致",
                }
            )
    else:
        fee = expected or 0
        built.is_estimate = bool(rule and rule.is_estimate)
    if fee > gross.minor:
        _raise([FieldError("inputs.fee", "INPUT_INVALID", "手续费不能大于毛额")])
    net = Amount(gross.minor - fee, gross.commodity)
    built.lines.append(_line(inputs["settle_account"], "debit", net, "net", ctx)) if net.minor else None
    if fee:
        built.lines.append(_line(ctx.fee_account, "debit", Amount(fee, gross.commodity), "fee", ctx))
    built.lines.append(_line(inputs["revenue_account"], "credit", gross, "gross", ctx))
    built.computed = {
        "gross": gross.minor,
        "fee": fee,
        "net": net.minor,
        "commodity": gross.commodity,
        "fee_expected": expected,
    }
    return built


def sale_refund(inputs: dict[str, Any], ctx: Context) -> Built:
    """Dr revenue (amount) / Cr fee (refunded part) / Cr funds (rest)."""
    amount: Amount = inputs["amount"]
    fee_back: Amount | None = inputs.get("fee_refunded")
    errors: list[FieldError] = []
    _positive(amount, "inputs.amount", "退款金额", errors)
    _positive(fee_back, "inputs.fee_refunded", "退回手续费", errors, allow_zero=True)
    if fee_back is not None:
        _same(amount, fee_back, "inputs.fee_refunded", errors)
        if fee_back.minor > amount.minor:
            errors.append(FieldError("inputs.fee_refunded", "INPUT_INVALID", "退回手续费不能大于退款金额"))
    _raise(errors)
    built = Built(lines=[])
    fee, expected = _fee(built, fee_back, amount, ctx, "inputs.fee_refunded", "退回手续费")
    if fee > amount.minor:
        _raise([FieldError("inputs.fee_refunded", "INPUT_INVALID", "退回手续费不能大于退款金额")])
    built.lines.append(_line(inputs["revenue_account"], "debit", amount, "gross", ctx))
    if fee:
        built.lines.append(_line(ctx.fee_account, "credit", Amount(fee, amount.commodity), "fee", ctx))
    if amount.minor - fee:
        built.lines.append(
            _line(inputs["settle_account"], "credit", Amount(amount.minor - fee, amount.commodity), "net", ctx)
        )
    built.computed = {
        "amount": amount.minor,
        "fee_refunded": fee,
        "fee": fee,
        "fee_expected": expected,
        "commodity": amount.commodity,
    }
    return built


def credit_purchase(inputs: dict[str, Any], ctx: Context) -> Built:
    """Dr upstream credits (face, with credit quantity) / Dr fee / Cr funds (total paid)."""
    face: Amount | None = inputs.get("face")
    total: Amount | None = inputs.get("total")
    errors: list[FieldError] = []
    if face is None and total is None:
        errors.append(FieldError("inputs.face", "INPUT_INVALID", "面值与实付至少填写一项"))
    _positive(face, "inputs.face", "面值", errors)
    _positive(total, "inputs.total", "实付", errors)
    if face and total:
        _same(face, total, "inputs.total", errors)
        if total.minor < face.minor:
            errors.append(FieldError("inputs.total", "INPUT_INVALID", "实付不能小于面值；赠送额度请填写额度数量"))
    if not ctx.counterparty:
        errors.append(FieldError("counterparty", "INPUT_INVALID", "额度采购必须指定上游站点（往来方）"))
    if not ctx.channel:
        errors.append(FieldError("inputs.channel", "INPUT_INVALID", "额度采购必须指定渠道（或给往来方设置默认渠道）"))
    _raise(errors)
    commodity = (face or total).commodity  # type: ignore[union-attr]
    rule = ctx.fee_rule(commodity)
    built = Built(lines=[], fee_rule=rule)
    if face and total:
        face_minor, fee = face.minor, total.minor - face.minor
        expected = fee_on(rule, face.minor, ctx.rounding_mode) if rule else None
        if expected is not None and _deviation(fee, expected, face.minor):
            built.warnings.append(
                {
                    "code": "FEE_DEVIATION",
                    "path": "inputs.total",
                    "message": f"实付差额 {fee} 与规则计算的手续费 {expected} 不一致",
                }
            )
    elif face:
        face_minor = face.minor
        fee = fee_on(rule, face.minor, ctx.rounding_mode) if rule else 0
        built.is_estimate = bool(rule and rule.is_estimate)
    else:
        assert total is not None
        face_minor, fee = split_total(rule, total.minor, ctx.rounding_mode) if rule else (total.minor, 0)
        built.is_estimate = bool(rule and rule.is_estimate)
    quantity: Decimal | None = inputs.get("credit_quantity")
    built.lines.append(
        _line(
            inputs["cost_account"],
            "debit",
            Amount(face_minor, commodity),
            "cost",
            ctx,
            quantity=quantity,
            quantity_unit="UCR" if quantity is not None else None,
        )
    )
    if fee:
        built.lines.append(_line(ctx.fee_account, "debit", Amount(fee, commodity), "fee", ctx))
    built.lines.append(_line(inputs["pay_account"], "credit", Amount(face_minor + fee, commodity), "pay", ctx))
    built.computed = {
        "face": face_minor,
        "fee": fee,
        "total": face_minor + fee,
        "commodity": commodity,
        "credit_quantity": str(quantity) if quantity is not None else None,
    }
    return built


def expense(inputs: dict[str, Any], ctx: Context) -> Built:
    """Dr category (amount) / Dr fee / Cr funds."""
    amount: Amount = inputs["amount"]
    fee_amount: Amount | None = inputs.get("fee")
    errors: list[FieldError] = []
    _positive(amount, "inputs.amount", "金额", errors)
    _positive(fee_amount, "inputs.fee", "手续费", errors, allow_zero=True)
    if fee_amount is not None:
        _same(amount, fee_amount, "inputs.fee", errors)
    category: AccountInfo = inputs["category"]
    if category.classification != "expense":
        errors.append(FieldError("inputs.category", "INPUT_INVALID", f"{category.code} 不是支出分类"))
    _raise(errors)
    built = Built(lines=[_line(category, "debit", amount, "cost", ctx)])
    fee, expected = _fee(built, fee_amount, amount, ctx, "inputs.fee")
    if fee:
        built.lines.append(_line(ctx.fee_account, "debit", Amount(fee, amount.commodity), "fee", ctx))
    built.lines.append(_line(inputs["pay_account"], "credit", Amount(amount.minor + fee, amount.commodity), "pay", ctx))
    built.computed = {
        "amount": amount.minor,
        "fee": fee,
        "fee_expected": expected,
        "total": amount.minor + fee,
        "commodity": amount.commodity,
    }
    return built


def purchase_refund(inputs: dict[str, Any], ctx: Context) -> Built:
    """Dr funds / Cr the original cost or expense account."""
    amount: Amount = inputs["amount"]
    errors: list[FieldError] = []
    _positive(amount, "inputs.amount", "退款金额", errors)
    _raise(errors)
    lines = [
        _line(inputs["pay_account"], "debit", amount, "pay", ctx),
        _line(inputs["category"], "credit", amount, "cost", ctx),
    ]
    return Built(lines=lines, computed={"amount": amount.minor, "commodity": amount.commodity})


def transfer(inputs: dict[str, Any], ctx: Context) -> Built:
    """Cr from (amount_out) / Dr to (amount_in) / Dr fee; different commodities = exchange."""
    out: Amount = inputs["amount_out"]
    received: Amount | None = inputs.get("amount_in")
    fee_amount: Amount | None = inputs.get("fee")
    errors: list[FieldError] = []
    _positive(out, "inputs.amount_out", "转出金额", errors)
    _positive(received, "inputs.amount_in", "转入金额", errors)
    _positive(fee_amount, "inputs.fee", "手续费", errors, allow_zero=True)
    if fee_amount is not None:
        _same(out, fee_amount, "inputs.fee", errors)
    _raise(errors)
    built = Built(lines=[])
    if fee_amount is None and received is not None and received.commodity == out.commodity:
        # same commodity, both amounts given: the difference is the fee
        fee_amount = Amount(out.minor - received.minor, out.commodity)
        if fee_amount.minor < 0:
            _raise([FieldError("inputs.amount_in", "INPUT_INVALID", "同币种划转：转入不能大于转出")])
    fee, expected = _fee(built, fee_amount, out, ctx, "inputs.fee")
    if received is None:
        received = Amount(out.minor - fee, out.commodity)
        if received.minor <= 0:
            errors.append(FieldError("inputs.fee", "INPUT_INVALID", "手续费不能大于等于转出金额"))
    exchange = received.commodity != out.commodity
    if not exchange and received.minor + fee != out.minor:
        errors.append(FieldError("inputs.amount_in", "INPUT_INVALID", "同币种划转：转入 + 手续费必须等于转出"))
    if inputs["from_account"].id == inputs["to_account"].id and not exchange:
        errors.append(FieldError("inputs.to_account", "INPUT_INVALID", "同币种划转的转出、转入科目不能相同"))
    _raise(errors)
    no_dims: dict[str, str] = {}
    built.lines = [
        _line(inputs["from_account"], "credit", out, "out", ctx, dimensions=no_dims),
        _line(inputs["to_account"], "debit", received, "in", ctx, dimensions=no_dims),
    ]
    if fee:
        built.lines.append(_line(ctx.fee_account, "debit", Amount(fee, out.commodity), "fee", ctx, dimensions=no_dims))
    built.allow_conversion = exchange
    built.computed = {
        "amount_out": out.minor,
        "out_commodity": out.commodity,
        "amount_in": received.minor,
        "in_commodity": received.commodity,
        "fee": fee,
        "fee_expected": expected,
    }
    return built


BUILDERS: dict[str, Callable[[dict[str, Any], Context], Built]] = {
    "sale": sale,
    "sale_refund": sale_refund,
    "credit_purchase": credit_purchase,
    "expense": expense,
    "purchase_refund": purchase_refund,
    "transfer": transfer,
}
