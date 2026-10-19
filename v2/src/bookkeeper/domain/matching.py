"""Matching algorithms (docs/06 §7): record ↔ transaction scoring and record ↔ record pairing.

Pairing two time-ordered lists by minimum total |Δt| with unmatched penalties is solved by dynamic
programming over non-crossing matchings; for absolute-difference costs (and interval windows on the
difference) an optimal matching never needs crossings, so the result is globally optimal — unlike
greedy nearest-neighbour matching.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from bookkeeper.domain.rules import norm

INF = math.inf


@dataclass(frozen=True)
class Candidate:
    id: str
    amount: int
    on: date
    name: str = ""
    reference: str = ""
    external_ref: str = ""


@dataclass(frozen=True)
class Scored:
    id: str
    score: float
    method: str
    components: dict[str, float | str]


def trigrams(text: str) -> set[str]:
    t = f"  {norm(text)} "
    return {t[i : i + 3] for i in range(len(t) - 2)}


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    x, y = trigrams(a), trigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def score(
    record: Candidate,
    txn: Candidate,
    *,
    tolerance: int,
    same_counterparty: bool = False,
) -> Scored:
    """Deterministic rounds first (external id, reference, exact amount + party + date), then a weighted score."""
    if record.reference and txn.external_ref and norm(record.reference) == norm(txn.external_ref):
        return Scored(txn.id, 1.0, "external_id", {})
    days = abs((record.on - txn.on).days)
    if record.reference and txn.reference and norm(record.reference) == norm(txn.reference) and days <= 7:
        return Scored(txn.id, 0.98, "reference_window", {"days": days})
    if record.amount == txn.amount and same_counterparty and days <= 1:
        return Scored(txn.id, 0.95, "amount_window", {"days": days})
    delta = abs(record.amount - txn.amount)
    s_amount = 1.0 if delta == 0 else max(0.0, 1.0 - delta / max(tolerance, 1))
    s_date = math.exp(-days / 2)
    s_name = 1.0 if same_counterparty else similarity(record.name, txn.name)
    s_ref = (
        1.0
        if record.reference
        and txn.reference
        and (norm(record.reference) in norm(txn.reference) or norm(txn.reference) in norm(record.reference))
        else 0.0
    )
    total = 0.45 * s_amount + 0.25 * s_date + 0.20 * s_name + 0.10 * s_ref
    components: dict[str, float | str] = {
        "amount": round(s_amount, 4),
        "date": round(s_date, 4),
        "name": round(s_name, 4),
        "reference": s_ref,
        "days": days,
        "amount_delta": delta,
    }
    return Scored(txn.id, round(total, 4), "score", components)


def decide(ranked: Sequence[Scored], *, auto: float = 0.92, lead: float = 0.08, suggest: float = 0.60) -> str:
    """auto_accepted / pending / none for the best candidate of one record."""
    if not ranked:
        return "none"
    best = ranked[0]
    second = ranked[1].score if len(ranked) > 1 else 0.0
    if best.score >= auto and best.score - second >= lead:
        return "auto_accepted"
    return "pending" if best.score >= suggest else "none"


def pair(
    left: Sequence[float],
    right: Sequence[float],
    *,
    before: float,
    after: float,
    penalty: float,
) -> list[tuple[int, int, float]]:
    """Optimal non-crossing matching of two sorted time lists (minutes).

    Right item j may match left item i when ``-before <= right[j] - left[i] <= after``; cost is
    ``|right[j] - left[i]|``; every unmatched item costs ``penalty``. Returns (i, j, gap) pairs.
    """
    n, m = len(left), len(right)
    f = [[INF] * (m + 1) for _ in range(n + 1)]
    step = [[0] * (m + 1) for _ in range(n + 1)]  # 1 = pair, 2 = skip left, 3 = skip right
    f[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best, how = INF, 0
            if i and j:
                gap = right[j - 1] - left[i - 1]
                if -before <= gap <= after:
                    cand = f[i - 1][j - 1] + abs(gap)
                    if cand < best:
                        best, how = cand, 1
            if i and f[i - 1][j] + penalty < best:
                best, how = f[i - 1][j] + penalty, 2
            if j and f[i][j - 1] + penalty < best:
                best, how = f[i][j - 1] + penalty, 3
            f[i][j], step[i][j] = best, how
    pairs: list[tuple[int, int, float]] = []
    i, j = n, m
    while i or j:
        how = step[i][j]
        if how == 1:
            pairs.append((i - 1, j - 1, right[j - 1] - left[i - 1]))
            i, j = i - 1, j - 1
        elif how == 2:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def total_cost(pairs: Sequence[tuple[int, int, float]], n: int, m: int, penalty: float) -> float:
    return sum(abs(g) for _i, _j, g in pairs) + penalty * (n + m - 2 * len(pairs))
