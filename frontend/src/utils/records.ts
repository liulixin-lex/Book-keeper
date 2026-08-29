import type { MoneyRead, RecordRead } from "../types/api";

export type FeeMode = "amount" | "percent" | "combined";
export type RecordSortKey =
  | "accounting_date"
  | "record_type"
  | "category"
  | "provider"
  | "description"
  | "external_id"
  | "amount";
export type SortDirection = "asc" | "desc";

const cleanDecimal = (value: number) =>
  value
    .toFixed(8)
    .replace(/\.0+$/, "")
    .replace(/(\.\d*?)0+$/, "$1");

export const calculateFeeAmount = (
  amount: string,
  mode: FeeMode,
  value: string,
  fixedValue = "",
) => {
  const base = Number(amount);
  const feeValue = Number(value);
  if (!Number.isFinite(base)) {
    return "0";
  }

  if (mode === "combined") {
    const fixedFee = Number(fixedValue);
    if (
      !Number.isFinite(feeValue) ||
      !Number.isFinite(fixedFee) ||
      feeValue < 0 ||
      fixedFee < 0
    ) {
      return "0";
    }
    return cleanDecimal((base * feeValue) / 100 + fixedFee);
  }

  if (!Number.isFinite(feeValue) || feeValue <= 0) return "0";
  return cleanDecimal(mode === "percent" ? (base * feeValue) / 100 : feeValue);
};

export const isStripeIncomeCategory = (name?: string) =>
  name?.trim().toLocaleLowerCase() === "stripe收入";

export const getStripeIncomeFeePreset = (categoryName?: string) =>
  isStripeIncomeCategory(categoryName)
    ? {
        currency: "USD",
        mode: "combined" as const,
        value: "2.2",
        fixedValue: "0.35",
      }
    : null;

const combineAmounts = (
  first: string,
  second: string,
  operation: "add" | "subtract",
) => {
  const firstValue = Number(first);
  const secondValue = Number(second);
  if (!Number.isFinite(firstValue) || !Number.isFinite(secondValue)) return "0";
  return cleanDecimal(
    operation === "add" ? firstValue + secondValue : firstValue - secondValue,
  );
};

export const addAmounts = (first: string, second: string) =>
  combineAmounts(first, second, "add");

export const subtractAmounts = (first: string, second: string) =>
  combineAmounts(first, second, "subtract");

export const getPrimaryAmount = (record: RecordRead): MoneyRead | undefined =>
  record.amounts.find((amount) => amount.role === "cash") ||
  record.amounts.find(
    (amount) => amount.role === "gross" || amount.role === "cost",
  ) ||
  record.amounts[0];

export const getPrimaryAmountCny = (record: RecordRead) =>
  getPrimaryAmount(record)?.amount_cny || "0";

const collator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

const sortValue = (record: RecordRead, key: RecordSortKey) => {
  if (key === "category") return record.category_name || "";
  if (key === "provider") return record.counterparty_name || "";
  if (key === "amount") return Number(getPrimaryAmountCny(record));
  return record[key] || "";
};

export const sortRecords = (
  records: RecordRead[],
  key: RecordSortKey,
  direction: SortDirection,
) =>
  records
    .map((record, index) => ({ record, index }))
    .sort((left, right) => {
      const leftValue = sortValue(left.record, key);
      const rightValue = sortValue(right.record, key);
      const comparison =
        typeof leftValue === "number" && typeof rightValue === "number"
          ? leftValue - rightValue
          : collator.compare(String(leftValue), String(rightValue));
      if (comparison === 0) return left.index - right.index;
      return direction === "asc" ? comparison : -comparison;
    })
    .map(({ record }) => record);
