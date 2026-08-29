import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../context/ToastContext";
import type { LedgerProposal } from "../types/api";
import { AIQueryPanel } from "../views/AIQueryPanel";
import { AIWorkflowGuidance } from "../views/AIWorkflowGuidance";
import { AIWorkflowPreview } from "../views/AIWorkflowPreview";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AI query write boundary", () => {
  it("routes natural-language write intent to the slash workflow without a request", () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    render(
      <ToastProvider>
        <AIQueryPanel providerId="provider-1" />
      </ToastProvider>,
    );
    fireEvent.change(screen.getByPlaceholderText("输入账本查询"), {
      target: { value: "帮我记一笔 20 元支出" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(
      screen.getByText(
        "该请求涉及账本写入，请切换到“流程记账”并选择对应斜杠命令。",
      ),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("AI proposal preview", () => {
  it("renders the rule-derived amount relation and balanced journal", () => {
    const proposal: LedgerProposal = {
      id: "proposal-1",
      sequence: 1,
      operation: "create_expense",
      record_type: "expense",
      status: "ready",
      version: 1,
      fields: {
        cost: { value: "20.00", status: "source_exact" },
        fee: { value: "1.00", status: "source_exact" },
        cash: { value: "21.00", status: "rule_derived" },
      },
      validation: { valid: true, errors: [] },
      journal_preview: {
        balanced: true,
        lines: [
          {
            account_id: "expense",
            account_code: "6602",
            account_name: "管理费用",
            debit_cny: "20.00",
            credit_cny: "0.00",
          },
          {
            account_id: "cash",
            account_code: "1002",
            account_name: "银行存款",
            debit_cny: "0.00",
            credit_cny: "20.00",
          },
        ],
      },
      duplicate: { status: "clear", matches: [] },
      entity_versions: {},
      canonical_hash: "a".repeat(64),
    };
    render(<AIWorkflowPreview proposal={proposal} />);
    expect(screen.getByText("实际支付")).toBeInTheDocument();
    expect(screen.getByText("21.00")).toBeInTheDocument();
    expect(screen.getByText("全部规则通过")).toBeInTheDocument();
    expect(screen.getByText("未发现重复")).toBeInTheDocument();
  });
});

describe("AI workflow guidance", () => {
  it("renders clarifying questions and sends on Enter", () => {
    const onSend = vi.fn();
    render(
      <AIWorkflowGuidance
        messages={[
          {
            id: "message-1",
            sequence: 1,
            role: "assistant",
            content: "金额可以识别，日期仍需确认。",
            clarifying_questions: ["这笔支出发生在哪一天？"],
            created_at: "2026-08-29T00:00:00Z",
          },
        ]}
        value="日期是 2026-08-29"
        disabled={false}
        isSending={false}
        onChange={vi.fn()}
        onSend={onSend}
      />,
    );

    expect(
      screen.getByText("金额可以识别，日期仍需确认。"),
    ).toBeInTheDocument();
    expect(screen.getByText("这笔支出发生在哪一天？")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByLabelText("判断引导"), {
      key: "Enter",
      shiftKey: false,
    });
    expect(onSend).toHaveBeenCalledOnce();
  });
});
