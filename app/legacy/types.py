from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

type Scalar = str | bool | None
type DatePrecision = Literal["month", "date", "second"]


@dataclass(frozen=True, slots=True)
class SourceLocation:
    file: str
    sha256: str
    sheet: str | None = None
    page: int | None = None
    row: int | None = None
    column: int | None = None
    cell: str | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    field: str
    source: SourceLocation
    value: Scalar
    formula: str | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class LegacyRecord:
    record_type: Literal["income", "expense", "upstream_recharge"]
    source_system: str
    category: str
    accounting_date: str
    occurred_at: str | None
    date_precision: DatePrecision
    service_period: str | None
    description: str
    counterparty: str | None
    channel: str | None
    external_id: str | None
    status: str | None
    currency: str
    original_amount: str
    fx_rate: str
    gross_amount_cny: str | None
    fee_amount_cny: str | None
    net_amount_cny: str | None
    operating_amount_cny: str
    cash_amount_cny: str
    credited_value: str | None
    recognition_method: str | None
    notes: str | None
    fingerprint: str
    business_fingerprint: str
    source_fingerprint: str
    evidence: tuple[FieldEvidence, ...]
    metadata: dict[str, Scalar] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LegacyExtraction:
    records: tuple[LegacyRecord, ...]
    source_hashes: dict[str, str]

    def records_for(
        self,
        *,
        record_type: str | None = None,
        source_system: str | None = None,
        category: str | None = None,
    ) -> tuple[LegacyRecord, ...]:
        return tuple(
            record
            for record in self.records
            if (record_type is None or record.record_type == record_type)
            and (source_system is None or record.source_system == source_system)
            and (category is None or record.category == category)
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
