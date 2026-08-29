import { describe, expect, it } from "vitest";
import {
  CURRENCIES,
  formatCurrencyAmount,
  getCurrencyOptionLabel,
  isCurrencyCode,
} from "../utils/currency";

describe("Currency utils", () => {
  it("defines the shared nine-currency set including HKD", () => {
    expect(CURRENCIES.map(({ code }) => code)).toEqual([
      "CNY",
      "USD",
      "GBP",
      "EUR",
      "HKD",
      "JPY",
      "KRW",
      "SGD",
      "PHP",
    ]);
    expect(isCurrencyCode("HKD")).toBe(true);
    expect(isCurrencyCode("BTC")).toBe(false);
  });

  it("formats symbols and keeps the ISO code when requested", () => {
    expect(formatCurrencyAmount("1234.5", "USD")).toBe("$1,234.50");
    expect(formatCurrencyAmount("1234.5", "HKD", { showCode: true })).toBe(
      "HKD HK$1,234.50",
    );
    expect(getCurrencyOptionLabel("JPY")).toBe("JP¥ JPY 日元");
  });
});
