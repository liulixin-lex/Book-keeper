"""`bookkeeper ai-eval`: how well each provider and model reads a gold set, field by field (docs/19 §4.4).

A gold set is a folder of screenshots / PDFs, each with ``<file>.gold.json`` beside it:
``{"page_type": "order_list", "records": [{"occurred_at": "2026-10-05 12:00", "direction": "out", "amount": "8.00",
"currency": "CNY", "order_no": "A1", "counterparty": "…"}]}`` (fields left out are not scored).

Real gold sets hold real bills: keep them outside the repository (the default ``.local/ai-gold`` is ignored by git).
The repository has only synthetic samples (tests/fixtures/ai_eval). ``--replay`` reads recorded answers instead of
calling a provider, so a comparison can be rerun without paying again; ``--record`` saves answers for that.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from bookkeeper.ai import adapters
from bookkeeper.ai.adapters import Request, Response, Target, Usage
from bookkeeper.services import ai_extract

FIELDS = ("occurred_at", "direction", "amount", "currency", "order_no", "counterparty", "fee", "face")
MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


@dataclass
class Sample:
    name: str
    data: bytes
    mime: str
    gold: dict[str, Any]


@dataclass
class Score:
    """One target over the whole gold set."""

    target: str
    files: int = 0
    page_type_ok: int = 0
    gold_rows: int = 0
    read_rows: int = 0
    matched: int = 0
    field_ok: dict[str, int] = field(default_factory=dict)
    field_seen: dict[str, int] = field(default_factory=dict)
    unreadable: int = 0
    failed: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "files": self.files,
            "page_type": _rate(self.page_type_ok, self.files),
            "recall": _rate(self.matched, self.gold_rows),
            "precision": _rate(self.matched, self.read_rows),
            "fields": {f: _rate(self.field_ok.get(f, 0), self.field_seen[f]) for f in FIELDS if self.field_seen.get(f)},
            "unreadable": self.unreadable,
            "failed": self.failed,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost, 4) if self.cost is not None else None,
            "seconds": round(self.seconds, 1),
        }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def load_gold(folder: Path) -> list[Sample]:
    samples = []
    for path in sorted(folder.iterdir()):
        mime = MIMES.get(path.suffix.lower())
        gold = path.with_name(path.name + ".gold.json")
        if mime and gold.exists():
            samples.append(Sample(path.name, path.read_bytes(), mime, json.loads(gold.read_text(encoding="utf-8"))))
    return samples


def _norm(fieldname: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if fieldname in ("amount", "fee", "face"):
        try:
            return format(Decimal(text.replace(",", "")).normalize(), "f")
        except InvalidOperation:
            return text
    if fieldname == "occurred_at":
        return re.sub(r"[T ]", " ", text)[:16]  # to the minute
    if fieldname in ("currency", "direction"):
        return text.upper() if fieldname == "currency" else text
    return text.lower() if fieldname == "counterparty" else text


def _pair(gold: list[dict[str, Any]], read: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Gold rows to read rows: by order number when the gold has one, else by time and amount."""
    left = list(read)
    pairs = []
    for want in gold:
        key = _norm("order_no", want.get("order_no"))
        found = next((r for r in left if key and _norm("order_no", r.get("order_no")) == key), None)
        if found is None:
            found = next(
                (
                    r
                    for r in left
                    if _norm("amount", r.get("amount")) == _norm("amount", want.get("amount"))
                    and (_norm("occurred_at", r.get("occurred_at")) or "")[:10]
                    == (_norm("occurred_at", want.get("occurred_at")) or "")[:10]
                ),
                None,
            )
        if found is not None:
            left.remove(found)
            pairs.append((want, found))
    return pairs


def _rows(name: str, page: dict[str, Any], today: date) -> list[dict[str, Any]]:
    """The model's page in the gold's shape, after the same checks the import runs (year, amounts)."""
    read = ai_extract._records(name, page, None, (), today)
    return [
        {
            "occurred_at": r["occurred_at"],
            "direction": r["direction"],
            "amount": r["amount"],
            "currency": r["commodity"],
            "order_no": r["order_no"],
            "counterparty": r["counterparty"],
            "fee": r["fee"],
            "face": (r.get("extracted") or {}).get("face"),
        }
        for r in read.records
    ]


def score_file(result: Score, sample: Sample, page: dict[str, Any], today: date) -> None:
    result.files += 1
    gold_rows = list(sample.gold.get("records") or [])
    if page.get("page_type") == sample.gold.get("page_type"):
        result.page_type_ok += 1
    rows = _rows(sample.name, page, today)
    result.gold_rows += len(gold_rows)
    result.read_rows += len(rows)
    result.unreadable += len(page.get("unreadable") or [])
    for want, got in _pair(gold_rows, rows):
        result.matched += 1
        for name in FIELDS:
            if name not in want:
                continue
            result.field_seen[name] = result.field_seen.get(name, 0) + 1
            if _norm(name, want[name]) == _norm(name, got.get(name)):
                result.field_ok[name] = result.field_ok.get(name, 0) + 1


class Replay:
    """Recorded answers as a backend: ``<folder>/<file>.json`` holds the page the model gave for that file."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def complete(self, target: Target, request: Request, *, json_mode: bool) -> Response:
        part = next(p for m in request.messages for p in m.parts if p.kind in ("image", "pdf"))
        recorded = json.loads((self.folder / f"{part.name}.json").read_text(encoding="utf-8"))
        usage = recorded.pop("_usage", {"input_tokens": 0, "output_tokens": 0})
        return Response(json.dumps({"page": recorded}, ensure_ascii=False), [], "end", Usage(**usage), target.model)

    def list_models(self, target: Target) -> list[str]:
        return [target.model]


def evaluate(
    targets: Sequence[Target],
    samples: Sequence[Sample],
    *,
    handbook: str,
    today: date,
    backend_for: Callable[[Target], adapters.Backend | None] = lambda t: None,
    record: Path | None = None,
) -> list[Score]:
    """Read every sample with every target, one file at a time, and score it."""
    scores = []
    for target in targets:
        label = f"{target.provider_name} · {target.model}"
        result = Score(label)
        backend = backend_for(target)
        for sample in samples:
            calls: list[dict[str, Any]] = []
            started = time.monotonic()
            try:
                page = ai_extract._read([target], sample.name, sample.data, sample.mime, "", backend, calls, handbook)
            except Exception as exc:  # one bad file must not stop the comparison
                result.failed.append(f"{sample.name}：{getattr(exc, 'detail', exc)}")
                continue
            finally:
                result.seconds += time.monotonic() - started
                for call in calls:
                    result.input_tokens += call["usage"].input_tokens
                    result.output_tokens += call["usage"].output_tokens
                    spend = adapters.cost(call["target"], call["usage"])
                    if spend is not None:
                        result.cost = (result.cost or 0.0) + spend
            usage = page.pop("_usage", None)
            page.pop("_model", None)
            if record is not None:
                folder = record / _slug(label)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{sample.name}.json").write_text(
                    json.dumps(page | {"_usage": usage}, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            score_file(result, sample, page, today)
        scores.append(result)
    return scores


def _slug(label: str) -> str:
    return re.sub(r"[^\w.-]+", "_", label).strip("_")


def table(scores: Sequence[Score]) -> str:
    """A plain-text comparison: one row per target, one column per field."""
    head = ["目标", "文件", "页面类型", "召回", "准确", *FIELDS, "读不清", "失败", "token", "费用", "秒"]
    lines = [" | ".join(head)]
    for s in scores:
        d = s.as_dict()
        cells = [
            d["target"],
            str(d["files"]),
            _pct(d["page_type"]),
            _pct(d["recall"]),
            _pct(d["precision"]),
            *(_pct(d["fields"].get(f)) for f in FIELDS),
            str(d["unreadable"]),
            str(len(d["failed"])),
            str(d["input_tokens"] + d["output_tokens"]),
            "—" if d["cost_usd"] is None else f"${d['cost_usd']:.2f}",
            str(d["seconds"]),
        ]
        lines.append(" | ".join(cells))
    return "\n".join(lines)
