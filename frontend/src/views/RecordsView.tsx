import React, { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  CaretLeft,
  CaretRight,
  MagnifyingGlass,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Button, Input, Select, Badge } from "../components/ui/core";
import { Drawer, Modal } from "../components/ui/modals";
import {
  EmptyState,
  ErrorState,
  TableSkeleton,
} from "../components/ui/feedback";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import type {
  Category,
  FxRate,
  MemberOption,
  Provider,
  RecordPageRead,
  RecordRead,
  RecordType,
} from "../types/api";
import { formatMoney } from "../utils/format";
import {
  addAmounts,
  calculateFeeAmount,
  getPrimaryAmountCny,
  subtractAmounts,
  type FeeMode,
} from "../utils/records";

interface RecordsViewProps {
  recordType: RecordType;
}

interface EntryFormData {
  accounting_date: string;
  description: string;
  external_id: string;
  amount: string;
  currency: string;
  fee_mode: FeeMode;
  fee_value: string;
  category_id: string;
  provider_id: string;
  note: string;
}

const CURRENCIES = [
  ["CNY", "人民币"],
  ["USD", "美元"],
  ["EUR", "欧元"],
  ["GBP", "英镑"],
  ["JPY", "日元"],
  ["KRW", "韩元"],
  ["SGD", "新加坡元"],
  ["PHP", "菲律宾比索"],
] as const;

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  pending_approval: "待审批",
  posted: "已过账",
  reversed: "已冲销",
};

const shanghaiToday = () => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return `${values.year}-${values.month}-${values.day}`;
};

const initialFormData = (): EntryFormData => ({
  accounting_date: shanghaiToday(),
  description: "",
  external_id: "",
  amount: "",
  currency: "CNY",
  fee_mode: "amount",
  fee_value: "",
  category_id: "",
  provider_id: "",
  note: "",
});

const emptyPage: RecordPageRead = {
  items: [],
  total: 0,
  total_amount_cny: "0",
  limit: 20,
  offset: 0,
};

const amountRoleLabel = (role: string) =>
  ({
    cash: "实际收付",
    gross: "毛收入",
    net: "实际到账",
    cost: "费用金额",
    fee: "手续费",
    refund: "退款金额",
  })[role] || role;

const RecordsView: React.FC<RecordsViewProps> = ({ recordType }) => {
  const isExpense = recordType === "expense";
  const { user } = useAuth();
  const { success, error: toastError } = useToast();
  const [pageData, setPageData] = useState<RecordPageRead>(emptyPage);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [categories, setCategories] = useState<Category[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [members, setMembers] = useState<MemberOption[]>([]);
  const [selectedRecord, setSelectedRecord] = useState<RecordRead | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [formData, setFormData] = useState<EntryFormData>(initialFormData);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const activeCategories = useMemo(
    () =>
      categories.filter(
        (category) =>
          category.is_active &&
          (category.kind === recordType || category.kind === "both"),
      ),
    [categories, recordType],
  );
  const activeProviders = useMemo(
    () => providers.filter((provider) => provider.is_active),
    [providers],
  );

  const fetchRecords = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams({
        record_type: recordType,
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
      });
      if (startDate) query.set("start_date", startDate);
      if (endDate) query.set("end_date", endDate);
      if (categoryFilter) query.set("category_id", categoryFilter);
      if (isExpense && userFilter) query.set("created_by_user_id", userFilter);
      if (deferredSearch.trim()) query.set("q", deferredSearch.trim());
      setPageData(await apiRequest<RecordPageRead>(`/records/page?${query}`));
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "加载明细失败",
      );
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchRecords();
  }, [
    recordType,
    page,
    pageSize,
    startDate,
    endDate,
    categoryFilter,
    userFilter,
    deferredSearch,
  ]);

  useEffect(() => {
    const requests: Promise<unknown>[] = [
      apiRequest<Category[]>("/catalog/categories?active_only=true").then(
        setCategories,
      ),
    ];
    if (isExpense) {
      requests.push(
        apiRequest<Provider[]>("/catalog/providers?active_only=true").then(
          setProviders,
        ),
        apiRequest<MemberOption[]>("/users/options").then(setMembers),
      );
    }
    void Promise.all(requests).catch(() => undefined);
  }, [isExpense]);

  const resetPage = () => setPage(1);
  const totalPages = Math.max(1, Math.ceil(pageData.total / pageSize));
  const feeAmount = calculateFeeAmount(
    formData.amount,
    formData.fee_mode,
    formData.fee_value,
  );
  const settledAmount = isExpense
    ? addAmounts(formData.amount || "0", feeAmount)
    : subtractAmounts(formData.amount || "0", feeAmount);

  const handleProviderChange = (providerId: string) => {
    const provider = activeProviders.find((item) => item.id === providerId);
    setFormData((current) => ({
      ...current,
      provider_id: providerId,
      category_id: provider?.expense_category_id || "",
    }));
  };

  const createRecord = async (event: React.FormEvent) => {
    event.preventDefault();
    const amount = Number(formData.amount);
    const fee = Number(feeAmount);
    if (
      !formData.description.trim() ||
      !Number.isFinite(amount) ||
      amount <= 0
    ) {
      toastError("请填写摘要和有效金额");
      return;
    }
    if (isExpense && !formData.provider_id) {
      toastError("请选择提供商");
      return;
    }
    if (!Number.isFinite(fee) || fee < 0 || (!isExpense && fee > amount)) {
      toastError("请检查手续费金额");
      return;
    }

    setIsSubmitting(true);
    try {
      const fxRate =
        formData.currency === "CNY"
          ? null
          : await apiRequest<FxRate>(
              `/catalog/fx-rates/fetch?currency=${encodeURIComponent(formData.currency)}&effective_date=${formData.accounting_date}`,
              { method: "POST" },
            );
      const money = (amountValue: string) => ({
        currency: formData.currency,
        amount: amountValue,
        ...(fxRate ? { fx_rate_id: fxRate.id } : {}),
      });
      const common = {
        accounting_date: formData.accounting_date,
        description: formData.description.trim(),
        external_id: formData.external_id || undefined,
        category_id: formData.category_id || undefined,
        note: formData.note || undefined,
        post: true,
      };
      if (isExpense) {
        await apiRequest("/records/expenses", {
          method: "POST",
          body: JSON.stringify({
            ...common,
            cost: money(formData.amount),
            fee: fee > 0 ? money(feeAmount) : undefined,
            cash: money(settledAmount),
            counterparty_id: formData.provider_id,
          }),
        });
      } else {
        await apiRequest("/records/income", {
          method: "POST",
          body: JSON.stringify({
            ...common,
            gross: money(formData.amount),
            fee: fee > 0 ? money(feeAmount) : undefined,
            cash_received: true,
          }),
        });
      }
      success(isExpense ? "支出录入成功" : "收入录入成功");
      setFormData(initialFormData());
      setIsCreateOpen(false);
      if (page !== 1) setPage(1);
      else await fetchRecords();
    } catch (requestError) {
      toastError(
        requestError instanceof Error ? requestError.message : "录入失败",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const deleteRecord = async (record: RecordRead) => {
    if (!confirm(`确定删除“${record.description}”吗？此操作无法恢复。`)) return;
    try {
      await apiRequest(`/records/${record.id}`, { method: "DELETE" });
      success("记录已删除");
      setSelectedRecord(null);
      if (pageData.items.length === 1 && page > 1) setPage(page - 1);
      else await fetchRecords();
    } catch (requestError) {
      toastError(
        requestError instanceof Error ? requestError.message : "删除失败",
      );
    }
  };

  const clearFilters = () => {
    setStartDate("");
    setEndDate("");
    setCategoryFilter("");
    setUserFilter("");
    setSearch("");
    setPage(1);
  };

  return (
    <div className="space-y-4">
      <section className="instrument-panel">
        <div className="flex flex-col gap-4 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-xs text-muted">
              当前筛选共 {pageData.total} 笔{isExpense ? "支出" : "收入"}
            </p>
            <p
              className={`mt-1 font-mono-amount text-2xl font-semibold ${isExpense ? "text-danger" : "text-success"}`}
            >
              ¥{formatMoney(pageData.total_amount_cny)}
            </p>
          </div>
          {user?.role !== "viewer" && (
            <Button size="sm" onClick={() => setIsCreateOpen(true)}>
              <Plus size={15} weight="bold" />
              录入{isExpense ? "支出" : "收入"}
            </Button>
          )}
        </div>

        <div className="instrument-strip grid gap-2 p-4 md:grid-cols-2 xl:grid-cols-[minmax(220px,1.5fr)_140px_140px_150px_150px_auto]">
          <div className="relative">
            <MagnifyingGlass
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            />
            <input
              aria-label="搜索明细"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                resetPage();
              }}
              placeholder="搜索摘要、类别、单号或用户"
              className="h-9 w-full rounded-lg border border-border bg-surface-inset shadow-control-inset pl-9 pr-3 text-xs text-ink placeholder:text-muted focus:border-primary focus:outline-none"
            />
          </div>
          <Select
            aria-label="按类别筛选"
            value={categoryFilter}
            onChange={(event) => {
              setCategoryFilter(event.target.value);
              resetPage();
            }}
            className="text-xs"
          >
            <option value="">全部类别</option>
            {activeCategories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
          {isExpense ? (
            <Select
              aria-label="按用户筛选"
              value={userFilter}
              onChange={(event) => {
                setUserFilter(event.target.value);
                resetPage();
              }}
              className="text-xs"
            >
              <option value="">全部用户</option>
              {members.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.username}
                </option>
              ))}
            </Select>
          ) : (
            <div className="hidden xl:block" />
          )}
          <input
            aria-label="开始日期"
            type="date"
            value={startDate}
            onChange={(event) => {
              setStartDate(event.target.value);
              resetPage();
            }}
            className="h-9 rounded-lg border border-border bg-surface-inset shadow-control-inset px-2 text-xs text-ink focus:border-primary focus:outline-none"
          />
          <input
            aria-label="结束日期"
            type="date"
            value={endDate}
            min={startDate || undefined}
            onChange={(event) => {
              setEndDate(event.target.value);
              resetPage();
            }}
            className="h-9 rounded-lg border border-border bg-surface-inset shadow-control-inset px-2 text-xs text-ink focus:border-primary focus:outline-none"
          />
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearFilters}
          >
            清空筛选
          </Button>
        </div>
      </section>

      <section className="data-table-shell">
        {isLoading ? (
          <TableSkeleton rows={pageSize > 20 ? 12 : pageSize} cols={8} />
        ) : error ? (
          <ErrorState message={error} onRetry={() => void fetchRecords()} />
        ) : pageData.items.length === 0 ? (
          <EmptyState
            title={`暂无${isExpense ? "支出" : "收入"}明细`}
            description="调整筛选条件，或录入第一笔数据。"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-xs">
              <thead className="border-b border-border bg-surface-inset text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">记账日期</th>
                  <th className="px-4 py-3 font-medium">用户</th>
                  <th className="px-4 py-3 font-medium">类别</th>
                  {isExpense && (
                    <th className="px-4 py-3 font-medium">提供商</th>
                  )}
                  <th className="px-4 py-3 font-medium">摘要</th>
                  <th className="px-4 py-3 font-medium">外部单号</th>
                  <th className="px-4 py-3 text-right font-medium">
                    {isExpense ? "实际支出" : "实际到账"}
                  </th>
                  <th className="px-4 py-3 text-center font-medium">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/70">
                {pageData.items.map((record) => (
                  <tr
                    key={record.id}
                    onClick={() => setSelectedRecord(record)}
                    className="cursor-pointer hover:bg-surface-strong/50"
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-ink">
                      {record.accounting_date}
                    </td>
                    <td className="max-w-36 truncate px-4 py-3 font-medium text-ink">
                      {record.created_by_username}
                    </td>
                    <td className="max-w-40 truncate px-4 py-3 text-muted">
                      {record.category_name || "未分类"}
                    </td>
                    {isExpense && (
                      <td className="max-w-40 truncate px-4 py-3 text-muted">
                        {record.counterparty_name || "-"}
                      </td>
                    )}
                    <td className="max-w-64 truncate px-4 py-3 font-medium text-ink">
                      {record.description}
                    </td>
                    <td className="max-w-40 truncate px-4 py-3 font-mono text-muted">
                      {record.external_id || "-"}
                    </td>
                    <td
                      className={`whitespace-nowrap px-4 py-3 text-right font-mono-amount font-semibold ${isExpense ? "text-danger" : "text-success"}`}
                    >
                      ¥{formatMoney(getPrimaryAmountCny(record))}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <Badge
                        variant={
                          record.status === "posted"
                            ? "success"
                            : record.status === "reversed"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {STATUS_LABELS[record.status] || record.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex flex-col gap-3 border-t border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <label className="flex items-center gap-2 text-xs text-muted">
            每页
            <select
              value={pageSize}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(1);
              }}
              className="h-8 rounded-lg border border-border bg-surface-inset shadow-control-inset px-2 text-xs text-ink"
            >
              {[20, 50, 100, 200].map((size) => (
                <option key={size} value={size}>
                  {size} 条
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-1 text-xs text-muted">
              第 {page} / {totalPages} 页
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="上一页"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              <CaretLeft size={15} />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="下一页"
              disabled={page >= totalPages}
              onClick={() =>
                setPage((current) => Math.min(totalPages, current + 1))
              }
            >
              <CaretRight size={15} />
            </Button>
          </div>
        </div>
      </section>

      <Modal
        isOpen={isCreateOpen}
        onClose={() => !isSubmitting && setIsCreateOpen(false)}
        title={`录入${isExpense ? "支出" : "收入"}`}
        maxWidth="2xl"
      >
        <form onSubmit={createRecord} className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="记账日期 *"
              type="date"
              value={formData.accounting_date}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  accounting_date: event.target.value,
                }))
              }
              required
            />
            <Input
              label="摘要 *"
              value={formData.description}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
              required
            />
            <Input
              label={`${isExpense ? "费用" : "毛收入"}金额 *`}
              type="number"
              min="0.00000001"
              step="any"
              value={formData.amount}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  amount: event.target.value,
                }))
              }
              required
            />
            <Select
              label="币种 *"
              value={formData.currency}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  currency: event.target.value,
                }))
              }
            >
              {CURRENCIES.map(([code, name]) => (
                <option key={code} value={code}>
                  {code} · {name}
                </option>
              ))}
            </Select>
            {isExpense && (
              <Select
                label="提供商 *"
                value={formData.provider_id}
                onChange={(event) => handleProviderChange(event.target.value)}
                required
              >
                <option value="">请选择提供商</option>
                {activeProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </Select>
            )}
            <Select
              label="类别"
              value={formData.category_id}
              disabled={isExpense && Boolean(formData.provider_id)}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  category_id: event.target.value,
                }))
              }
            >
              <option value="">使用默认类别</option>
              {activeCategories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </Select>
            <Select
              label="手续费方式"
              value={formData.fee_mode}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  fee_mode: event.target.value as FeeMode,
                }))
              }
            >
              <option value="amount">固定金额</option>
              <option value="percent">按比例</option>
            </Select>
            <Input
              label={
                formData.fee_mode === "percent"
                  ? "手续费比例 (%)"
                  : "手续费金额"
              }
              type="number"
              min="0"
              max={formData.fee_mode === "percent" ? "100" : undefined}
              step="any"
              value={formData.fee_value}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  fee_value: event.target.value,
                }))
              }
            />
            <Input
              label="外部单号"
              value={formData.external_id}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  external_id: event.target.value,
                }))
              }
            />
          </div>
          <div className="instrument-inset p-3 text-xs text-muted">
            {isExpense ? "实际支出" : "实际到账"}：
            <strong className="ml-2 font-mono-amount text-ink">
              {formData.currency} {formatMoney(settledAmount)}
            </strong>
          </div>
          <label className="block space-y-1.5 text-xs font-medium text-muted">
            备注
            <textarea
              rows={3}
              value={formData.note}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  note: event.target.value,
                }))
              }
              className="w-full resize-none rounded-lg border border-border bg-surface-inset shadow-control-inset px-3 py-2 text-sm text-ink focus:border-primary focus:outline-none"
            />
          </label>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setIsCreateOpen(false)}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button type="submit" size="sm" isLoading={isSubmitting}>
              确认录入
            </Button>
          </div>
        </form>
      </Modal>

      <Drawer
        isOpen={Boolean(selectedRecord)}
        onClose={() => setSelectedRecord(null)}
        title="明细详情"
      >
        {selectedRecord && (
          <div className="space-y-5 text-sm">
            <dl className="grid grid-cols-[96px_minmax(0,1fr)] gap-x-4 gap-y-3">
              <dt className="text-muted">记账用户</dt>
              <dd className="font-medium text-ink">
                {selectedRecord.created_by_username}
              </dd>
              <dt className="text-muted">记账日期</dt>
              <dd className="text-ink">{selectedRecord.accounting_date}</dd>
              <dt className="text-muted">类别</dt>
              <dd className="text-ink">
                {selectedRecord.category_name || "未分类"}
              </dd>
              {isExpense && (
                <>
                  <dt className="text-muted">提供商</dt>
                  <dd className="text-ink">
                    {selectedRecord.counterparty_name || "-"}
                  </dd>
                </>
              )}
              <dt className="text-muted">摘要</dt>
              <dd className="break-words text-ink">
                {selectedRecord.description}
              </dd>
              <dt className="text-muted">外部单号</dt>
              <dd className="break-all font-mono text-xs text-ink">
                {selectedRecord.external_id || "-"}
              </dd>
              <dt className="text-muted">状态</dt>
              <dd className="text-ink">
                {STATUS_LABELS[selectedRecord.status]}
              </dd>
            </dl>
            <div className="border-t border-border pt-4">
              <h4 className="mb-2 text-xs font-semibold text-ink">金额组成</h4>
              <div className="divide-y divide-border rounded-lg border border-border">
                {selectedRecord.amounts.map((amount) => (
                  <div
                    key={`${amount.role}-${amount.currency}`}
                    className="flex items-center justify-between gap-4 px-3 py-2.5 text-xs"
                  >
                    <span className="text-muted">
                      {amountRoleLabel(amount.role)}
                    </span>
                    <span className="font-mono-amount font-medium text-ink">
                      {amount.currency} {formatMoney(amount.amount)}
                      {amount.currency !== "CNY" && (
                        <span className="ml-2 text-muted">
                          ¥{formatMoney(amount.amount_cny)}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            {selectedRecord.note && (
              <div className="border-t border-border pt-4">
                <h4 className="mb-2 text-xs font-semibold text-ink">备注</h4>
                <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted">
                  {selectedRecord.note}
                </p>
              </div>
            )}
            {user?.role !== "viewer" && (
              <div className="flex justify-end border-t border-border pt-4">
                <Button
                  type="button"
                  variant="danger"
                  size="sm"
                  onClick={() => void deleteRecord(selectedRecord)}
                >
                  <Trash size={15} />
                  删除记录
                </Button>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </div>
  );
};

export const IncomeRecordsView = () => <RecordsView recordType="income" />;
export const ExpenseRecordsView = () => <RecordsView recordType="expense" />;
