import { describe, expect, it } from "vitest";
import { addDays, bookDate, dayLabel, formatMoney, monthEnd, moneyParts, parseAmount } from "./format";

describe("format", () => {
  it("splits money into sign, symbol and grouped digits", () => {
    expect(moneyParts({ minor: -1234567, commodity: "CNY" })).toEqual({ sign: "-", symbol: "¥", digits: "12,345.67", unit: "" });
    expect(moneyParts({ minor: 12450, commodity: "UCR" }, 0)).toEqual({ sign: "", symbol: "", digits: "12,450", unit: "UCR" });
  });

  it("prefers the server display and uses a true minus sign", () => {
    expect(formatMoney({ minor: -5150, commodity: "CNY", display: "-¥51.50" })).toBe("−¥51.50");
    expect(formatMoney({ minor: 380, commodity: "GBP" })).toBe("£3.80");
  });

  it("parses typed amounts into API decimals", () => {
    expect(parseAmount("1,234.5")).toBe("1234.5");
    expect(parseAmount("¥ 50")).toBe("50");
    expect(parseAmount("12.3.4")).toBeNull();
    expect(parseAmount("")).toBeNull();
  });

  it("does date arithmetic on ISO days", () => {
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(monthEnd("2026-02-10")).toBe("2026-02-28");
    expect(dayLabel("2026-10-18", "2026-10-19")).toBe("昨天");
    expect(dayLabel("2025-12-31", "2026-10-19")).toBe("2025-12-31");
  });

  it("takes the business day in the book timezone", () => {
    expect(bookDate(new Date("2026-10-18T16:30:00Z"))).toBe("2026-10-19");
  });
});
