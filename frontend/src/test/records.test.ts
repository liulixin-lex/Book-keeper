import { describe, expect, it } from "vitest";
import { getIncomeFeePreset } from "../utils/records";

describe("income fee presets", () => {
  it("applies the configured percentages for income categories", () => {
    expect(getIncomeFeePreset("链动收入")).toMatchObject({
      mode: "percent",
      value: "3",
    });
    expect(getIncomeFeePreset("xorpay收入")).toMatchObject({
      mode: "percent",
      value: "1.6",
    });
  });

  it("keeps the existing Stripe combined fee preset", () => {
    expect(getIncomeFeePreset("Stripe收入")).toEqual({
      currency: "USD",
      mode: "combined",
      value: "2.2",
      fixedValue: "0.35",
    });
  });
});
