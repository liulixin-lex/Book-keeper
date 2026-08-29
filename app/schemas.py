from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.amounts import as_decimal
from app.enums import ApprovalStatus, DatePrecision, RecordStatus


class MoneyInput(BaseModel):
    currency: str = Field(min_length=3, max_length=12)
    amount: str
    amount_cny: str | None = None
    fx_rate_id: str | None = None
    fx_rate: str | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("amount", "amount_cny", "fx_rate")
    @classmethod
    def validate_decimal_string(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        parsed = as_decimal(normalized)
        if info.field_name == "fx_rate" and parsed <= 0:
            raise ValueError("汇率必须大于零")
        return normalized


class MoneyRead(BaseModel):
    role: str
    currency: str
    amount: str
    amount_cny: str
    fx_rate_id: str | None = None
    derived: bool


class IncomeCreate(BaseModel):
    accounting_date: date
    occurred_at: datetime | None = None
    date_precision: DatePrecision = DatePrecision.DAY
    description: str = Field(min_length=1, max_length=500)
    channel: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, max_length=240)
    gross: MoneyInput
    fee: MoneyInput | None = None
    cash_received: bool = True
    category_id: str | None = None
    counterparty_id: str | None = None
    recognition_method: str = "transaction"
    note: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    post: bool = True


class ExpenseCreate(BaseModel):
    accounting_date: date
    occurred_at: datetime | None = None
    date_precision: DatePrecision = DatePrecision.DAY
    description: str = Field(min_length=1, max_length=500)
    cost: MoneyInput
    fee: MoneyInput | None = None
    cash: MoneyInput | None = None
    category_id: str | None = None
    category_name: str | None = None
    counterparty_id: str | None = None
    source_channel: str | None = None
    external_id: str | None = Field(default=None, max_length=240)
    service_period_start: date | None = None
    service_period_end: date | None = None
    note: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    post: bool = True


class TopupCreate(BaseModel):
    accounting_date: date
    occurred_at: datetime | None = None
    upstream_name: str = Field(min_length=1, max_length=240)
    amount_cny: str
    external_id: str | None = Field(default=None, max_length=240)
    note: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    post: bool = True

    @field_validator("amount_cny")
    @classmethod
    def validate_amount_cny(cls, value: str) -> str:
        normalized = value.strip()
        if as_decimal(normalized) <= 0:
            raise ValueError("充值金额必须大于零")
        return normalized


class RefundCreate(BaseModel):
    original_record_id: str
    accounting_date: date
    occurred_at: datetime | None = None
    description: str | None = Field(default=None, max_length=500)
    refund: MoneyInput
    fee_refund: MoneyInput | None = None
    cash_out: MoneyInput | None = None
    channel: str | None = Field(default=None, max_length=80)
    external_id: str | None = Field(default=None, max_length=240)
    note: str | None = None
    source_locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    post: bool = True


class DraftRecordUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    note: str | None = None
    category_id: str | None = None
    counterparty_id: str | None = None


class RecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    record_type: Literal["income", "expense"]
    status: RecordStatus
    accounting_date: date
    occurred_at: datetime | None
    date_precision: DatePrecision
    description: str
    source_channel: str | None
    external_id: str | None
    recognition_method: str | None
    note: str | None
    category_id: str | None = None
    category_name: str | None = None
    counterparty_id: str | None = None
    counterparty_name: str | None = None
    created_by_user_id: str | None = None
    created_by_username: str = "历史/系统"
    source_locator: dict[str, Any]
    metadata: dict[str, Any]
    version: int
    amounts: list[MoneyRead]


class RecordPageRead(BaseModel):
    items: list[RecordRead]
    total: int
    total_amount_cny: str
    limit: int
    offset: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["income", "expense", "both"]
    account_id: str
    parent_id: str | None = None
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("类别名称不能为空")
        return normalized


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    kind: Literal["income", "expense", "both"] | None = None
    account_id: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("类别名称不能为空")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> CategoryUpdate:
        if not self.model_fields_set:
            raise ValueError("至少需要修改一个字段")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("更新字段不能为 null")
        return self


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    expense_category_id: str
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("提供商名称不能为空")
        return normalized


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    expense_category_id: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("提供商名称不能为空")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> ProviderUpdate:
        if not self.model_fields_set:
            raise ValueError("至少需要修改一个字段")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("更新字段不能为 null")
        return self


class FxRateCreate(BaseModel):
    base_currency: str = Field(min_length=1, max_length=12)
    quote_currency: str = Field(default="CNY", min_length=1, max_length=12)
    rate: str
    effective_at: datetime
    source: str = Field(min_length=1, max_length=160)
    rate_type: str = Field(default="reference", min_length=1, max_length=40)

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("currency must not be blank")
        return normalized

    @field_validator("rate")
    @classmethod
    def validate_positive_rate(cls, value: str) -> str:
        normalized = value.strip()
        if as_decimal(normalized) <= 0:
            raise ValueError("rate must be greater than zero")
        return normalized

    @field_validator("source", "rate_type")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class FxRateUpdate(BaseModel):
    rate: str

    @field_validator("rate")
    @classmethod
    def validate_positive_rate(cls, value: str) -> str:
        normalized = value.strip()
        if as_decimal(normalized) <= 0:
            raise ValueError("汇率必须大于零")
        return normalized


class DailyReportRow(BaseModel):
    date: date
    gross_revenue: str
    channel_fees: str
    net_revenue: str
    operating_expenses: str
    operating_net: str
    cash_in: str
    cash_out: str
    net_cash: str


class ExpenseUserSummary(BaseModel):
    user_id: str | None
    username: str
    amount: str


class OverviewRead(BaseModel):
    start_date: date
    end_date: date
    gross_revenue: str
    channel_fees: str
    net_revenue: str
    operating_expenses: str
    operating_net: str
    cash_in: str
    cash_out: str
    net_cash: str
    posted_records: int
    expense_by_user: list[ExpenseUserSummary] = Field(default_factory=list)


class DashboardRateRead(BaseModel):
    cny_per_unit: str
    source: str
    effective_at: datetime
    fetched_at: datetime
    is_stale: bool


class DashboardReportRead(BaseModel):
    display_currency: str
    rate: DashboardRateRead
    overview: OverviewRead
    daily: list[DailyReportRow]


class ApprovalRequestRead(BaseModel):
    id: str
    kind: str
    status: ApprovalStatus
    payload: dict[str, Any]
    requested_by_user_id: str | None
    requested_by_ai_run_id: str | None
    decided_by_id: str | None
    decided_at: datetime | None
    reason: str | None
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class HealthRead(BaseModel):
    status: str
    sqlite_version: str
    database: str
