"""Business transaction types: input parsing, default accounts, building, descriptions (docs/14 §5, §9)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from bookkeeper.db.models import (
    Account,
    Book,
    Counterparty,
    CounterpartyAccount,
    DimensionValue,
    Transaction,
    TransactionType,
)
from bookkeeper.domain import business as rules
from bookkeeper.domain.errors import DomainError, FieldError, not_found
from bookkeeper.domain.fees import FeeRule, select_rule
from bookkeeper.domain.ledger import AccountInfo, LineInput, quantize_rate
from bookkeeper.domain.money import AmountError, format_amount, from_minor, parse_decimal, to_minor
from bookkeeper.services import accounts, fees, reference


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


ACCOUNT_REF = "科目编码（如 1012.01）、科目名称或 ID；省略时用账套默认科目"


class MoneyIn(_In):
    amount: str = Field(description='字符串小数，如 "51.50"；不接受浮点数', examples=["51.50"])
    commodity: str = Field(default="CNY", description="币种代码，默认 CNY；额度单位如 UCR")


class SaleIn(_In):
    """销售收入：渠道到账 = 毛额 − 手续费。"""

    gross: MoneyIn = Field(description="客户支付的毛额")
    fee: MoneyIn | None = Field(default=None, description="渠道实际扣除的手续费；省略时按手续费规则计算")
    channel: str | None = Field(
        default=None, description="销售渠道（代码、名称或别名，如 链动 / liandong）；省略时用往来方的默认渠道"
    )
    settle_account: str | None = Field(default=None, description="到账科目。" + ACCOUNT_REF)
    revenue_account: str | None = Field(default=None, description="收入科目。" + ACCOUNT_REF)
    fx_rate: str | None = Field(default=None, description="原币对本位币的实际汇率（如 9.5127）；省略时按当日参考汇率")


class SaleRefundIn(_In):
    """销售退款：退给客户的金额；渠道退回的手续费冲减手续费。"""

    amount: MoneyIn = Field(description="退给客户的金额")
    fee_refunded: MoneyIn | None = Field(
        default=None, description="渠道退回的手续费；省略时按列出 sale_refund 的手续费规则计算（无规则为 0）"
    )
    original: str | None = Field(default=None, description="原销售交易的编号（T2026-000123）或 ID；渠道与科目随原交易")
    channel: str | None = Field(default=None, description="渠道（代码、名称或别名）；有 original 时可省略")
    settle_account: str | None = Field(default=None, description="退款支付科目。" + ACCOUNT_REF)
    revenue_account: str | None = Field(default=None, description="冲减的收入科目。" + ACCOUNT_REF)
    fx_rate: str | None = Field(default=None, description="原币对本位币的实际汇率（如 9.5127）；省略时按当日参考汇率")


class CreditPurchaseIn(_In):
    """额度采购：成本 = 面值，另付的差额计手续费。面值与实付至少填一项。"""

    face: MoneyIn | None = Field(default=None, description="额度面值（计入成本）")
    total: MoneyIn | None = Field(default=None, description="实际支付总额；与面值的差额为手续费")
    credit_quantity: str | None = Field(default=None, description="获得的额度数量（UCR），含赠送")
    channel: str | None = Field(
        default=None, description="购买渠道（代码、名称或别名，如 链动、云猫、站内商店）；省略时用往来方的默认渠道"
    )
    counterparty_account: str | None = Field(default=None, description="上游站点下的账号 ID（往来方子账户）")
    pay_account: str | None = Field(default=None, description="付款科目。" + ACCOUNT_REF)
    cost_account: str | None = Field(default=None, description="成本科目，默认 5401.01 上游额度。" + ACCOUNT_REF)
    fx_rate: str | None = Field(default=None, description="原币对本位币的实际汇率（如 9.5127）；省略时按当日参考汇率")


class ExpenseIn(_In):
    """费用支出：额度采购以外的支出，按收支分类入账。"""

    amount: MoneyIn = Field(description="支出金额（不含手续费）")
    category: str = Field(description="收支分类：支出类明细科目的编码、名称或 ID，如 5401.04 服务器与网络")
    fee: MoneyIn | None = Field(
        default=None, description="另付的手续费；省略时按列出 expense 的手续费规则计算（无规则为 0）"
    )
    channel: str | None = Field(default=None, description="支付渠道（代码、名称或别名）")
    pay_account: str | None = Field(default=None, description="付款科目。" + ACCOUNT_REF)
    fx_rate: str | None = Field(default=None, description="原币对本位币的实际汇率（如 9.5127）；省略时按当日参考汇率")


class PurchaseRefundIn(_In):
    """采购退款：供应商退回的款项，冲减原成本或费用。"""

    amount: MoneyIn = Field(description="退回金额")
    original: str | None = Field(default=None, description="原采购 / 支出交易的编号或 ID；冲减科目随原交易")
    category: str | None = Field(default=None, description="冲减的科目；有 original 时可省略。" + ACCOUNT_REF)
    pay_account: str | None = Field(default=None, description="收款科目。" + ACCOUNT_REF)
    fx_rate: str | None = Field(default=None, description="原币对本位币的实际汇率（如 9.5127）；省略时按当日参考汇率")


class TransferIn(_In):
    """资金划转：同币种转移，或不同币种兑换（结汇、换汇）。"""

    from_account: str = Field(description="转出科目。" + ACCOUNT_REF)
    to_account: str = Field(description="转入科目；结汇时可与转出相同。" + ACCOUNT_REF)
    amount_out: MoneyIn = Field(description="转出金额")
    amount_in: MoneyIn | None = Field(default=None, description="转入金额；币种不同即为兑换，省略时 = 转出 − 手续费")
    fee: MoneyIn | None = Field(
        default=None,
        description="手续费（转出币种）；同币种且给了转入金额时 = 转出 − 转入；否则按列出 transfer 的手续费规则计算",
    )


EXAMPLES: dict[str, dict[str, Any]] = {
    "sale": {
        "type": "sale",
        "effective_date": "2026-10-18",
        "order_no": "LD20261018001",
        "inputs": {"gross": {"amount": "100.00", "commodity": "CNY"}, "channel": "liandong"},
    },
    "sale_refund": {
        "type": "sale_refund",
        "effective_date": "2026-10-19",
        "inputs": {"original": "T2026-000123", "amount": {"amount": "30.00", "commodity": "CNY"}},
    },
    "credit_purchase": {
        "type": "credit_purchase",
        "effective_date": "2026-10-18",
        "counterparty": "api.relay-a.example",
        "inputs": {
            "face": {"amount": "50.00", "commodity": "CNY"},
            "total": {"amount": "51.50", "commodity": "CNY"},
            "credit_quantity": "50",
            "channel": "direct",
        },
    },
    "expense": {
        "type": "expense",
        "effective_date": "2026-10-18",
        "counterparty": "Vultr",
        "inputs": {"amount": {"amount": "12.00", "commodity": "USD"}, "category": "5401.04"},
    },
    "purchase_refund": {
        "type": "purchase_refund",
        "effective_date": "2026-10-20",
        "inputs": {"original": "T2026-000124", "amount": {"amount": "10.00", "commodity": "CNY"}},
    },
    "transfer": {
        "type": "transfer",
        "effective_date": "2026-10-18",
        "inputs": {
            "from_account": "1012.01",
            "to_account": "1012.01",
            "amount_out": {"amount": "100.00", "commodity": "GBP"},
            "amount_in": {"amount": "951.27", "commodity": "CNY"},
        },
    },
}


INPUT_MODELS: dict[str, type[_In]] = {
    "sale": SaleIn,
    "sale_refund": SaleRefundIn,
    "credit_purchase": CreditPurchaseIn,
    "expense": ExpenseIn,
    "purchase_refund": PurchaseRefundIn,
    "transfer": TransferIn,
}
ACCOUNT_FIELDS = (
    "settle_account",
    "revenue_account",
    "pay_account",
    "cost_account",
    "category",
    "from_account",
    "to_account",
)
MONEY_FIELDS = ("gross", "fee", "amount", "fee_refunded", "face", "total", "amount_out", "amount_in")
DEFAULT_ROLES = {
    "settle_account": "funds",
    "pay_account": "funds",
    "revenue_account": "revenue_operating",
    "cost_account": "cost_operating",
}


def input_schema(type_code: str) -> dict[str, Any]:
    return INPUT_MODELS[type_code].model_json_schema()


def catalogue(session: Session, book_id: str) -> list[dict[str, Any]]:
    """Transaction types with how to enter them: input schema, example, default accounts."""
    from bookkeeper.domain import chart

    active = dict(
        session.execute(
            select(TransactionType.code, TransactionType.is_active).where(TransactionType.book_id == book_id)
        ).all()
    )
    defaults = {}
    for field_name, role in DEFAULT_ROLES.items():
        acc = accounts.default_for_role(session, book_id, role)
        defaults[field_name] = f"{acc.code} {acc.name}" if acc else None
    items = []
    for t in chart.TRANSACTION_TYPES:
        if t.code in INPUT_MODELS:
            mode, schema = "inputs", input_schema(t.code)
            used = INPUT_MODELS[t.code].model_fields
            account_defaults = {k: v for k, v in defaults.items() if k in used}
        elif t.code in chart.LINE_INPUT_TYPES:
            mode, schema, account_defaults = "lines", None, {}
        else:
            continue  # system-generated types are not entered by clients
        items.append(
            {
                "code": t.code,
                "name": t.name,
                "category": t.category,
                "description": t.description,
                "input_mode": mode,
                "is_active": active.get(t.code, False),
                "input_schema": schema,
                "default_accounts": account_defaults,
                "fee_rules_apply": t.code in fees.FEE_TYPES,
                "example": EXAMPLES.get(t.code),
            }
        )
    return items


def _account(session: Session, book_id: str, ref: str, path: str, errors: list[FieldError]) -> Account | None:
    item = (
        session.execute(
            select(Account).where(
                Account.book_id == book_id, (Account.id == ref) | (Account.code == ref) | (Account.name == ref)
            )
        )
        .scalars()
        .all()
    )
    if len(item) == 1:
        return item[0]
    errors.append(
        FieldError(path, "INPUT_INVALID", f"科目 {ref} 不存在" if not item else f"科目名 {ref} 对应多个科目，请用编码")
    )
    return None


def _original(session: Session, book_id: str, ref: str) -> tuple[Transaction, str]:
    row = session.execute(
        select(Transaction, TransactionType.code)
        .join(TransactionType, TransactionType.id == Transaction.transaction_type_id)
        .where(Transaction.book_id == book_id, (Transaction.id == ref) | (Transaction.number == ref))
    ).first()
    if row is None:
        raise not_found("原交易", ref)
    return row[0], row[1]


CHANNEL_TYPES = ("sale", "credit_purchase", "expense")


def normalise(
    session: Session, book: Book, type_code: str, raw: dict[str, Any], header: dict[str, Any]
) -> dict[str, Any]:
    """Validate and resolve inputs → JSON stored in ``transactions.inputs`` (ids, minor units)."""
    try:
        model = INPUT_MODELS[type_code].model_validate(raw)
    except ValidationError as exc:
        problems = [
            FieldError("inputs." + ".".join(str(p) for p in e["loc"]), "INPUT_INVALID", e["msg"]) for e in exc.errors()
        ]
        raise DomainError(
            "INPUT_INVALID",
            f"输入有 {len(problems)} 处问题：{problems[0].path} {problems[0].message}。",
            errors=problems,
            next_action={"operation": "meta_transaction_types", "hint": "查看该类型的 input_schema"},
        ) from exc
    data = model.model_dump(exclude_none=True)
    scales = reference.active_scales(session)
    errors: list[FieldError] = []
    result: dict[str, Any] = {}
    original_inputs: dict[str, Any] = {}
    if data.get("original"):
        original, original_type = _original(session, book.id, data["original"])
        expected = {"sale_refund": "sale", "purchase_refund": ("credit_purchase", "expense")}[type_code]
        if original_type not in (expected if isinstance(expected, tuple) else (expected,)):
            errors.append(
                FieldError(
                    "inputs.original",
                    "INPUT_INVALID",
                    f"原交易 {original.number} 类型为 {original_type}，不能作为该退款的原交易",
                )
            )
        elif original.status != "posted":
            errors.append(FieldError("inputs.original", "INPUT_INVALID", f"原交易 {original.number} 已删除"))
        result["original_id"] = original.id
        original_inputs = original.inputs
        header["counterparty_id"] = header.get("counterparty_id") or original.counterparty_id
    for key, value in data.items():
        if key in MONEY_FIELDS:
            commodity = value["commodity"]
            if commodity not in scales:
                errors.append(
                    FieldError(f"inputs.{key}.commodity", "INPUT_INVALID", reference.unknown_commodity(commodity))
                )
                continue
            try:
                result[key] = {"minor": to_minor(value["amount"], scales[commodity]), "commodity": commodity}
            except AmountError as exc:
                errors.append(FieldError(f"inputs.{key}.amount", "INPUT_INVALID", str(exc)))
        elif key in ACCOUNT_FIELDS:
            acc = _account(session, book.id, value, f"inputs.{key}", errors)
            if acc is not None:
                result[key] = acc.id
        elif key == "channel":
            try:
                result["channel_id"] = reference.resolve_dimensions(session, book.id, {"channel": value})["channel"]
            except DomainError as exc:
                errors.append(FieldError("inputs.channel", "INPUT_INVALID", exc.detail))
        elif key in ("credit_quantity", "fx_rate"):
            try:
                number = parse_decimal(value)
                if key == "fx_rate" and number <= 0:
                    raise AmountError("汇率必须大于 0")
                result[key] = str(number)
            except AmountError as exc:
                errors.append(FieldError(f"inputs.{key}", "INPUT_INVALID", str(exc)))
        elif key == "counterparty_account":
            cpa = session.get(CounterpartyAccount, value)
            if cpa is None or cpa.book_id != book.id:
                errors.append(FieldError("inputs.counterparty_account", "INPUT_INVALID", "往来方子账户不存在"))
            else:
                result["counterparty_account_id"] = cpa.id
    if errors:
        raise DomainError("INPUT_INVALID", f"输入有 {len(errors)} 处问题：{errors[0].message}。", errors=errors)
    if "channel_id" not in result and type_code in CHANNEL_TYPES and header.get("counterparty_id"):
        cp = session.get(Counterparty, header["counterparty_id"])
        channel = reference.counterparty_defaults(session, cp)["channel"] if cp else None
        if channel:  # the counterparty's usual channel (relay-b.example → 链动) when the entry does not name one
            result["channel_id"] = channel["id"]
            header.setdefault("defaults_applied", {})["channel"] = channel["code"]
    # refunds inherit channel and accounts from the original transaction
    if type_code == "sale_refund":
        result.setdefault("channel_id", original_inputs.get("channel_id"))
        result.setdefault("settle_account", original_inputs.get("settle_account"))
        result.setdefault("revenue_account", original_inputs.get("revenue_account"))
    if type_code == "purchase_refund":
        result.setdefault("category", original_inputs.get("category") or original_inputs.get("cost_account"))
        result.setdefault("pay_account", original_inputs.get("pay_account"))
        if not result.get("category"):
            raise DomainError(
                "INPUT_INVALID",
                "采购退款需指定 original 或 category。",
                errors=[FieldError("inputs.category", "INPUT_INVALID", "缺少退回的科目")],
            )
    return {k: v for k, v in result.items() if v is not None}


def raw_inputs(session: Session, stored: dict[str, Any]) -> dict[str, Any]:
    """Inverse of :func:`normalise` — used to edit an existing transaction."""
    scales = reference.commodity_scales(session)
    raw: dict[str, Any] = {}
    for key, value in stored.items():
        if key in MONEY_FIELDS:
            raw[key] = {
                "amount": str(from_minor(value["minor"], scales[value["commodity"]])),
                "commodity": value["commodity"],
            }
        elif key in ACCOUNT_FIELDS or key in ("credit_quantity", "fx_rate"):
            raw[key] = value
        elif key in ("channel_id", "original_id", "counterparty_account_id"):
            raw[key.removesuffix("_id")] = value
    return raw


def _check_refund(session: Session, txn: Transaction, computed: dict[str, Any]) -> None:
    """Cumulative posted refunds of one original may not exceed what it received or paid."""
    original = session.get(Transaction, txn.inputs["original_id"])
    assert original is not None
    limit = original.computed.get("gross", original.computed.get("total"))
    if limit is None:
        return
    if original.computed.get("commodity") != computed["commodity"]:
        raise DomainError(
            "INPUT_INVALID",
            f"退款币种须与原交易 {original.number} 一致（{original.computed.get('commodity')}）。",
            errors=[FieldError("inputs.amount.commodity", "INPUT_INVALID", "币种与原交易不一致")],
        )
    others = session.execute(
        select(Transaction.computed).where(
            Transaction.book_id == txn.book_id,
            Transaction.status == "posted",
            Transaction.id != txn.id,
            Transaction.inputs["original_id"].astext == original.id,
        )
    ).scalars()
    refunded = sum(int(c.get("amount", 0)) for c in others)
    if refunded + computed["amount"] > limit:
        scale = reference.commodity_scales(session)[computed["commodity"]]

        def show(minor: int) -> str:
            return format_amount(minor, scale, None, computed["commodity"])

        raise DomainError(
            "INPUT_INVALID",
            f"累计退款将超过原交易 {original.number} 的金额：已退 {show(refunded)}，"
            f"本次 {show(computed['amount'])}，原交易 {show(limit)}。",
            extra={"refundable": limit - refunded},
            errors=[FieldError("inputs.amount", "INPUT_INVALID", "累计退款超过原交易金额")],
        )


def _implied_rate(
    session: Session,
    book: Book,
    txn: Transaction,
    lines: list[LineInput],
    computed: dict[str, Any],
    warnings: list[dict[str, str]],
) -> list[LineInput]:
    """Exchange into the base currency without a reference rate for that day: value the foreign
    legs at the rate actually obtained, so the exchange can still be posted (with a warning)."""
    out_c, in_c = computed["out_commodity"], computed["in_commodity"]
    if in_c != book.base_commodity or reference.QuoteProvider(session, book, txn.effective_date)(out_c) is not None:
        return lines
    scales = reference.commodity_scales(session)
    converted = computed["amount_out"] - computed["fee"]
    rate = quantize_rate(from_minor(computed["amount_in"], scales[in_c]) / from_minor(converted, scales[out_c]))
    computed["implied_rate"] = format(rate.normalize(), "f")
    warnings.append(
        {
            "code": "FX_IMPLIED_RATE",
            "path": "inputs.amount_in",
            "message": f"未找到 {txn.effective_date} 的 {out_c}→{in_c} 参考汇率，"
            f"按本笔实际兑换汇率 {computed['implied_rate']} 折算",
        }
    )
    return [replace(line, fx_rate=rate) if line.commodity == out_c else line for line in lines]


@dataclass
class Prepared:
    lines: list[LineInput]
    computed: dict[str, Any]
    warnings: list[dict[str, str]] = field(default_factory=list)
    fee_rule: FeeRule | None = None
    allow_conversion: bool = False
    is_estimate: bool = False


def _info(session: Session, book_id: str, account_id: str | None, role: str | None = None) -> AccountInfo:
    acc = session.get(Account, account_id) if account_id else accounts.default_for_role(session, book_id, role or "")
    if acc is None:
        raise DomainError("ACCOUNT_NOT_POSTABLE", f"账套缺少默认科目（角色 {role}）。")
    return accounts.to_info(acc)


def prepare(session: Session, book: Book, txn: Transaction, type_code: str) -> Prepared:
    stored = txn.inputs
    builder_inputs: dict[str, Any] = {}
    for key, value in stored.items():
        if key in MONEY_FIELDS:
            builder_inputs[key] = rules.Amount(value["minor"], value["commodity"])
    for key in ACCOUNT_FIELDS:
        if key in stored or key in DEFAULT_ROLES:
            if key in ("category", "from_account", "to_account") and key not in stored:
                continue
            builder_inputs[key] = _info(session, book.id, stored.get(key), DEFAULT_ROLES.get(key))
    if "credit_quantity" in stored:
        builder_inputs["credit_quantity"] = Decimal(stored["credit_quantity"])
    channel = stored.get("channel_id")
    fee_account = _info(session, book.id, None, "expense_finance_fee")

    def fee_rule(commodity: str) -> FeeRule | None:
        return select_rule(
            fees.active_rules(session, book.id), type_code, channel, txn.counterparty_id, txn.effective_date, commodity
        )

    ctx = rules.Context(
        type_code=type_code,
        channel=channel,
        counterparty=txn.counterparty_id,
        on=txn.effective_date,
        fee_rule=fee_rule,
        fee_account=fee_account,
        rounding_mode=book.rounding_mode,
    )
    built = rules.BUILDERS[type_code](builder_inputs, ctx)
    lines = built.lines
    if stored.get("counterparty_account_id"):
        lines = [replace(line, counterparty_account_id=stored["counterparty_account_id"]) for line in lines]
    computed = dict(built.computed)
    if stored.get("fx_rate"):  # actual rate given: value every foreign-currency line with it
        rate = quantize_rate(Decimal(stored["fx_rate"]))
        lines = [replace(line, fx_rate=rate) if line.commodity != book.base_commodity else line for line in lines]
        computed["fx_rate"] = stored["fx_rate"]
    if type_code == "transfer" and built.allow_conversion:
        lines = _implied_rate(session, book, txn, lines, computed, built.warnings)
    if stored.get("original_id"):
        _check_refund(session, txn, computed)
    amount_key = {"sale": "gross", "credit_purchase": "total", "expense": "total", "transfer": "amount_out"}.get(
        type_code, "amount"
    )
    commodity = computed.get("commodity") or computed["out_commodity"]
    item = reference.commodities_by_code(session)[commodity]
    computed["headline"] = {
        "minor": computed[amount_key],
        "commodity": commodity,
        "display": format_amount(computed[amount_key], item.scale, item.symbol, commodity),
    }
    if built.fee_rule:
        computed["fee_rule"] = {"id": built.fee_rule.id, "code": built.fee_rule.code, "version": built.fee_rule.version}
    return Prepared(lines, computed, built.warnings, built.fee_rule, built.allow_conversion, built.is_estimate)


def default_description(
    session: Session, book: Book, txn: Transaction, type_code: str, computed: dict[str, Any]
) -> str:
    stored = txn.inputs
    channel_value = session.get(DimensionValue, stored["channel_id"]) if stored.get("channel_id") else None
    channel = channel_value.name if channel_value else None
    known_channel = channel if channel_value is not None and channel_value.code != "other" else None
    party = session.get(Counterparty, txn.counterparty_id).name if txn.counterparty_id else None  # type: ignore[union-attr]
    suffix = f" · {txn.order_no}" if txn.order_no else ""
    symbols = {c: x.symbol for c, x in reference.commodities_by_code(session).items()}
    scales = reference.commodity_scales(session)

    def money(minor: int, commodity: str) -> str:
        text = format_amount(minor, scales[commodity], symbols.get(commodity), commodity)
        return text.replace(".00", "") if text.endswith(".00") else text

    if type_code == "sale":
        return f"{channel} · API 额度销售{suffix}"
    if type_code == "sale_refund":
        return f"{channel or party or '客户'} · 销售退款{suffix}"
    if type_code == "credit_purchase":
        text = f"{party} · 额度采购 · 面值 {money(computed['face'], computed['commodity'])}"
        return text + (f" · {known_channel}" if known_channel else "")
    if type_code == "expense":
        category = session.get(Account, stored["category"])
        return f"{party or channel or '未指定往来方'} · {category.name if category else '费用'}"
    if type_code == "purchase_refund":
        return f"{party or '供应商'} · 采购退款{suffix}"
    if type_code == "transfer":
        source = session.get(Account, stored["from_account"])
        target = session.get(Account, stored["to_account"])
        out_c, in_c = computed["out_commodity"], computed["in_commodity"]
        if out_c != in_c:
            label = "结汇" if in_c == book.base_commodity else "换汇"
            return f"{label} · {out_c} → {in_c}"
        return f"{source.name if source else ''} → {target.name if target else ''}"
    return type_code


def explain(session: Session, book: Book, txn: Transaction, type_code: str) -> dict[str, Any]:
    """Readable account of how the inputs became lines: resolved inputs, fee rule choice, results."""
    stored = txn.inputs
    commodities = reference.commodities_by_code(session)
    readable: dict[str, Any] = {}
    for key, value in stored.items():
        if key in MONEY_FIELDS:
            c = commodities[value["commodity"]]
            readable[key] = format_amount(value["minor"], c.scale, c.symbol, c.code)
        elif key in ACCOUNT_FIELDS:
            acc = session.get(Account, value)
            readable[key] = f"{acc.code} {acc.name}" if acc else value
        elif key == "channel_id":
            dv = session.get(DimensionValue, value)
            readable["channel"] = dv.name if dv else value
        elif key == "original_id":
            original = session.get(Transaction, value)
            readable["original"] = f"{original.number} {original.description}" if original else value
        elif key != "journal_code":
            readable[key] = value
    computed = txn.computed
    result: dict[str, Any] = {
        "type": type_code,
        "inputs": readable,
        "computed": {k: v for k, v in computed.items() if k not in ("warnings", "fx")},
        "warnings": computed.get("warnings", []),
        "fx": computed.get("fx", []),
    }
    if type_code in fees.FEE_TYPES:
        commodity = computed.get("commodity") or book.base_commodity
        rules_now = fees.active_rules(session, book.id)
        candidates = [
            {
                "rule": f"{r.code}@{r.version}",
                "method": r.method,
                "priority": r.priority,
                "reason": r.mismatch(
                    type_code, stored.get("channel_id"), txn.counterparty_id, txn.effective_date, commodity
                )
                or "命中",
            }
            for r in sorted(rules_now, key=lambda r: (r.code, r.version))
        ]
        used = computed.get("fee_rule")
        actual_given = "fee" in stored or ("face" in stored and "total" in stored)
        result["fee"] = {
            "rule": f"{used['code']}@{used['version']}" if used else None,
            "fee": computed.get("fee"),
            "expected": computed.get("fee_expected"),
            "source": "actual" if actual_given else ("rule" if used else "none"),
            "candidates": candidates,
        }
    return result
