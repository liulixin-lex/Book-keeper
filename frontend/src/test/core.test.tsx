import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "../components/ui/core";
import type { RecordRead } from "../types/api";
import {
  calculateFeeAmount,
  getPrimaryAmount,
  getPrimaryAmountCny,
  getStripeIncomeFeePreset,
  isStripeIncomeCategory,
  sortRecords,
} from "../utils/records";

describe("Badge Component", () => {
  it("renders badge children correctly", () => {
    render(<Badge variant="success">已过账</Badge>);
    expect(screen.getByText("已过账")).toBeDefined();
  });
});

describe("Record fee calculation", () => {
  it("supports fixed values, percentages, and combined fees", () => {
    expect(calculateFeeAmount("100", "amount", "2.75")).toBe("2.75");
    expect(calculateFeeAmount("100", "percent", "2.5")).toBe("2.5");
    expect(calculateFeeAmount("100", "percent", "0")).toBe("0");
    expect(calculateFeeAmount("100", "combined", "2.2", "0.35")).toBe("2.55");
    expect(calculateFeeAmount("100", "combined", "0", "0.35")).toBe("0.35");
  });

  it("recognizes the Stripe income category for its fee preset", () => {
    expect(isStripeIncomeCategory("Stripe收入")).toBe(true);
    expect(isStripeIncomeCategory(" stripe收入 ")).toBe(true);
    expect(isStripeIncomeCategory("其他业务收入")).toBe(false);
    expect(getStripeIncomeFeePreset("Stripe收入")).toEqual({
      currency: "USD",
      mode: "combined",
      value: "2.2",
      fixedValue: "0.35",
    });
    expect(getStripeIncomeFeePreset("其他业务收入")).toBeNull();
  });
});

const record = (id: string, category: string, amount: string): RecordRead => ({
  id,
  record_type: "income",
  status: "posted",
  accounting_date: id === "a" ? "2026-08-28" : "2026-08-29",
  date_precision: "day",
  description: `记录 ${id}`,
  recognition_method: "transaction",
  category_name: category,
  counterparty_id: null,
  counterparty_name: null,
  created_by_username: "测试用户",
  version: 1,
  amounts: [
    {
      role: "cash",
      currency: "CNY",
      amount,
      amount_cny: amount,
      derived: false,
    },
  ],
});

describe("Record table sorting", () => {
  it("sorts categories and numeric cash amounts", () => {
    const records = [record("a", "云服务", "20"), record("b", "收入", "100")];

    expect(
      sortRecords(records, "category", "asc").map((item) => item.id),
    ).toEqual(["b", "a"]);
    expect(
      sortRecords(records, "amount", "desc").map((item) => item.id),
    ).toEqual(["b", "a"]);
    expect(getPrimaryAmountCny(records[0])).toBe("20");
  });

  it("keeps the original currency amount for row display", () => {
    const foreignRecord = record("a", "海外收入", "10");
    foreignRecord.amounts[0] = {
      role: "cash",
      currency: "USD",
      amount: "10",
      amount_cny: "72",
      derived: false,
    };

    expect(getPrimaryAmount(foreignRecord)).toMatchObject({
      currency: "USD",
      amount: "10",
    });
    expect(getPrimaryAmountCny(foreignRecord)).toBe("72");
  });
});
