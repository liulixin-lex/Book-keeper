"""Domain error codes. Interfaces map them to HTTP problem details and MCP envelopes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    title: str
    retryable: bool = False


ERROR_SPECS: dict[str, ErrorSpec] = {
    "UNAUTHENTICATED": ErrorSpec(401, "未登录或凭据无效"),
    "TOKEN_EXPIRED": ErrorSpec(401, "令牌已过期"),
    "TOKEN_REVOKED": ErrorSpec(401, "令牌已吊销"),
    "CSRF_FAILED": ErrorSpec(403, "CSRF 校验失败"),
    "FORBIDDEN_SCOPE": ErrorSpec(403, "权限不足"),
    "NOT_FOUND": ErrorSpec(404, "对象不存在"),
    "METHOD_NOT_ALLOWED": ErrorSpec(405, "不支持该请求方法"),
    "VALIDATION_FAILED": ErrorSpec(422, "请求内容不符合要求"),
    "AMBIGUOUS_REFERENCE": ErrorSpec(422, "名称对应多个对象"),
    "IDEMPOTENCY_KEY_REQUIRED": ErrorSpec(400, "缺少幂等键"),
    "IDEMPOTENCY_MISMATCH": ErrorSpec(409, "幂等键已用于不同的请求"),
    "IDEMPOTENCY_IN_PROGRESS": ErrorSpec(409, "相同请求仍在处理", retryable=True),
    "VERSION_CONFLICT": ErrorSpec(409, "数据已被修改"),
    "INVALID_STATE": ErrorSpec(409, "当前状态不允许该操作"),
    "CONFLICT": ErrorSpec(409, "与现有数据冲突"),
    "FILE_TOO_LARGE": ErrorSpec(413, "文件过大"),
    "UNSUPPORTED_MEDIA_TYPE": ErrorSpec(415, "不支持的文件类型"),
    "ACCOUNT_LOCKED": ErrorSpec(429, "登录失败次数过多，请稍后再试", retryable=True),
    "RATE_LIMITED": ErrorSpec(429, "请求过于频繁", retryable=True),
    "SNAPSHOT_STALE": ErrorSpec(503, "余额快照重算中", retryable=True),
    "INTERNAL": ErrorSpec(500, "服务器内部错误", retryable=True),
    "INPUT_INVALID": ErrorSpec(422, "输入不符合要求"),
    "COMMODITY_MISMATCH": ErrorSpec(422, "不同币种不能直接运算"),
    "FEE_RULE_AMBIGUOUS": ErrorSpec(422, "手续费规则冲突"),
    "FX_RATE_MISSING": ErrorSpec(422, "缺少汇率"),
    "NOT_BALANCED": ErrorSpec(422, "借贷不平衡"),
    "ACCOUNT_NOT_POSTABLE": ErrorSpec(422, "科目不可记账"),
    "DIMENSION_REQUIRED": ErrorSpec(422, "缺少必填维度"),
    "DIMENSION_FORBIDDEN": ErrorSpec(422, "科目不允许该维度"),
    "BALANCE_RULE_VIOLATION": ErrorSpec(422, "余额方向违反科目规则"),
    "DUPLICATE_SUSPECTED": ErrorSpec(409, "疑似重复"),
    "AI_UNAVAILABLE": ErrorSpec(503, "AI 识别暂不可用", retryable=True),
}


@dataclass(frozen=True)
class FieldError:
    path: str
    code: str
    message: str


@dataclass
class DomainError(Exception):
    """Raised by services; carries everything an interface needs to render the error."""

    code: str
    detail: str
    errors: list[FieldError] = field(default_factory=list)
    next_action: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in ERROR_SPECS:
            raise ValueError(f"unknown error code: {self.code}")
        super().__init__(f"{self.code}: {self.detail}")

    @property
    def spec(self) -> ErrorSpec:
        return ERROR_SPECS[self.code]

    @property
    def status(self) -> int:
        return self.spec.status

    @property
    def retryable(self) -> bool:
        return self.spec.retryable


def not_found(entity: str, ident: str) -> DomainError:
    return DomainError("NOT_FOUND", f"{entity} {ident} 不存在。")


def version_conflict(entity: str, expected: int, actual: int) -> DomainError:
    return DomainError(
        "VERSION_CONFLICT",
        f"{entity} 已被修改（期望版本 {expected}，当前版本 {actual}）。请重新读取后再提交。",
        extra={"current_version": actual},
    )
