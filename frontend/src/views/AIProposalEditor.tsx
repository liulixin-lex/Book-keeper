import React, { useEffect, useMemo, useState } from "react";
import { Check, FloppyDisk, WarningCircle } from "@phosphor-icons/react";
import { Badge, Button, Input, Select } from "../components/ui/core";
import {
  Category,
  LedgerProposal,
  ProposalField,
  Provider,
} from "../types/api";

interface AIProposalEditorProps {
  proposal: LedgerProposal;
  providers: Provider[];
  categories: Category[];
  isSaving: boolean;
  onSave: (changes: Record<string, unknown>) => void;
}

const labels: Record<string, string> = {
  accounting_date: "日期",
  description: "摘要",
  currency: "币种",
  gross: "毛额",
  cost: "成本",
  fee: "手续费",
  net: "净到账",
  cash: "实际收付",
  amount_cny: "人民币金额",
  fx_rate: "汇率",
  channel: "渠道",
  provider_id: "提供商",
  category_id: "类别",
  external_id: "外部单号",
  record_id: "原记录 ID",
  reason: "原因",
};

const provenance: Record<
  string,
  { label: string; variant: "success" | "info" | "warning" | "danger" }
> = {
  source_exact: { label: "来源原值", variant: "success" },
  rule_derived: { label: "规则计算", variant: "info" },
  ai_inferred: { label: "AI 提取", variant: "warning" },
  missing: { label: "缺失", variant: "danger" },
  ambiguous: { label: "有歧义", variant: "danger" },
};

const editableFields = (proposal: LedgerProposal) => {
  if (proposal.operation === "reverse") return ["record_id", "reason"];
  const amountField = proposal.record_type === "income" ? "gross" : "cost";
  return [
    "accounting_date",
    "description",
    "currency",
    amountField,
    "fee",
    "amount_cny",
    "fx_rate",
    "channel",
    "provider_id",
    "category_id",
    "external_id",
  ];
};

const fieldValue = (field?: ProposalField) =>
  field?.value === null || field?.value === undefined
    ? ""
    : String(field.value);

export const AIProposalEditor: React.FC<AIProposalEditorProps> = ({
  proposal,
  providers,
  categories,
  isSaving,
  onSave,
}) => {
  const fields = useMemo(() => editableFields(proposal), [proposal]);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    setValues(
      Object.fromEntries(
        fields.map((name) => [name, fieldValue(proposal.fields[name])]),
      ),
    );
  }, [fields, proposal]);

  const changes = Object.fromEntries(
    fields
      .filter((name) => values[name] !== fieldValue(proposal.fields[name]))
      .map((name) => [name, values[name] || null]),
  );
  const expense = proposal.record_type === "expense";
  const eligibleCategories = categories.filter(
    (category) =>
      category.is_active &&
      (category.kind === proposal.record_type || category.kind === "both"),
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {fields.map((name) => {
          const field = proposal.fields[name];
          const source =
            provenance[field?.status || "missing"] || provenance.missing;
          const commonLabel = (
            <span className="flex items-center justify-between gap-2">
              <span>{labels[name] || name}</span>
              <Badge
                variant={source.variant}
                className="px-1.5 py-0 text-[10px]"
              >
                {source.label}
              </Badge>
            </span>
          );
          if (name === "provider_id") {
            return (
              <div key={name} className="space-y-1.5">
                <div className="text-xs font-medium text-muted">
                  {commonLabel}
                </div>
                <Select
                  value={values[name] || ""}
                  onChange={(event) =>
                    setValues((current) => ({
                      ...current,
                      [name]: event.target.value,
                      ...(expense ? { category_id: "" } : {}),
                    }))
                  }
                >
                  <option value="">未选择</option>
                  {providers
                    .filter((provider) => provider.is_active)
                    .map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.name}
                      </option>
                    ))}
                </Select>
              </div>
            );
          }
          if (name === "category_id") {
            return (
              <div key={name} className="space-y-1.5">
                <div className="text-xs font-medium text-muted">
                  {commonLabel}
                </div>
                <Select
                  value={values[name] || ""}
                  disabled={expense && !!values.provider_id}
                  onChange={(event) =>
                    setValues((current) => ({
                      ...current,
                      [name]: event.target.value,
                    }))
                  }
                >
                  <option value="">由规则确定</option>
                  {eligibleCategories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </Select>
              </div>
            );
          }
          return (
            <div
              key={name}
              className={
                name === "description" || name === "reason"
                  ? "sm:col-span-2"
                  : ""
              }
            >
              <Input
                label={labels[name] || name}
                type={name === "accounting_date" ? "date" : "text"}
                inputMode={
                  ["gross", "cost", "fee", "amount_cny", "fx_rate"].includes(
                    name,
                  )
                    ? "decimal"
                    : undefined
                }
                value={values[name] || ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [name]: event.target.value,
                  }))
                }
                helperText={source.label}
              />
            </div>
          );
        })}
      </div>

      {proposal.duplicate.requires_override && (
        <label className="flex items-start gap-2 rounded-lg border border-warning/35 bg-warning/10 p-3 text-xs text-ink">
          <input
            type="checkbox"
            checked={
              values.duplicate_override === "true" ||
              proposal.duplicate.override === true
            }
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                duplicate_override: String(event.target.checked),
              }))
            }
            className="mt-0.5 accent-warning"
          />
          <WarningCircle size={16} className="shrink-0 text-warning" />
          <span>仍作为新交易</span>
        </label>
      )}

      <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
        <div className="flex items-center gap-2 text-xs text-muted">
          {proposal.validation.valid ? (
            <>
              <Check size={15} className="text-success" />
              校验通过
            </>
          ) : (
            <>
              <WarningCircle size={15} className="text-warning" />
              {proposal.validation.errors?.length || 0} 项待处理
            </>
          )}
        </div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          isLoading={isSaving}
          disabled={
            Object.keys(changes).length === 0 &&
            values.duplicate_override === undefined
          }
          onClick={() =>
            onSave({
              ...changes,
              ...(values.duplicate_override !== undefined
                ? { duplicate_override: values.duplicate_override === "true" }
                : {}),
            })
          }
        >
          <FloppyDisk size={15} />
          保存修改
        </Button>
      </div>
    </div>
  );
};
