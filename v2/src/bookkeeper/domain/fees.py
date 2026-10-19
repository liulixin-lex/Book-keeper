"""Fee rules: selection and computation.

fee = round(base × rate) + fixed, then clamped to [min, max]. Either part may be absent, which
covers percentage (3%), fixed (¥1 per order) and combined (2.9% + $0.30) rules. Whether the fee
is deducted from a receipt or paid on top is decided by the transaction type, not the rule.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from bookkeeper.domain.errors import DomainError
from bookkeeper.domain.money import round_minor

FEE_TYPES = ("sale", "credit_purchase", "expense", "transfer", "sale_refund")
# A rule without transaction types covers the two fee-bearing types it always did; expenses, transfers
# and refunds only use rules that list them, so adding those types never changes existing rules.
DEFAULT_FEE_TYPES = ("sale", "credit_purchase")


@dataclass(frozen=True)
class FeeRule:
    id: str
    code: str
    version: int
    rate: Decimal | None = None
    fixed_minor: int | None = None
    min_minor: int | None = None
    max_minor: int | None = None
    commodity: str | None = None  # required when fixed/min/max are set: they are in its minor units
    transaction_types: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    counterparties: tuple[str, ...] = ()
    priority: int = 0
    valid_from: date = date.min
    valid_to: date | None = None
    is_estimate: bool = False

    @property
    def method(self) -> str:
        if self.rate is not None and self.fixed_minor:
            return "percentage_plus_fixed"
        return "percentage" if self.rate is not None else "fixed"

    @property
    def specificity(self) -> int:
        return sum(1 for scope in (self.transaction_types, self.channels, self.counterparties) if scope)

    def mismatch(
        self, type_code: str, channel: str | None, counterparty: str | None, on: date, commodity: str | None = None
    ) -> str | None:
        """Why the rule does not apply (None = it applies)."""
        if on < self.valid_from:
            return f"{self.valid_from} 起生效"
        if self.valid_to is not None and on > self.valid_to:
            return f"已于 {self.valid_to} 失效"
        if self.commodity and commodity and self.commodity != commodity:
            return f"只适用于 {self.commodity}"
        if self.transaction_types and type_code not in self.transaction_types:
            return "交易类型不在范围内"
        if not self.transaction_types and type_code not in DEFAULT_FEE_TYPES:
            return "未列出交易类型的规则只适用于销售收入与额度采购"
        if self.channels and channel not in self.channels:
            return "渠道不在范围内"
        if self.counterparties and counterparty not in self.counterparties:
            return "往来方不在范围内"
        return None

    def matches(
        self, type_code: str, channel: str | None, counterparty: str | None, on: date, commodity: str | None = None
    ) -> bool:
        return self.mismatch(type_code, channel, counterparty, on, commodity) is None


def select_rule(
    rules: Sequence[FeeRule],
    type_code: str,
    channel: str | None,
    counterparty: str | None,
    on: date,
    commodity: str | None = None,
) -> FeeRule | None:
    """Highest priority wins, then the most specific scope; a tie is an error, never a guess."""
    candidates = [r for r in rules if r.matches(type_code, channel, counterparty, on, commodity)]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.priority, r.specificity), reverse=True)
    best = candidates[0]
    if len(candidates) > 1 and (candidates[1].priority, candidates[1].specificity) == (best.priority, best.specificity):
        raise DomainError(
            "FEE_RULE_AMBIGUOUS",
            f"手续费规则 {best.code} 与 {candidates[1].code} 同时适用且优先级相同，请调整优先级或范围。",
        )
    return best


def _clamp(rule: FeeRule, fee: int) -> int:
    if rule.min_minor is not None:
        fee = max(fee, rule.min_minor)
    if rule.max_minor is not None:
        fee = min(fee, rule.max_minor)
    return fee


def fee_on(rule: FeeRule, base_minor: int, mode: str = "half_up") -> int:
    """Fee charged on a base amount (sale gross, purchase face value…)."""
    fee = round_minor(Decimal(base_minor) * rule.rate, mode) if rule.rate is not None else 0
    return _clamp(rule, fee + (rule.fixed_minor or 0))


def split_total(rule: FeeRule, total_minor: int, mode: str = "half_up") -> tuple[int, int]:
    """(base, fee) when only the total paid (base + fee) is known."""
    fixed = rule.fixed_minor or 0
    base = round_minor(Decimal(total_minor - fixed) / (Decimal(1) + (rule.rate or Decimal(0))), mode)
    fee = _clamp(rule, total_minor - base)
    return total_minor - fee, fee
