import type { Money } from "@/lib/format";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_superadmin: boolean;
}

export interface BookRef {
  id: string;
  name: string;
  role: "viewer" | "accountant" | "admin" | "owner";
}

export interface Me {
  user: User;
  books: BookRef[];
  auth_method: string;
  csrf_token?: string;
}

export interface Book {
  id: string;
  name: string;
  base_commodity: string;
  timezone: string;
  role: BookRef["role"];
  /** What you may do here: your role's permissions. */
  scopes: string[];
  /** Token tiers you may hand out. */
  token_tiers: TokenTier[];
  version: number;
}

export type TokenTier = "user_read" | "user_write" | "admin_read" | "admin_write";

export type Enums = Record<string, Record<string, string>>;

export interface Ref {
  id: string;
  code?: string;
  name: string;
}

/** Two states only: 已入账 and 已删除. Edits keep the number; deletes and edits can be undone. */
export interface Transaction {
  id: string;
  number: string;
  type: string;
  status: "posted" | "reversed";
  effective_date: string;
  occurred_at: string | null;
  date_precision: string;
  description: string;
  counterparty_id: string | null;
  channel_id: string | null;
  amount: Money | null;
  external_ref: string | null;
  order_no: string | null;
  is_estimate: boolean;
  created_channel: string;
  posted_entry_id: string | null;
  reverse_reason: string | null;
  notes: string | null;
  version: number;
}

export interface PreviewLine {
  line_no: number;
  account_code: string;
  account_name: string;
  commodity: string;
  amount: Money;
  side?: "debit" | "credit";
  role?: string;
}

export interface Computed {
  gross?: number;
  fee?: number;
  net?: number;
  total?: number;
  amount?: number;
  commodity?: string;
  headline?: Money;
  entry_number?: string;
  fee_expected?: number | null;
  warnings?: { code: string; message: string }[];
  [k: string]: unknown;
}

export interface TransactionDetail extends Transaction {
  counterparty: Ref | null;
  channel: Ref | null;
  inputs: Record<string, unknown>;
  computed: Computed;
  provenance: Record<string, { by: string; at: string; locked: boolean }>;
  metadata: Record<string, unknown>;
  links: { kind: string; transaction_id: string; number?: string }[];
  tags: string[];
  sources: unknown[];
  entries: JournalEntry[];
  /** Only on dry runs of a new transaction: the lines that would be written. */
  preview_lines?: PreviewLine[];
  /** Which fee rule the transaction used (types that carry a fee). */
  fee_rule?: FeeBasis | null;
}

export interface JournalLine {
  line_no: number;
  account_id?: string;
  account_code: string;
  account_name: string;
  commodity: string;
  amount: Money;
  base_amount?: number;
  line_role?: string;
  memo?: string | null;
}

export interface JournalEntry {
  id: string;
  number?: string;
  kind: string;
  effective_date: string;
  recorded_at: string;
  description?: string;
  reverses_entry_id?: string | null;
  reversed_by_entry_id?: string | null;
  lines: JournalLine[];
}

export interface TransactionType {
  code: string;
  name: string;
  category: "income" | "expense" | "transfer" | "adjustment" | "system";
  description: string;
  input_mode: "inputs" | "lines";
  is_active: boolean;
  input_schema: JsonSchema | null;
  default_accounts: Record<string, string>;
  fee_rules_apply: boolean;
  example: Record<string, unknown> | null;
}

export interface JsonSchema {
  type?: string | string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  description?: string;
  title?: string;
  default?: unknown;
  $ref?: string;
  anyOf?: JsonSchema[];
  enum?: string[];
  examples?: unknown[];
  $defs?: Record<string, JsonSchema>;
}

export interface WorkSummaryItem {
  label: string;
  count: number;
  balance?: Money;
  last_run?: string;
}

export interface WorkSummary {
  summary: Record<string, WorkSummaryItem>;
  total: number;
}

export interface Counterparty {
  id: string;
  name: string;
  category: string;
  roles: string[];
  domains: string[];
  notes: string | null;
  is_active: boolean;
  version: number;
  aliases: { id?: string; alias?: string; pattern?: string; match_type?: string }[] | string[];
  accounts: { id: string; name?: string; label?: string }[];
  defaults: { type: { code: string; name: string } | null; channel: { code: string; name: string } | null };
}

export interface DimensionValue {
  id: string;
  code: string;
  name: string;
  aliases?: string[];
  is_active: boolean;
  version: number;
}

export interface DimensionType {
  code: string;
  name: string;
  values: DimensionValue[];
}

export interface Account {
  id: string;
  code: string;
  name: string;
  full_name: string;
  classification: "asset" | "liability" | "equity" | "revenue" | "expense";
  role: string | null;
  parent_code: string | null;
  level: number;
  is_group: boolean;
  is_active: boolean;
  is_system: boolean;
  normal_side: "debit" | "credit";
  description: string | null;
  version: number;
}

export interface Commodity {
  code: string;
  name: string;
  kind: string;
  scale: number;
  symbol: string | null;
  is_active: boolean;
}

/* ---------- reports ---------- */

export type Drilldown = { transactions?: Record<string, string> };

export interface Summary {
  title: string;
  profit: { revenue: Money; cost: Money; gross_profit: Money; operating_profit: Money; net_profit: Money };
  funds: { commodity: string; amount: Money; base: Money }[];
  top_channels: { channel: { code: string; name: string }; net_sales: Money; orders: number }[];
  top_sites: { site: { id: string; name: string }; total_paid: Money; purchases: number }[];
  attention: { estimated: number; suspense_balance: Money };
}

export type OpsKey = "sales" | "other_income" | "fees" | "credit_cost" | "other_cost" | "expenses" | "profit";

export interface OpsRow {
  period: string;
  values: Record<OpsKey, Money>;
  counts: Record<string, number>;
  drilldown: Drilldown;
}

export interface Operations {
  title: string;
  columns: { key: OpsKey; name: string }[];
  rows: OpsRow[];
  totals: Record<OpsKey, Money>;
}

export interface SalesRow {
  channel: { code: string; name: string };
  orders: number;
  refund_count: number;
  gross: Money;
  refunds: Money;
  net_sales: Money;
  fees: Money;
  net_received: Money;
  fee_rate: string | null;
  average_order: Money | null;
  drilldown: Drilldown;
}

export interface CreditRow {
  site: { id: string; name: string };
  purchases: number;
  face: Money;
  fees: Money;
  total_paid: Money;
  refunds: Money;
  net_cost: Money;
  credit_quantity: string | null;
  cost_per_credit: string | null;
  fee_rate: string | null;
  drilldown: Drilldown;
}

export interface FeeRow {
  channel: { code: string; name: string } | null;
  transaction_type: { code: string; name: string };
  count: number;
  fee: Money;
  estimated_fee: Money;
  base: Money;
  effective_rate: string | null;
  drilldown: Drilldown;
}

export interface IncomeLine {
  code: string;
  name: string;
  level: number;
  amount: Money;
  drilldown?: Drilldown;
}

/* ---------- imports ---------- */

export interface ImportSource {
  id: string;
  code: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  is_active: boolean;
  version: number;
}

export interface BatchSummary {
  records?: number;
  by_status?: Record<string, number>;
  skipped?: number;
  row_errors?: { row_no: number; message: string }[];
  checks?: { code: string; severity: string; ok: boolean; message: string }[];
  blocking?: string[];
  period?: [string, string];
  note?: string;
  commit?: { counts?: Record<string, number> };
  /** Set when an AI read the uploaded screenshots / PDFs. */
  extraction?: { model: string; files: string[]; usage: { input_tokens: number; output_tokens: number }; unreadable: string[]; totals: string[] };
  /** Files of an AI batch, and why its read failed. */
  files?: string[];
  error?: string;
}

export interface Batch {
  id: string;
  source: { id: string; code: string; name: string; kind: string } | string;
  /** parser@version, e.g. "wechat_bill@1.0.0" or "ai_extract@claude-opus-5-5". */
  parser: string;
  /** extracting: an AI is reading the files on the server (识别中); failed: that read failed (识别失败). */
  status: "extracting" | "failed" | "parsed" | "committed" | "reverted";
  summary: BatchSummary;
  note: string | null;
  created_at: string;
  committed_at: string | null;
  reverted_at: string | null;
  commit_change_set_id?: string | null;
  /** Records still waiting: missing a field, or left unbooked by a finished import (list endpoint only). */
  open_records?: number;
}

export interface SourceRecord {
  id: string;
  row_no: number | null;
  status: string;
  occurred_at: string;
  effective_date: string;
  direction: "in" | "out" | "neutral";
  amount: Money;
  fee: Money | null;
  counterparty_text: string | null;
  description: string | null;
  order_no: string | null;
  status_text: string | null;
  classification: {
    type?: string;
    inputs?: Record<string, unknown>;
    missing?: string[];
    counterparty?: string;
    /** Why a complete record still waits in 待确认. */
    review?: ("ai_low_confidence" | "future_date")[];
    /** The model's suggestion for what the rules left open (识别 step 5). */
    ai?: { type?: string; counterparty?: string; category?: string; channel?: string; ignore?: string; confidence: number; reason: string; auto: boolean; used?: boolean; model?: string };
  } | null;
  ignore_reason: string | null;
  transaction_id: string | null;
  /** Why booking this record failed last time (kept on the record until it books). */
  error: { code: string; detail: string } | null;
  version: number;
  /** The booked transaction this record is evidence of (accepted / auto_accepted), or may duplicate (pending). */
  match?: RecordMatch | null;
  /** Where the fee will come from when this record is booked. */
  fee_rule?: FeeBasis | null;
}

/** actual: the fee is given; rule: the rule in force on the date; none: no rule matched, fee 0. */
export interface FeeBasis {
  basis: "actual" | "rule" | "none";
  rule: { id: string; code: string; version: number; name: string; rate: string | null; fixed_minor: number | null; commodity: string | null } | null;
}

export interface RecordMatch {
  suggestion_id: string;
  status: "pending" | "auto_accepted" | "accepted";
  method: string;
  score: number;
  transaction: { id: string; number: string; effective_date: string; description: string; amount: Money | null };
}

export interface Capabilities {
  features: { ai_extract: boolean; imports: boolean; mcp: boolean };
  limits: { upload_max_bytes: number; ai_max_files: number };
}

/* ---------- settings ---------- */

export interface FeeRule {
  id: string;
  code: string;
  version: number;
  name: string | null;
  method: string;
  rate: string | null;
  fixed_minor: number | null;
  commodity: string | null;
  channel_ids: string[];
  counterparty_ids: string[];
  transaction_types: string[];
  valid_from: string;
  valid_to: string | null;
  is_estimate: boolean;
  status: string;
  note: string | null;
}

export interface RuleCondition {
  field: string;
  op: string;
  value: string;
}

export interface RuleAction {
  type: string;
  value?: string;
  reason?: string;
  name?: string;
}

export interface Rule {
  id: string;
  code: string;
  name: string | null;
  stage: string;
  priority: number;
  condition: { all?: RuleCondition[]; any?: RuleCondition[] } & Record<string, unknown>;
  actions: RuleAction[];
  is_active: boolean;
  version: number;
}

export interface Token {
  id: string;
  name: string;
  token_prefix: string;
  tier: TokenTier;
  tier_label: string;
  /** Present when the owner's role was lowered: the tier the token acts with now (null = none). */
  effective_tier?: TokenTier | null;
  scopes: string[];
  mcp_enabled: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
  token?: string;
}

export interface ChangeSet {
  id: string;
  operation: string;
  actor_type: string;
  user_id: string | null;
  token_id: string | null;
  channel: string;
  mcp_client: string | null;
  entity_counts: Record<string, number>;
  status: string;
  created_at: string;
}

export interface FxRate {
  id: string;
  base: string;
  quote: string;
  rate_date: string;
  rate: string;
  rate_type: string;
  source: string;
}

/* ---------- 设置 → AI ---------- */

export type AiKind = "anthropic" | "openai_compatible";

export interface AiCapabilities {
  images: boolean;
  pdf: boolean;
  structured: boolean;
  tools: boolean;
  fallback: boolean;
}

export interface AiProvider {
  id: string;
  name: string;
  kind: AiKind;
  base_url: string | null;
  has_key: boolean;
  key_hint: string | null;
  models: string[];
  default_model: string | null;
  timeout_seconds: number;
  enabled: boolean;
  capabilities: AiCapabilities;
  options: { effort?: string; max_tokens_param?: string };
  prices: Record<string, { input: number; output: number }>;
  version: number;
}

export interface AiRoute {
  provider_id: string;
  model: string;
  provider_name?: string | null;
}

export type AiTask = "extract" | "agent";
export type AiRoutes = Record<AiTask, AiRoute[]>;

export interface AiProbe {
  ok: boolean;
  model: string;
  reply?: string;
  error?: string;
  latency_ms: number;
  models: string[] | null;
  models_error?: string;
  capabilities: AiCapabilities;
}

export interface AiUsageItem {
  provider: string;
  model: string;
  task: string;
  task_label: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  cost_complete: boolean;
}

/* ---------- AI 助手 ---------- */

export type AgentStatus = "queued" | "running" | "waiting" | "done" | "failed" | "cancelled";

export interface AgentRun {
  id: string;
  status: AgentStatus;
  stage: "general" | "recognition";
  tier: TokenTier;
  tier_label: string;
  instruction: string;
  playbook: string | null;
  file_ids: string[];
  question: string | null;
  result: string | null;
  error: string | null;
  change_set_id: string | null;
  turns: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  model: string | null;
  user_id: string;
  created_at: string;
  finished_at: string | null;
  version: number;
}

export interface AgentStep {
  seq: number;
  kind: "instruction" | "assistant" | "tool" | "answer" | "note";
  at: string;
  text?: string;
  calls?: { tool: string; title: string; arguments: Record<string, unknown> }[];
  tool?: string;
  title?: string;
  arguments?: Record<string, unknown>;
  ok?: boolean;
  code?: string;
  message?: string;
}

export interface AgentRunDetail extends AgentRun {
  change_set_status: "applied" | "reverted" | "partially_reverted" | null;
  steps: AgentStep[];
}

export interface AiHandbook {
  version: number;
  content: string;
  threshold: number;
  note?: string | null;
  created_at?: string | null;
  is_default: boolean;
  default: string;
  versions: { version: number; note: string | null; threshold: number; created_at: string }[];
}
