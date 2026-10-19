import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import type { TransactionType } from "@/api/types";
import { fieldsFor } from "@/lib/schema";
import { buildPayload, fieldErrors } from "./payload";

const money = { $ref: "#/$defs/MoneyIn" };
const sale: TransactionType = {
  code: "sale",
  name: "销售收入",
  category: "income",
  description: "",
  input_mode: "inputs",
  is_active: true,
  default_accounts: {},
  fee_rules_apply: true,
  example: null,
  input_schema: {
    required: ["gross"],
    properties: { gross: money, fee: { anyOf: [money, { type: "null" }] }, channel: { anyOf: [{ type: "string" }, { type: "null" }] }, settle_account: { anyOf: [{ type: "string" }, { type: "null" }] } },
  },
};
const purchase: TransactionType = { ...sale, code: "credit_purchase", input_schema: { properties: { face: money, total: money, credit_quantity: { type: "string" } } } };
const journal: TransactionType = { ...sale, code: "manual_journal", input_mode: "lines", input_schema: null };

const base = { counterparty: "", date: "2026-10-19", time: "", orderNo: "", description: "", notes: "", tags: "", lines: [], timezone: "Asia/Shanghai" };

describe("schema fields", () => {
  it("labels fields from docs/14 and hides book-default overrides", () => {
    const f = fieldsFor(sale);
    expect(f.map((x) => [x.key, x.label, x.kind, x.advanced])).toEqual([
      ["gross", "毛额", "money", false],
      ["fee", "手续费", "money", false],
      ["channel", "渠道", "channel", false],
      ["settle_account", "到账科目", "account", true],
    ]);
  });
});

describe("buildPayload", () => {
  it("is not ready until required money is a valid amount", () => {
    const fields = fieldsFor(sale);
    expect(buildPayload({ ...base, type: sale, fields, values: {} }).ready).toBe(false);
    expect(buildPayload({ ...base, type: sale, fields, values: { gross: { amount: "12.3.4", commodity: "CNY" } } }).ready).toBe(false);
    const ok = buildPayload({ ...base, type: sale, fields, values: { gross: { amount: "1,280.50", commodity: "CNY" }, channel: "liandong" }, orderNo: " LD1 ", tags: "赠送，大客户" });
    expect(ok.ready).toBe(true);
    expect(ok.body).toEqual({ type: "sale", effective_date: "2026-10-19", order_no: "LD1", tags: ["赠送", "大客户"], inputs: { gross: { amount: "1280.50", commodity: "CNY" }, channel: "liandong" } });
  });

  it("sends a book-local timestamp when a time is given", () => {
    const fields = fieldsFor(sale);
    const p = buildPayload({ ...base, type: sale, fields, time: "09:42", values: { gross: { amount: "1", commodity: "CNY" } } });
    expect(p.body.occurred_at).toBe("2026-10-19T09:42:00+08:00");
    expect(p.body.effective_date).toBeUndefined();
  });

  it("needs face or total for a credit purchase", () => {
    const fields = fieldsFor(purchase);
    expect(buildPayload({ ...base, type: purchase, fields, values: { credit_quantity: "50" } }).ready).toBe(false);
    expect(buildPayload({ ...base, type: purchase, fields, values: { total: { amount: "51.5", commodity: "CNY" } } }).ready).toBe(true);
  });

  it("builds journal lines and skips incomplete ones", () => {
    const lines = [
      { account: "5602.99", side: "debit" as const, amount: "10", commodity: "CNY", memo: "" },
      { account: "1012.01", side: "credit" as const, amount: "10", commodity: "CNY", memo: "" },
      { account: "", side: "debit" as const, amount: "3", commodity: "CNY", memo: "" },
    ];
    const p = buildPayload({ ...base, type: journal, fields: [], values: {}, lines });
    expect(p.ready).toBe(true);
    expect(p.body.lines).toHaveLength(2);
  });
});

describe("fieldErrors", () => {
  it("maps API error paths onto form fields", () => {
    const err = new ApiError(422, { detail: "x", errors: [{ path: "inputs.gross.amount", code: "INPUT_INVALID", message: "金额格式不对" }, { path: "counterparty", code: "NOT_FOUND", message: "往来方不存在" }] });
    expect(fieldErrors(err)).toEqual({ gross: "金额格式不对", counterparty: "往来方不存在" });
    expect(fieldErrors(new Error("x"))).toEqual({});
  });
});
