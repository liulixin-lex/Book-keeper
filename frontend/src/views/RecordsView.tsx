import React, { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  CaretLeft,
  CaretRight,
  CheckSquare,
  MagnifyingGlass,
  PencilSimple,
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
import {
  CURRENCIES,
  formatCurrencyAmount,
  getCurrencyOptionLabel,
} from "../utils/currency";
import { formatMoney } from "../utils/format";
import {
  addAmounts,
  calculateFeeAmount,
  getPrimaryAmount,
  getIncomeFeePreset,
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
  fee_fixed_value: string;
  category_id: string;
  provider_id: string;
  source_channel: string;
  note: string;
}

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
  fee_fixed_value: "",
  category_id: "",
  provider_id: "",
  source_channel: "",
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

const amountByRole = (record: RecordRead, role: string) =>
  record.amounts.find((amount) => amount.role === role);

const formFromRecord = (
  record: RecordRead,
  isExpense: boolean,
): EntryFormData => {
  const amount = amountByRole(record, isExpense ? "cost" : "gross");
  const fee = amountByRole(record, "fee");
  return {
    accounting_date: record.accounting_date,
    description: record.description,
    external_id: record.external_id || "",
    amount: amount?.amount || "",
    currency: amount?.currency || "CNY",
    fee_mode: "amount",
    fee_value: fee?.amount === "0.00" ? "" : fee?.amount || "",
    fee_fixed_value: "",
    category_id: record.category_id || "",
    provider_id: record.counterparty_id || "",
    source_channel: record.source_channel || "",
    note: record.note || "",
  };
};

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
  const [editingRecord, setEditingRecord] = useState<RecordRead | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isBatchOpen, setIsBatchOpen] = useState(false);
  const [batchForms, setBatchForms] = useState<EntryFormData[]>([
    initialFormData(),
  ]);
  const [formData, setFormData] = useState<EntryFormData>(initialFormData);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isBatchSubmitting, setIsBatchSubmitting] = useState(false);
  const [isBatchDeleting, setIsBatchDeleting] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

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
      setSelectedIds(new Set());
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
    formData.fee_fixed_value,
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

  const handleCategoryChange = (categoryId: string) => {
    const category = activeCategories.find((item) => item.id === categoryId);
    const feePreset = isExpense ? null : getIncomeFeePreset(category?.name);
    setFormData((current) => ({
      ...current,
      category_id: categoryId,
      ...(feePreset
        ? {
            ...(feePreset.currency ? { currency: feePreset.currency } : {}),
            fee_mode: feePreset.mode,
            fee_value: feePreset.value,
            fee_fixed_value: feePreset.fixedValue,
          }
        : {}),
    }));
  };

  const openCreate = () => {
    if (activeCategories.length === 0) {
      toastError(`请先在主数据管理中添加${isExpense ? "支出" : "收入"}类别`);
      return;
    }
    if (isExpense && activeProviders.length === 0) {
      toastError("请先在主数据管理中添加提供商");
      return;
    }
    setEditingRecord(null);
    setFormData(initialFormData());
    setIsCreateOpen(true);
  };

  const openBatchCreate = () => {
    if (activeCategories.length === 0) {
      toastError(`请先在主数据管理中添加${isExpense ? "支出" : "收入"}类别`);
      return;
    }
    if (isExpense && activeProviders.length === 0) {
      toastError("请先在主数据管理中添加提供商");
      return;
    }
    setBatchForms([initialFormData()]);
    setIsBatchOpen(true);
  };

  const openEdit = (record: RecordRead) => {
    setEditingRecord(record);
    setFormData(formFromRecord(record, isExpense));
    setSelectedRecord(null);
    setIsCreateOpen(true);
  };

  const validateForm = (data: EntryFormData, rowLabel = "") => {
    const amount = Number(data.amount);
    const fee = Number(
      calculateFeeAmount(
        data.amount,
        data.fee_mode,
        data.fee_value,
        data.fee_fixed_value,
      ),
    );
    const prefix = rowLabel ? `${rowLabel}：` : "";
    if (!data.description.trim() || !Number.isFinite(amount) || amount <= 0) {
      throw new Error(`${prefix}请填写摘要和有效金额`);
    }
    if (isExpense && !data.provider_id) {
      throw new Error(`${prefix}请选择提供商`);
    }
    if (!data.category_id) {
      throw new Error(`${prefix}请选择类别`);
    }
    if (!Number.isFinite(fee) || fee < 0 || (!isExpense && fee > amount)) {
      throw new Error(`${prefix}请检查手续费金额`);
    }
  };

  const buildPayload = async (
    data: EntryFormData,
    expectedVersion?: number,
    rowLabel = "",
  ) => {
    validateForm(data, rowLabel);
    const calculatedFee = calculateFeeAmount(
      data.amount,
      data.fee_mode,
      data.fee_value,
      data.fee_fixed_value,
    );
    const fee = Number(calculatedFee);
    const settled = isExpense
      ? addAmounts(data.amount || "0", calculatedFee)
      : subtractAmounts(data.amount || "0", calculatedFee);
    const fxRate =
      data.currency === "CNY"
        ? null
        : await apiRequest<FxRate>(
            `/catalog/fx-rates/fetch?currency=${encodeURIComponent(data.currency)}&effective_date=${data.accounting_date}`,
            { method: "POST" },
          );
    const money = (amountValue: string) => ({
      currency: data.currency,
      amount: amountValue,
      ...(fxRate ? { fx_rate_id: fxRate.id } : {}),
    });
    const common = {
      accounting_date: data.accounting_date,
      description: data.description.trim(),
      external_id: data.external_id || undefined,
      category_id: data.category_id,
      note: data.note || undefined,
      ...(expectedVersion ? { expected_version: expectedVersion } : {}),
      post: true,
    };
    return isExpense
      ? {
          ...common,
          cost: money(data.amount),
          fee: fee > 0 ? money(calculatedFee) : undefined,
          cash: money(settled),
          counterparty_id: data.provider_id,
          source_channel: data.source_channel || undefined,
        }
      : {
          ...common,
          gross: money(data.amount),
          fee: fee > 0 ? money(calculatedFee) : undefined,
          channel: data.source_channel || undefined,
          cash_received: true,
        };
  };

  const submitRecord = async (event: React.FormEvent) => {
    event.preventDefault();

    setIsSubmitting(true);
    try {
      const payload = await buildPayload(formData, editingRecord?.version);
      const path = editingRecord
        ? `/records/${editingRecord.id}/${isExpense ? "expense" : "income"}`
        : isExpense
          ? "/records/expenses"
          : "/records/income";
      await apiRequest(path, {
        method: editingRecord ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      success(
        editingRecord
          ? `${isExpense ? "支出" : "收入"}记录已更新`
          : `${isExpense ? "支出" : "收入"}录入成功`,
      );
      setFormData(initialFormData());
      setEditingRecord(null);
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

  const updateBatchForm = (index: number, changes: Partial<EntryFormData>) => {
    setBatchForms((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, ...changes } : item,
      ),
    );
  };

  const handleBatchCategoryChange = (index: number, categoryId: string) => {
    const category = activeCategories.find((item) => item.id === categoryId);
    const feePreset = isExpense ? null : getIncomeFeePreset(category?.name);
    updateBatchForm(index, {
      category_id: categoryId,
      ...(feePreset
        ? {
            ...(feePreset.currency ? { currency: feePreset.currency } : {}),
            fee_mode: feePreset.mode,
            fee_value: feePreset.value,
            fee_fixed_value: feePreset.fixedValue,
          }
        : {}),
    });
  };

  const handleBatchProviderChange = (index: number, providerId: string) => {
    const provider = activeProviders.find((item) => item.id === providerId);
    updateBatchForm(index, {
      provider_id: providerId,
      category_id: provider?.expense_category_id || "",
    });
  };

  const addBatchRow = () => {
    setBatchForms((current) => {
      const previous = current[current.length - 1] || initialFormData();
      return [
        ...current,
        {
          ...initialFormData(),
          accounting_date: previous.accounting_date,
          currency: previous.currency,
          category_id: previous.category_id,
          provider_id: previous.provider_id,
        },
      ];
    });
  };

  const submitBatch = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsBatchSubmitting(true);
    try {
      const items = await Promise.all(
        batchForms.map((item, index) =>
          buildPayload(item, undefined, `第 ${index + 1} 条`),
        ),
      );
      await apiRequest(
        isExpense ? "/records/expenses/batch" : "/records/income/batch",
        {
          method: "POST",
          body: JSON.stringify({ items }),
        },
      );
      success(`已批量录入 ${items.length} 条${isExpense ? "支出" : "收入"}`);
      setIsBatchOpen(false);
      setBatchForms([initialFormData()]);
      if (page !== 1) setPage(1);
      else await fetchRecords();
    } catch (requestError) {
      toastError(
        requestError instanceof Error ? requestError.message : "批量录入失败",
      );
    } finally {
      setIsBatchSubmitting(false);
    }
  };

  const deleteSelectedRecords = async () => {
    if (selectedIds.size === 0) return;
    if (
      !confirm(`确定删除选中的 ${selectedIds.size} 条记录吗？此操作无法恢复。`)
    )
      return;
    setIsBatchDeleting(true);
    try {
      const result = await apiRequest<{ deleted_count: number }>(
        "/records/batch-delete",
        {
          method: "POST",
          body: JSON.stringify({ record_ids: Array.from(selectedIds) }),
        },
      );
      success(`已删除 ${result.deleted_count} 条记录`);
      setSelectedIds(new Set());
      if (selectedIds.size >= pageData.items.length && page > 1) {
        setPage(page - 1);
      } else {
        await fetchRecords();
      }
    } catch (requestError) {
      toastError(
        requestError instanceof Error ? requestError.message : "批量删除失败",
      );
    } finally {
      setIsBatchDeleting(false);
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

  const allPageSelected =
    pageData.items.length > 0 &&
    pageData.items.every((record) => selectedIds.has(record.id));

  const toggleRecordSelection = (recordId: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(recordId)) next.delete(recordId);
      else next.add(recordId);
      return next;
    });
  };

  const togglePageSelection = () => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allPageSelected) {
        pageData.items.forEach((record) => next.delete(record.id));
      } else {
        pageData.items.forEach((record) => next.add(record.id));
      }
      return next;
    });
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
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="secondary" onClick={openBatchCreate}>
                <CheckSquare size={15} />
                批量录入
              </Button>
              <Button size="sm" onClick={openCreate}>
                <Plus size={15} weight="bold" />
                录入{isExpense ? "支出" : "收入"}
              </Button>
            </div>
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
        {user?.role !== "viewer" && selectedIds.size > 0 && (
          <div className="flex flex-col gap-2 border-b border-border bg-surface-strong/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <span className="text-xs font-medium text-ink">
              已选择 {selectedIds.size} 条记录
            </span>
            <Button
              type="button"
              variant="danger"
              size="sm"
              isLoading={isBatchDeleting}
              onClick={() => void deleteSelectedRecords()}
            >
              <Trash size={15} />
              批量删除
            </Button>
          </div>
        )}
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
                  {user?.role !== "viewer" && (
                    <th className="w-12 px-4 py-3 text-center font-medium">
                      <input
                        type="checkbox"
                        aria-label="选择当前页全部记录"
                        checked={allPageSelected}
                        onChange={togglePageSelection}
                        className="size-4 rounded border-border accent-primary"
                      />
                    </th>
                  )}
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
                  {user?.role !== "viewer" && (
                    <th className="w-14 px-4 py-3 text-center font-medium">
                      操作
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/70">
                {pageData.items.map((record) => {
                  const primaryAmount = getPrimaryAmount(record);
                  return (
                    <tr
                      key={record.id}
                      onClick={() => setSelectedRecord(record)}
                      className="cursor-pointer hover:bg-surface-strong/50"
                    >
                      {user?.role !== "viewer" && (
                        <td
                          className="px-4 py-3 text-center"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            aria-label={`选择记录 ${record.description}`}
                            checked={selectedIds.has(record.id)}
                            onChange={() => toggleRecordSelection(record.id)}
                            className="size-4 rounded border-border accent-primary"
                          />
                        </td>
                      )}
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
                        {primaryAmount
                          ? formatCurrencyAmount(
                              primaryAmount.amount,
                              primaryAmount.currency,
                              { showCode: true },
                            )
                          : "-"}
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
                      {user?.role !== "viewer" && (
                        <td
                          className="px-4 py-3 text-center"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <button
                            type="button"
                            aria-label={`编辑记录 ${record.description}`}
                            title="编辑记录"
                            onClick={() => openEdit(record)}
                            className="inline-flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-strong hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                          >
                            <PencilSimple size={16} />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
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
        onClose={() => {
          if (isSubmitting) return;
          setIsCreateOpen(false);
          setEditingRecord(null);
        }}
        title={`${editingRecord ? "编辑" : "录入"}${isExpense ? "支出" : "收入"}`}
        maxWidth="2xl"
      >
        <form onSubmit={submitRecord} className="space-y-5">
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
              {CURRENCIES.map(({ code }) => (
                <option key={code} value={code}>
                  {getCurrencyOptionLabel(code)}
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
              label="类别 *"
              value={formData.category_id}
              disabled={isExpense && Boolean(formData.provider_id)}
              onChange={(event) => handleCategoryChange(event.target.value)}
              required
            >
              <option value="">请选择类别</option>
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
              {!isExpense && <option value="combined">比例 + 固定金额</option>}
            </Select>
            <Input
              label={
                formData.fee_mode === "percent" ||
                formData.fee_mode === "combined"
                  ? "手续费比例 (%)"
                  : "手续费金额"
              }
              type="number"
              min="0"
              max={formData.fee_mode !== "amount" ? "100" : undefined}
              step="any"
              value={formData.fee_value}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  fee_value: event.target.value,
                }))
              }
            />
            {!isExpense && formData.fee_mode === "combined" && (
              <Input
                label={`固定手续费金额 (${formData.currency})`}
                type="number"
                min="0"
                step="any"
                value={formData.fee_fixed_value}
                onChange={(event) =>
                  setFormData((current) => ({
                    ...current,
                    fee_fixed_value: event.target.value,
                  }))
                }
              />
            )}
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
            <Input
              label="来源渠道"
              value={formData.source_channel}
              onChange={(event) =>
                setFormData((current) => ({
                  ...current,
                  source_channel: event.target.value,
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
              onClick={() => {
                setIsCreateOpen(false);
                setEditingRecord(null);
              }}
              disabled={isSubmitting}
            >
              取消
            </Button>
            <Button type="submit" size="sm" isLoading={isSubmitting}>
              {editingRecord ? "保存修改" : "确认录入"}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={isBatchOpen}
        onClose={() => !isBatchSubmitting && setIsBatchOpen(false)}
        title={`批量录入${isExpense ? "支出" : "收入"}`}
        maxWidth="4xl"
      >
        <form onSubmit={submitBatch} className="space-y-4">
          <div className="divide-y divide-border rounded-lg border border-border">
            {batchForms.map((item, index) => {
              const rowFee = calculateFeeAmount(
                item.amount,
                item.fee_mode,
                item.fee_value,
                item.fee_fixed_value,
              );
              const rowSettled = isExpense
                ? addAmounts(item.amount || "0", rowFee)
                : subtractAmounts(item.amount || "0", rowFee);
              return (
                <section key={index} className="space-y-3 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-xs font-semibold text-ink">
                      第 {index + 1} 条
                    </h4>
                    {batchForms.length > 1 && (
                      <button
                        type="button"
                        aria-label={`删除第 ${index + 1} 条`}
                        title="删除此行"
                        onClick={() =>
                          setBatchForms((current) =>
                            current.filter(
                              (_, itemIndex) => itemIndex !== index,
                            ),
                          )
                        }
                        className="inline-flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-danger/10 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
                      >
                        <Trash size={15} />
                      </button>
                    )}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <Input
                      id={`batch-date-${index}`}
                      label="记账日期 *"
                      type="date"
                      value={item.accounting_date}
                      onChange={(event) =>
                        updateBatchForm(index, {
                          accounting_date: event.target.value,
                        })
                      }
                      required
                    />
                    <Input
                      id={`batch-description-${index}`}
                      label="摘要 *"
                      value={item.description}
                      maxLength={500}
                      onChange={(event) =>
                        updateBatchForm(index, {
                          description: event.target.value,
                        })
                      }
                      required
                    />
                    <Input
                      id={`batch-amount-${index}`}
                      label={`${isExpense ? "费用" : "毛收入"}金额 *`}
                      type="number"
                      min="0.00000001"
                      step="any"
                      value={item.amount}
                      onChange={(event) =>
                        updateBatchForm(index, { amount: event.target.value })
                      }
                      required
                    />
                    <Select
                      id={`batch-currency-${index}`}
                      label="币种 *"
                      value={item.currency}
                      onChange={(event) =>
                        updateBatchForm(index, { currency: event.target.value })
                      }
                    >
                      {CURRENCIES.map(({ code }) => (
                        <option key={code} value={code}>
                          {getCurrencyOptionLabel(code)}
                        </option>
                      ))}
                    </Select>
                    {isExpense && (
                      <Select
                        id={`batch-provider-${index}`}
                        label="提供商 *"
                        value={item.provider_id}
                        onChange={(event) =>
                          handleBatchProviderChange(index, event.target.value)
                        }
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
                      id={`batch-category-${index}`}
                      label="类别 *"
                      value={item.category_id}
                      disabled={isExpense && Boolean(item.provider_id)}
                      onChange={(event) =>
                        handleBatchCategoryChange(index, event.target.value)
                      }
                      required
                    >
                      <option value="">请选择类别</option>
                      {activeCategories.map((category) => (
                        <option key={category.id} value={category.id}>
                          {category.name}
                        </option>
                      ))}
                    </Select>
                    <Select
                      id={`batch-fee-mode-${index}`}
                      label="手续费方式"
                      value={item.fee_mode}
                      onChange={(event) =>
                        updateBatchForm(index, {
                          fee_mode: event.target.value as FeeMode,
                        })
                      }
                    >
                      <option value="amount">固定金额</option>
                      <option value="percent">按比例</option>
                      {!isExpense && (
                        <option value="combined">比例 + 固定金额</option>
                      )}
                    </Select>
                    <Input
                      id={`batch-fee-${index}`}
                      label={
                        item.fee_mode === "amount"
                          ? "手续费金额"
                          : "手续费比例 (%)"
                      }
                      type="number"
                      min="0"
                      max={item.fee_mode === "amount" ? undefined : "100"}
                      step="any"
                      value={item.fee_value}
                      onChange={(event) =>
                        updateBatchForm(index, {
                          fee_value: event.target.value,
                        })
                      }
                    />
                    {!isExpense && item.fee_mode === "combined" && (
                      <Input
                        id={`batch-fixed-fee-${index}`}
                        label={`固定手续费 (${item.currency})`}
                        type="number"
                        min="0"
                        step="any"
                        value={item.fee_fixed_value}
                        onChange={(event) =>
                          updateBatchForm(index, {
                            fee_fixed_value: event.target.value,
                          })
                        }
                      />
                    )}
                    <Input
                      id={`batch-channel-${index}`}
                      label="来源渠道"
                      value={item.source_channel}
                      maxLength={80}
                      onChange={(event) =>
                        updateBatchForm(index, {
                          source_channel: event.target.value,
                        })
                      }
                    />
                    <Input
                      id={`batch-external-${index}`}
                      label="外部单号"
                      value={item.external_id}
                      maxLength={240}
                      onChange={(event) =>
                        updateBatchForm(index, {
                          external_id: event.target.value,
                        })
                      }
                    />
                  </div>
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                    <label className="min-w-0 flex-1 space-y-1.5 text-xs font-medium text-muted">
                      备注
                      <textarea
                        rows={2}
                        value={item.note}
                        onChange={(event) =>
                          updateBatchForm(index, { note: event.target.value })
                        }
                        className="w-full resize-none rounded-lg border border-border bg-surface-inset px-3 py-2 text-sm text-ink shadow-control-inset focus:border-primary focus:outline-none"
                      />
                    </label>
                    <div className="instrument-inset min-w-48 px-3 py-2.5 text-xs text-muted">
                      {isExpense ? "实际支出" : "实际到账"}
                      <strong className="ml-2 font-mono-amount text-ink">
                        {item.currency} {formatMoney(rowSettled)}
                      </strong>
                    </div>
                  </div>
                </section>
              );
            })}
          </div>
          <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={addBatchRow}
              disabled={batchForms.length >= 100 || isBatchSubmitting}
            >
              <Plus size={15} />
              添加一行
            </Button>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setIsBatchOpen(false)}
                disabled={isBatchSubmitting}
              >
                取消
              </Button>
              <Button type="submit" size="sm" isLoading={isBatchSubmitting}>
                确认录入 {batchForms.length} 条
              </Button>
            </div>
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
                      {formatCurrencyAmount(amount.amount, amount.currency, {
                        showCode: true,
                      })}
                      {amount.currency !== "CNY" && (
                        <span className="ml-2 text-muted">
                          {formatCurrencyAmount(amount.amount_cny, "CNY")}
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
              <div className="flex justify-end gap-2 border-t border-border pt-4">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={() => openEdit(selectedRecord)}
                >
                  <PencilSimple size={15} />
                  编辑记录
                </Button>
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
