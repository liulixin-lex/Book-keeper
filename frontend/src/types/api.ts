export type UserRole = "admin" | "bookkeeper" | "viewer";

export interface User {
  id: string;
  workspace_id: string;
  username: string;
  email: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  csrf_token: string;
  expires_at: string;
}

export type RecordType = "income" | "expense";
export type RecordStatus = "draft" | "pending_approval" | "posted" | "reversed";

export interface MoneyRead {
  role: string;
  currency: string;
  amount: string;
  amount_cny: string;
  fx_rate_id?: string | null;
  derived: boolean;
}

export interface RecordRead {
  id: string;
  record_type: RecordType;
  status: RecordStatus;
  accounting_date: string;
  occurred_at?: string | null;
  date_precision: string;
  description: string;
  source_channel?: string | null;
  external_id?: string | null;
  recognition_method: string;
  note?: string | null;
  category_id?: string | null;
  category_name?: string | null;
  counterparty_id?: string | null;
  counterparty_name?: string | null;
  created_by_user_id?: string | null;
  created_by_username: string;
  source_locator?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  version: number;
  amounts: MoneyRead[];
}

export interface RecordPageRead {
  items: RecordRead[];
  total: number;
  total_amount_cny: string;
  limit: number;
  offset: number;
}

export interface OverviewRead {
  start_date: string;
  end_date: string;
  gross_revenue: string;
  channel_fees: string;
  net_revenue: string;
  operating_expenses: string;
  operating_net: string;
  cash_in: string;
  cash_out: string;
  net_cash: string;
  posted_records: number;
  expense_by_user: ExpenseUserSummary[];
}

export interface ExpenseUserSummary {
  user_id?: string | null;
  username: string;
  amount: string;
}

export interface MemberOption {
  id: string;
  username: string;
}

export interface DailyReportRow {
  date: string;
  gross_revenue: string;
  channel_fees: string;
  net_revenue: string;
  operating_expenses: string;
  operating_net: string;
  cash_in: string;
  cash_out: string;
  net_cash: string;
}

export interface DashboardRateRead {
  cny_per_unit: string;
  source: string;
  effective_at: string;
  fetched_at: string;
  is_stale: boolean;
}

export interface DashboardReportRead {
  display_currency: string;
  rate: DashboardRateRead;
  overview: OverviewRead;
  daily: DailyReportRow[];
}

export interface AIProvider {
  id: string;
  workspace_id: string;
  name: string;
  protocol: "responses" | "chat_completions" | "anthropic_messages";
  base_url: string;
  model: string;
  reasoning_effort:
    "none" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
  timeout_seconds: number;
  headers_json: Record<string, string>;
  capabilities_json: Record<string, unknown>;
  is_active: boolean;
  version: number;
  has_api_key: boolean;
  api_key_source: string;
  last_tested_at?: string | null;
  last_test_status?: string | null;
  last_test_error?: string | null;
}

export interface AIWorkspaceSettings {
  agents_md: string;
  web_access_enabled: boolean;
  version: number;
}

export interface ApprovalRequest {
  id: string;
  kind: string;
  status: "pending" | "processing" | "approved" | "rejected";
  payload: Record<string, unknown>;
  requested_by_user_id?: string | null;
  requested_by_ai_run_id?: string | null;
  decided_by_id?: string | null;
  decided_at?: string | null;
  reason?: string | null;
  created_at: string;
}

export interface Account {
  id: string;
  code: string;
  name: string;
  account_type: string;
  subtype?: string | null;
  currency?: string | null;
  is_active: boolean;
}

export interface Category {
  id: string;
  parent_id?: string | null;
  account_id: string;
  name: string;
  kind: "income" | "expense" | "both";
  is_active: boolean;
}

export interface Provider {
  id: string;
  name: string;
  expense_category_id: string;
  expense_category_name: string;
  is_active: boolean;
}

export interface FxRate {
  id: string;
  base_currency: string;
  quote_currency: string;
  rate: string;
  effective_at: string;
  source: string;
  rate_type: string;
  fetched_at: string;
}

export interface Subscription {
  id: string;
  counterparty_id: string;
  name: string;
  billing_cycle: string;
  currency: string;
  expected_amount?: string | null;
  renewal_date?: string | null;
  auto_renew: boolean;
  is_active: boolean;
  version: number;
}

export interface AuditEvent {
  id: string;
  actor_type: string;
  actor_id?: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  before_json?: Record<string, unknown> | null;
  after_json?: Record<string, unknown> | null;
  request_id?: string | null;
  ai_run_id?: string | null;
  created_at: string;
}

export interface AuditPageRead {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
}

export type AIWorkflowStatus =
  | "collecting"
  | "extracting"
  | "needs_input"
  | "draft"
  | "validating"
  | "ready"
  | "committing"
  | "committed"
  | "pending_approval"
  | "cancelled"
  | "expired"
  | "failed"
  | "unknown";

export type ProposalFieldStatus =
  "source_exact" | "rule_derived" | "ai_inferred" | "missing" | "ambiguous";

export interface AICommand {
  command: string;
  label: string;
  description: string;
  effect: "read" | "propose" | "control";
  plugin_id: string;
  starts_workflow: boolean;
}

export interface ProposalField {
  value: unknown;
  status: ProposalFieldStatus;
  source_ref?: string | null;
  source_span?: string | null;
}

export interface ProposalValidationError {
  field: string;
  code: string;
  message: string;
}

export interface JournalPreviewLine {
  account_id: string;
  account_code: string;
  account_name: string;
  debit_cny: string;
  credit_cny: string;
}

export interface LedgerProposal {
  id: string;
  sequence: number;
  operation: string;
  record_type?: string | null;
  status: string;
  version: number;
  fields: Record<string, ProposalField>;
  validation: {
    valid?: boolean;
    errors?: ProposalValidationError[];
    rules_version?: string;
    schema_version?: string;
  };
  journal_preview: {
    balanced?: boolean;
    lines?: JournalPreviewLine[];
    original?: Record<string, unknown> | null;
  };
  duplicate: {
    status?: string;
    matches?: Array<{
      record_id: string;
      description: string;
      match: string;
    }>;
    requires_override?: boolean;
    override?: boolean;
    business_fingerprint?: string;
  };
  entity_versions: Record<string, unknown>;
  canonical_hash?: string | null;
  committed_record_id?: string | null;
  approval_id?: string | null;
}

export interface AIWorkflow {
  id: string;
  command: string;
  status: AIWorkflowStatus;
  version: number;
  canonical_hash?: string | null;
  selected_proposal_ids: string[];
  validation: {
    valid?: boolean;
    proposal_count?: number;
    invalid_count?: number;
  };
  result: {
    records?: Array<Record<string, unknown>>;
    approvals?: Array<Record<string, unknown>>;
    atomic?: boolean;
  };
  error?: string | null;
  created_at: string;
  updated_at: string;
  input_count: number;
  attachment_count: number;
  messages: Array<{
    id: string;
    sequence: number;
    role: "user" | "assistant";
    content: string;
    clarifying_questions: string[];
    created_at: string;
  }>;
  proposals: LedgerProposal[];
  events: Array<{
    sequence: number;
    event_type: string;
    payload: Record<string, unknown>;
    created_at: string;
  }>;
}

export interface AIPlugin {
  id: string;
  name: string;
  version: string;
  api_version: string;
  commands: string[];
  permissions: string[];
  data_scope: string[];
  effect: "read" | "propose";
  approval_policy: "none" | "user_confirmation" | "admin_approval";
  idempotent: boolean;
  timeout_seconds: number;
  core: boolean;
  enabled: boolean;
  config: Record<string, unknown>;
  health_status: string;
  last_error?: string | null;
}

export interface AIEmbeddingProvider {
  id: string;
  name: string;
  base_url: string;
  model: string;
  dimension: number;
  timeout_seconds: number;
  batch_size: number;
  is_active: boolean;
  version: number;
  index_version: number;
  pending_index_version?: number | null;
  has_api_key: boolean;
  api_key_source: string;
  last_tested_at?: string | null;
  last_test_status?: string | null;
  last_test_error?: string | null;
}

export interface KnowledgeStatus {
  documents: number;
  chunks: number;
  jobs: Record<string, number>;
  vector_backend: string;
  embedding_provider?: AIEmbeddingProvider | null;
  fallback_available: boolean;
}
export type BackupStorageType = "s3" | "r2";

export interface BackupStorageConfig {
  storage_type: BackupStorageType;
  endpoint_url: string | null;
  region: string;
  bucket: string;
  access_key_id: string;
  prefix: string;
  force_path_style: boolean;
  secret_configured: boolean;
  version: number;
}

export interface BackupScheduleConfig {
  enabled: boolean;
  cron_expression: string;
  retain_days: number;
  retain_count: number;
  timezone: string;
  next_run_at: string | null;
  version: number;
}

export interface BackupRun {
  id: string;
  status: "running" | "completed" | "failed";
  trigger: "manual" | "scheduled";
  file_name: string;
  object_key: string | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  expires_at: string | null;
}
