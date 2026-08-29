import { describe, it, expect } from "vitest";
import { formatMoney } from "../utils/format";

describe("Format utils", () => {
  it("formats decimals string properly without float loss", () => {
    expect(formatMoney("12345.67")).toBe("12,345.67");
    expect(formatMoney("0.50")).toBe("0.50");
    expect(formatMoney("-1000.00")).toBe("-1,000.00");
    expect(formatMoney("12345.67890123")).toBe("12,345.67890123");
    expect(formatMoney(undefined)).toBe("0.00");
  });
});
