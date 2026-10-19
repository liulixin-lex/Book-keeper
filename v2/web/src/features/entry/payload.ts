/** Form state → TransactionIn. Kept pure so the rules (what is required, how dates and money are sent) are testable. */
import { ApiError, type FieldError } from "@/api/client";
import type { TransactionDetail, TransactionType } from "@/api/types";
import { fromMinor, parseAmount } from "@/lib/format";
import type { FieldSpec } from "@/lib/schema";

export interface MoneyDraft {
  amount: string;
  commodity: string;
}

export interface LineDraft {
  account: string;
  side: "debit" | "credit";
  amount: string;
  commodity: string;
  memo: string;
}

export function buildPayload(s: {
  type: TransactionType | undefined;
  fields: FieldSpec[];
  counterparty: string;
  date: string;
  time: string;
  values: Record<string, string | MoneyDraft>;
  orderNo: string;
  description: string;
  notes: string;
  tags: string;
  lines: LineDraft[];
  timezone?: string;
}): { ready: boolean; body: Record<string, unknown> } {
  const body: Record<string, unknown> = { type: s.type?.code };
  if (!s.type) return { ready: false, body };
  if (s.counterparty.trim()) body.counterparty = s.counterparty.trim();
  if (s.time && s.timezone === "Asia/Shanghai") body.occurred_at = `${s.date}T${s.time}:00+08:00`;
  else body.effective_date = s.date;
  if (s.orderNo.trim()) body.order_no = s.orderNo.trim();
  if (s.description.trim()) body.description = s.description.trim();
  if (s.notes.trim()) body.notes = s.notes.trim();
  const tags = s.tags
    .split(/[,，]/)
    .map((t) => t.trim())
    .filter(Boolean);
  if (tags.length) body.tags = tags;

  if (s.type.input_mode === "lines") {
    const lines = s.lines
      .filter((l) => l.account && parseAmount(l.amount))
      .map((l) => ({ account: l.account, side: l.side, amount: { amount: parseAmount(l.amount), commodity: l.commodity }, ...(l.memo ? { memo: l.memo } : {}) }));
    body.lines = lines;
    return { ready: lines.length >= 2 && !!s.date, body };
  }

  const inputs: Record<string, unknown> = {};
  let ready = !!s.date;
  for (const f of s.fields) {
    const v = s.values[f.key];
    if (f.kind === "money") {
      const m = v as MoneyDraft | undefined;
      const amount = m ? parseAmount(m.amount) : null;
      if (amount) inputs[f.key] = { amount, commodity: m!.commodity };
      else if (f.required) ready = false;
    } else {
      const text = typeof v === "string" ? v.trim() : "";
      if (text) inputs[f.key] = text;
      else if (f.required) ready = false;
    }
  }
  // 额度采购 needs at least one of 面值 / 实付.
  if (s.type.code === "credit_purchase" && !inputs.face && !inputs.total) ready = false;
  body.inputs = inputs;
  return { ready, body };
}

export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError)) return {};
  const out: Record<string, string> = {};
  error.errors.forEach((e: FieldError) => {
    const parts = e.path.split(".");
    const key = parts[0] === "inputs" ? (parts[1] ?? "inputs") : (parts[0] ?? "");
    out[key] ??= e.message;
  });
  return out;
}

export interface Draft {
  counterparty: string;
  date: string;
  time: string;
  values: Record<string, string | MoneyDraft>;
  orderNo: string;
  description: string;
  notes: string;
  tags: string;
  lines: LineDraft[];
}

interface Lookups {
  accountCode: (id: string) => string | undefined;
  channelCode: (id: string) => string | undefined;
  scale: (commodity: string) => number;
  clock: (at: string) => string | null;
}

const MONEY_KEYS = new Set(["gross", "fee", "amount", "fee_refunded", "face", "total", "amount_out", "amount_in"]);

/** A saved transaction → the entry form's state, so editing starts from exactly what was recorded. */
export function draftFromDetail(t: TransactionDetail, l: Lookups): Draft {
  const values: Record<string, string | MoneyDraft> = {};
  for (const [key, raw] of Object.entries(t.inputs)) {
    if (MONEY_KEYS.has(key) && raw && typeof raw === "object") {
      const m = raw as { minor: number; commodity: string };
      values[key] = { amount: fromMinor(m.minor, l.scale(m.commodity)), commodity: m.commodity };
    } else if (key === "channel_id" && typeof raw === "string") values.channel = l.channelCode(raw) ?? raw;
    else if (key === "original_id" && typeof raw === "string") values.original = raw;
    else if (key === "counterparty_account_id" && typeof raw === "string") values.counterparty_account = raw;
    else if ((key === "category" || key.endsWith("_account")) && typeof raw === "string") values[key] = l.accountCode(raw) ?? raw;
    else if ((key === "credit_quantity" || key === "fx_rate") && raw != null) values[key] = String(raw);
  }
  const stored = Array.isArray(t.inputs.lines) ? (t.inputs.lines as { account_id: string; side: "debit" | "credit"; amount_minor: number; commodity: string; memo?: string | null }[]) : [];
  return {
    counterparty: t.counterparty?.name ?? "",
    date: t.effective_date,
    time: t.occurred_at ? (l.clock(t.occurred_at) ?? "") : "",
    values,
    orderNo: t.order_no ?? "",
    // An automatic description stays automatic: it is regenerated when the amounts or the counterparty change.
    description: t.provenance.description ? t.description : "",
    notes: t.notes ?? "",
    tags: t.tags.join(", "),
    lines: stored.map((x) => ({
      account: l.accountCode(x.account_id) ?? x.account_id,
      side: x.side,
      amount: fromMinor(Math.abs(x.amount_minor), l.scale(x.commodity)),
      commodity: x.commodity,
      memo: x.memo ?? "",
    })),
  };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** Two request bodies (before / after the edit) → the PATCH: only what changed; cleared fields become null. */
export function patchBody(before: Record<string, unknown>, after: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!same(before.effective_date, after.effective_date) || !same(before.occurred_at, after.occurred_at)) {
    if (after.occurred_at) out.occurred_at = after.occurred_at;
    else {
      out.effective_date = after.effective_date;
      if (before.occurred_at) out.occurred_at = null;
    }
  }
  for (const key of ["counterparty", "order_no", "notes"]) if (!same(before[key], after[key])) out[key] = after[key] ?? null;
  if (!same(before.description, after.description)) out.description = after.description ?? "";
  if (!same(before.tags ?? [], after.tags ?? [])) out.tags = after.tags ?? [];
  const bi = (before.inputs ?? {}) as Record<string, unknown>;
  const ai = (after.inputs ?? {}) as Record<string, unknown>;
  const inputs: Record<string, unknown> = {};
  for (const key of new Set([...Object.keys(bi), ...Object.keys(ai)])) if (!same(bi[key], ai[key])) inputs[key] = ai[key] ?? null;
  if (Object.keys(inputs).length) out.inputs = inputs;
  if (after.lines !== undefined && !same(before.lines, after.lines)) out.lines = after.lines;
  return out;
}
