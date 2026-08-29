import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "../api/client";
import type { DashboardReportRead } from "../types/api";
import { OverviewView } from "../views/OverviewView";

vi.mock("../api/client", () => ({ apiRequest: vi.fn() }));
vi.mock("@gsap/react", () => ({ useGSAP: () => undefined }));
vi.mock("gsap", () => ({
  default: {
    registerPlugin: vi.fn(),
    to: (
      target: { val: number },
      options: {
        val: number;
        onUpdate?: () => void;
        onComplete?: () => void;
      },
    ) => {
      target.val = options.val;
      options.onUpdate?.();
      options.onComplete?.();
      return { kill: vi.fn() };
    },
  },
}));
vi.mock("recharts", () => ({
  Area: () => null,
  AreaChart: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  CartesianGrid: () => null,
  Legend: () => null,
  Line: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

const dashboard = (
  currency: "CNY" | "USD",
  options?: { stale?: boolean },
): DashboardReportRead => {
  const usd = currency === "USD";
  return {
    display_currency: currency,
    rate: {
      cny_per_unit: usd ? "7.2" : "1",
      source: usd ? "Frankfurter" : "fixed-rule",
      effective_at: "2026-08-29T00:00:00Z",
      fetched_at: "2026-08-29T12:00:00Z",
      is_stale: options?.stale || false,
    },
    overview: {
      start_date: "2026-08-23",
      end_date: "2026-08-29",
      gross_revenue: usd ? "50.00" : "360.00",
      channel_fees: usd ? "5.00" : "36.00",
      net_revenue: usd ? "45.00" : "324.00",
      operating_expenses: usd ? "10.00" : "72.00",
      operating_net: usd ? "35.00" : "252.00",
      cash_in: usd ? "45.00" : "324.00",
      cash_out: usd ? "10.00" : "72.00",
      net_cash: usd ? "35.00" : "252.00",
      posted_records: 2,
      expense_by_user: [
        {
          user_id: "user-1",
          username: "alice",
          amount: usd ? "10.00" : "72.00",
        },
      ],
    },
    daily: [
      {
        date: "2026-08-29",
        gross_revenue: usd ? "50.00" : "360.00",
        channel_fees: usd ? "5.00" : "36.00",
        net_revenue: usd ? "45.00" : "324.00",
        operating_expenses: usd ? "10.00" : "72.00",
        operating_net: usd ? "35.00" : "252.00",
        cash_in: usd ? "45.00" : "324.00",
        cash_out: usd ? "10.00" : "72.00",
        net_cash: usd ? "35.00" : "252.00",
      },
    ],
  };
};

const apiRequestMock = vi.mocked(apiRequest);

beforeEach(() => {
  window.localStorage.clear();
  apiRequestMock.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("Overview currency display", () => {
  it("restores a saved currency and renders every report surface in it", async () => {
    window.localStorage.setItem("ledger_overview_currency", "USD");
    apiRequestMock.mockResolvedValue(dashboard("USD", { stale: true }));

    render(<OverviewView />);

    const select = await screen.findByLabelText("总览显示币种");
    expect(select).toHaveValue("USD");
    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.stringContaining("display_currency=USD"),
    );
    expect(screen.getByText("1 USD = ¥7.20")).toBeInTheDocument();
    expect(screen.getByText("缓存汇率 2026-08-29")).toBeInTheDocument();
    expect(screen.getAllByText("$50.00").length).toBeGreaterThan(0);
    expect(window.localStorage.getItem("ledger_overview_currency")).toBe("USD");
  });

  it("falls back to the last successful currency after a failed switch", async () => {
    apiRequestMock
      .mockResolvedValueOnce(dashboard("CNY"))
      .mockRejectedValueOnce(new Error("Frankfurter 暂时不可用"))
      .mockResolvedValue(dashboard("CNY"));

    render(<OverviewView />);
    const select = await screen.findByLabelText("总览显示币种");
    await waitFor(() => expect(select).toHaveValue("CNY"));

    fireEvent.change(select, { target: { value: "USD" } });

    expect(
      await screen.findByText(/币种切换失败，已保留上一次成功的数据/),
    ).toBeInTheDocument();
    await waitFor(() => expect(select).toHaveValue("CNY"));
    expect(window.localStorage.getItem("ledger_overview_currency")).toBe("CNY");
  });

  it("ignores an invalid saved currency and starts from CNY", async () => {
    window.localStorage.setItem("ledger_overview_currency", "BTC");
    apiRequestMock.mockResolvedValue(dashboard("CNY"));

    render(<OverviewView />);

    await screen.findByLabelText("总览显示币种");
    expect(apiRequestMock).toHaveBeenCalledWith(
      expect.stringContaining("display_currency=CNY"),
    );
  });
});
