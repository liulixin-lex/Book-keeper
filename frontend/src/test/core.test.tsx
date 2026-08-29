import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "../components/ui/core";
import type { RecordRead } from "../types/api";
import {
  calculateFeeAmount,
  getPrimaryAmountCny,
  sortRecords,
} from "../utils/records";

describe("Badge Component", () => {
  it("renders badge children correctly", () => {
    render(<Badge variant="success">已过账</Badge>);
    expect(screen.getByText("已过账")).toBeDefined();
  });
});

describe("Record fee calculation", () => {
  it("supports fixed values and percentages", () => {
    expect(calculateFeeAmount("100", "amount", "2.75")).toBe("2.75");
    expect(calculateFeeAmount("100", "percent", "2.5")).toBe("2.5");
    expect(calculateFeeAmount("100", "percent", "0")).toBe("0");
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
});
