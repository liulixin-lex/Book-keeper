from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    BOOKKEEPER = "bookkeeper"
    VIEWER = "viewer"


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class RecordType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    TOPUP = "topup"
    SUBSCRIPTION = "subscription"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class RecordStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    POSTED = "posted"
    REVERSED = "reversed"


class JournalStatus(StrEnum):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class AmountRole(StrEnum):
    GROSS = "gross"
    FEE = "fee"
    NET = "net"
    COST = "cost"
    CASH = "cash"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    CREDITED_VALUE = "credited_value"


class DatePrecision(StrEnum):
    TIMESTAMP = "timestamp"
    DAY = "day"
    MONTH = "month"


class CategoryKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    BOTH = "both"


class AIProtocol(StrEnum):
    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"


class AIMode(StrEnum):
    CHAT = "chat"
    EDIT = "edit"


class AIStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AIWorkflowStatus(StrEnum):
    COLLECTING = "collecting"
    EXTRACTING = "extracting"
    NEEDS_INPUT = "needs_input"
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    COMMITTING = "committing"
    COMMITTED = "committed"
    PENDING_APPROVAL = "pending_approval"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ProposalFieldStatus(StrEnum):
    SOURCE_EXACT = "source_exact"
    RULE_DERIVED = "rule_derived"
    AI_INFERRED = "ai_inferred"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


class KnowledgeJobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ReasoningEffort(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"
    ULTRA = "ultra"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActorType(StrEnum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"
