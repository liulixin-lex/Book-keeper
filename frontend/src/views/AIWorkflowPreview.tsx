import React from "react";
import {
  ArrowsLeftRight,
  CheckCircle,
  Copy,
  ListChecks,
  WarningCircle,
} from "@phosphor-icons/react";
import { Badge } from "../components/ui/core";
import { LedgerProposal } from "../types/api";

interface AIWorkflowPreviewProps {
  proposal?: LedgerProposal;
}

const amountValue = (proposal: LedgerProposal, field: string) => {
  const value = proposal.fields[field]?.value;
  return value === null || value === undefined || value === ""
    ? "-"
    : String(value);
};

export const AIWorkflowPreview: React.FC<AIWorkflowPreviewProps> = ({
  proposal,
}) => {
  if (!proposal) {
    return (
      <div className="flex min-h-72 items-center justify-center text-xs text-muted">
        暂无提案预览
      </div>
    );
  }

  const income = proposal.record_type === "income";
  const errors = proposal.validation.errors || [];
  const lines = proposal.journal_preview.lines || [];
  const duplicates = proposal.duplicate.matches || [];

  return (
    <div className="divide-y divide-border">
      <section className="space-y-3 p-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-xs font-semibold text-ink">
            <ArrowsLeftRight size={16} className="text-primary" />
            金额关系
          </h3>
          <Badge variant={proposal.validation.valid ? "success" : "warning"}>
            {proposal.validation.valid ? "已通过" : "待校验"}
          </Badge>
        </div>
        {proposal.operation === "reverse" ? (
          <div className="grid gap-2 text-xs">
            <div className="flex justify-between gap-3">
              <span className="text-muted">原记录</span>
              <span className="break-all text-right font-mono">
                {amountValue(proposal, "record_id")}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-muted">影响</span>
              <span>生成全额反向分录</span>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border text-center">
            <div className="bg-surface px-2 py-3">
              <div className="text-[10px] text-muted">
                {income ? "毛额" : "成本"}
              </div>
              <div className="mt-1 truncate font-mono text-sm font-semibold text-ink">
                {amountValue(proposal, income ? "gross" : "cost")}
              </div>
            </div>
            <div className="bg-surface px-2 py-3">
              <div className="text-[10px] text-muted">手续费</div>
              <div className="mt-1 truncate font-mono text-sm font-semibold text-ink">
                {amountValue(proposal, "fee")}
              </div>
            </div>
            <div className="bg-surface px-2 py-3">
              <div className="text-[10px] text-muted">
                {income ? "净到账" : "实际支付"}
              </div>
              <div className="mt-1 truncate font-mono text-sm font-semibold text-primary">
                {amountValue(proposal, "cash")}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="space-y-3 p-4">
        <h3 className="flex items-center gap-2 text-xs font-semibold text-ink">
          <ListChecks size={16} className="text-primary" />
          预计分录
        </h3>
        {lines.length > 0 ? (
          <div className="data-table-shell overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="bg-surface-inset text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">科目</th>
                  <th className="px-3 py-2 text-right font-medium">借</th>
                  <th className="px-3 py-2 text-right font-medium">贷</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {lines.map((line, index) => (
                  <tr
                    key={`${line.account_id}-${index}`}
                    className="hover:bg-surface-strong/50"
                  >
                    <td className="px-3 py-2">
                      <span className="font-mono text-muted">
                        {line.account_code}
                      </span>
                      <span className="ml-2 text-ink">{line.account_name}</span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {line.debit_cny === "0.00" ? "-" : line.debit_cny}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {line.credit_cny === "0.00" ? "-" : line.credit_cny}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-xs text-muted">校验后生成分录</div>
        )}
      </section>

      <section className="space-y-3 p-4">
        <h3 className="flex items-center gap-2 text-xs font-semibold text-ink">
          <Copy size={16} className="text-primary" />
          重复检查
        </h3>
        {duplicates.length > 0 ? (
          <div className="space-y-2">
            {duplicates.map((item) => (
              <div
                key={item.record_id}
                className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 p-2.5 text-xs"
              >
                <WarningCircle
                  size={15}
                  className="mt-0.5 shrink-0 text-warning"
                />
                <div className="min-w-0">
                  <div className="truncate text-ink">{item.description}</div>
                  <div className="truncate font-mono text-[10px] text-muted">
                    {item.record_id}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-muted">
            <CheckCircle size={15} className="text-success" />
            {proposal.duplicate.status === "clear" ? "未发现重复" : "等待检查"}
          </div>
        )}
      </section>

      <section className="space-y-3 p-4">
        <h3 className="text-xs font-semibold text-ink">校验结果</h3>
        {errors.length > 0 ? (
          <div className="space-y-2">
            {errors.map((error, index) => (
              <div
                key={`${error.field}-${error.code}-${index}`}
                className="flex items-start gap-2 text-xs text-danger"
              >
                <WarningCircle size={15} className="mt-0.5 shrink-0" />
                <span>
                  {error.field}: {error.message}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-muted">
            <CheckCircle size={15} className="text-success" />
            {proposal.validation.valid ? "全部规则通过" : "尚未执行校验"}
          </div>
        )}
      </section>
    </div>
  );
};
