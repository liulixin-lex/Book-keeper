/** Turns a transaction type's JSON schema into form fields. Labels follow docs/14 §10.2; the schema stays the authority. */
import type { JsonSchema, TransactionType } from "@/api/types";

export type FieldKind = "money" | "account" | "category" | "channel" | "original" | "decimal" | "text" | "subaccount";

export interface FieldSpec {
  key: string;
  label: string;
  kind: FieldKind;
  required: boolean;
  advanced: boolean;
  hint: string;
  placeholder?: string;
}

const LABELS: Record<string, string> = {
  gross: "毛额",
  fee: "手续费",
  fee_refunded: "退回手续费",
  amount: "金额",
  face: "面值",
  total: "实付",
  credit_quantity: "额度数量",
  channel: "渠道",
  category: "收支分类",
  original: "原交易",
  settle_account: "到账科目",
  revenue_account: "收入科目",
  pay_account: "付款科目",
  cost_account: "成本科目",
  from_account: "转出科目",
  to_account: "转入科目",
  amount_out: "转出金额",
  amount_in: "转入金额",
  counterparty_account: "站点账号",
  fx_rate: "汇率",
};

/** Overrides of the book defaults live behind “更多选项”; everything the owner types daily stays in view. */
const ADVANCED = new Set(["settle_account", "revenue_account", "pay_account", "cost_account", "fx_rate", "counterparty_account"]);

const KINDS: Record<string, FieldKind> = {
  channel: "channel",
  category: "category",
  original: "original",
  credit_quantity: "decimal",
  fx_rate: "decimal",
  counterparty_account: "subaccount",
};

const HINTS: Record<string, string> = {
  fee: "留空按手续费规则计算",
  fee_refunded: "留空按规则计算",
  total: "与面值的差额记为手续费",
  credit_quantity: "含赠送额度",
  amount_in: "币种不同即为换汇；留空 = 转出 − 手续费",
  fx_rate: "留空按当日参考汇率",
  channel: "留空用往来方的默认渠道",
  original: "交易号，如 T2026-000123",
};

function isMoney(s: JsonSchema | undefined): boolean {
  if (!s) return false;
  if (s.$ref?.endsWith("/MoneyIn")) return true;
  return !!s.anyOf?.some((x) => x.$ref?.endsWith("/MoneyIn"));
}

export function fieldsFor(type: TransactionType): FieldSpec[] {
  const schema = type.input_schema;
  if (!schema?.properties) return [];
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties).map(([key, prop]) => {
    const kind: FieldKind = isMoney(prop) ? "money" : (KINDS[key] ?? (key.endsWith("_account") ? "account" : "text"));
    return {
      key,
      label: LABELS[key] ?? prop.title ?? key,
      kind,
      required: required.has(key),
      advanced: ADVANCED.has(key) && !required.has(key),
      hint: HINTS[key] ?? "",
    };
  });
}

/** Business types shown as entry tabs, in the order the owner uses them. */
export const ENTRY_ORDER = ["sale", "credit_purchase", "expense", "transfer", "sale_refund", "purchase_refund", "manual_journal", "opening_balance"];
