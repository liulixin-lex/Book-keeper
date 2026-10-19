"""Split an amount into parts without losing a minor unit (largest remainder method)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def allocate(total: int, weights: Sequence[Decimal | int]) -> list[int]:
    """Parts proportional to ``weights``; Σ parts == total; ties go to earlier parts."""
    if not weights:
        raise ValueError("weights must not be empty")
    dec = [Decimal(w) for w in weights]
    if any(w < 0 for w in dec):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(dec)
    if weight_sum == 0:
        raise ValueError("weights must not all be zero")
    sign = -1 if total < 0 else 1
    magnitude = abs(total)
    raw = [Decimal(magnitude) * w / weight_sum for w in dec]
    floors = [int(r) for r in raw]
    remainder = magnitude - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:remainder]:
        floors[i] += 1
    return [sign * part for part in floors]
