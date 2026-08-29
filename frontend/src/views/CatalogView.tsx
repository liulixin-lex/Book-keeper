import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowsClockwise,
  PencilSimple,
  Plus,
  ToggleLeft,
  ToggleRight,
  Trash,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Account, Category, FxRate, Provider } from "../types/api";
import { Badge, Button, Input, Select } from "../components/ui/core";
import { Modal } from "../components/ui/modals";
import {
  EmptyState,
  ErrorState,
  TableSkeleton,
} from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";

type CatalogTab = "categories" | "accounts" | "providers" | "fx-rates";
type EditTarget = Category | Provider | FxRate;

interface FormState {
  name: string;
  kind: "income" | "expense";
  accountId: string;
  expenseCategoryId: string;
  isActive: boolean;
  currency: string;
  rate: string;
}

const FX_CURRENCIES = [
  ["USD", "美元"],
  ["EUR", "欧元"],
  ["GBP", "英镑"],
  ["JPY", "日元"],
  ["KRW", "韩元"],
  ["SGD", "新加坡元"],
  ["PHP", "菲律宾比索"],
] as const;

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  asset: "资产",
  liability: "负债",
  equity: "所有者权益",
  revenue: "收入",
  expense: "费用",
};

const ACCOUNT_PURPOSE_LABELS: Record<string, string> = {
  system_funds: "系统实际收付款",
  payable: "应付款项",
  opening_balance: "期初与迁移",
  operating_revenue: "主营收入",
  other_revenue: "其他收入",
  operating_cost: "主营成本",
  administrative_expense: "日常管理费用",
  processing_fee: "手续费与汇兑",
};

const emptyForm = (): FormState => ({
  name: "",
  kind: "income",
  accountId: "",
  expenseCategoryId: "",
  isActive: true,
  currency: "USD",
  rate: "",
});

const formatFxRate = (value: string) =>
  new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 8,
  }).format(Number(value));

const tabClass = (active: boolean) =>
  `px-3 py-1.5 text-xs font-medium rounded-lg whitespace-nowrap transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 ${
    active
      ? "bg-primary text-primary-ink font-semibold"
      : "text-muted hover:bg-surface-strong hover:text-ink"
  }`;

export const CatalogView: React.FC = () => {
  const { user } = useAuth();
  const { success, error: toastError } = useToast();
  const canEdit = !!user && user.role !== "viewer";

  const [activeTab, setActiveTab] = useState<CatalogTab>("categories");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [fxRates, setFxRates] = useState<FxRate[]>([]);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editing, setEditing] = useState<EditTarget | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<EditTarget | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const eligibleAccounts = useMemo(
    () =>
      accounts.filter(
        (account) =>
          account.is_active &&
          account.account_type ===
            (form.kind === "income" ? "revenue" : "expense"),
      ),
    [accounts, form.kind],
  );

  const expenseCategories = useMemo(
    () =>
      categories.filter(
        (category) => category.kind === "expense" && category.is_active,
      ),
    [categories],
  );

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      if (activeTab === "categories") {
        const [categoryRows, accountRows] = await Promise.all([
          apiRequest<Category[]>("/catalog/categories"),
          apiRequest<Account[]>("/catalog/accounts"),
        ]);
        setCategories(categoryRows);
        setAccounts(accountRows);
      } else if (activeTab === "accounts") {
        setAccounts(await apiRequest<Account[]>("/catalog/accounts"));
      } else if (activeTab === "providers") {
        const [providerRows, categoryRows] = await Promise.all([
          apiRequest<Provider[]>("/catalog/providers"),
          apiRequest<Category[]>("/catalog/categories"),
        ]);
        setProviders(providerRows);
        setCategories(categoryRows);
      } else {
        if (canEdit) {
          try {
            setFxRates(
              await apiRequest<FxRate[]>("/catalog/fx-rates/refresh", {
                method: "POST",
              }),
            );
            return;
          } catch {
            // Keep the last saved reference rates available if the provider is unavailable.
          }
        }
        setFxRates(await apiRequest<FxRate[]>("/catalog/fx-rates"));
      }
    } catch (err: any) {
      setError(err.message || "加载主数据失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [activeTab, canEdit]);

  const openCreate = () => {
    const next = emptyForm();
    if (activeTab === "categories") {
      next.accountId =
        accounts.find((item) => item.account_type === "revenue")?.id || "";
    } else if (activeTab === "providers") {
      next.expenseCategoryId = expenseCategories[0]?.id || "";
    }
    setEditing(null);
    setForm(next);
    setIsEditorOpen(true);
  };

  const openEdit = (item: EditTarget) => {
    setEditing(item);
    if ("kind" in item) {
      setForm({
        ...emptyForm(),
        name: item.name,
        kind: item.kind === "expense" ? "expense" : "income",
        accountId: item.account_id,
        isActive: item.is_active,
      });
    } else if ("expense_category_id" in item) {
      setForm({
        ...emptyForm(),
        name: item.name,
        expenseCategoryId: item.expense_category_id,
        isActive: item.is_active,
      });
    } else {
      setForm({
        ...emptyForm(),
        currency: item.base_currency,
        rate: item.rate,
      });
    }
    setIsEditorOpen(true);
  };

  const handleKindChange = (kind: FormState["kind"]) => {
    const account = accounts.find(
      (item) =>
        item.is_active &&
        item.account_type === (kind === "income" ? "revenue" : "expense"),
    );
    setForm((current) => ({ ...current, kind, accountId: account?.id || "" }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    try {
      if (activeTab === "categories") {
        const payload = {
          name: form.name,
          kind: form.kind,
          account_id: form.accountId,
          is_active: form.isActive,
        };
        await apiRequest(
          editing ? `/catalog/categories/${editing.id}` : "/catalog/categories",
          { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) },
        );
      } else if (activeTab === "providers") {
        const payload = {
          name: form.name,
          expense_category_id: form.expenseCategoryId,
          is_active: form.isActive,
        };
        await apiRequest(
          editing ? `/catalog/providers/${editing.id}` : "/catalog/providers",
          { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) },
        );
      } else if (activeTab === "fx-rates") {
        if (editing) {
          await apiRequest(`/catalog/fx-rates/${editing.id}`, {
            method: "PATCH",
            body: JSON.stringify({ rate: form.rate }),
          });
        } else {
          await apiRequest("/catalog/fx-rates", {
            method: "POST",
            body: JSON.stringify({
              base_currency: form.currency,
              quote_currency: "CNY",
              rate: form.rate,
              effective_at: new Date().toISOString(),
              source: "manual",
              rate_type: "manual_override",
            }),
          });
        }
      }
      success(editing ? "主数据已更新" : "主数据已新增");
      setIsEditorOpen(false);
      await loadData();
    } catch (err: any) {
      toastError(err.message || "保存失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleActive = async (item: Category | Provider) => {
    const endpoint = "kind" in item ? "categories" : "providers";
    try {
      await apiRequest(`/catalog/${endpoint}/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !item.is_active }),
      });
      success(item.is_active ? "已停用" : "已启用");
      await loadData();
    } catch (err: any) {
      toastError(err.message || "状态更新失败");
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsSubmitting(true);
    try {
      const endpoint =
        "kind" in deleteTarget
          ? "categories"
          : "expense_category_id" in deleteTarget
            ? "providers"
            : "fx-rates";
      await apiRequest(`/catalog/${endpoint}/${deleteTarget.id}`, {
        method: "DELETE",
      });
      success("主数据已删除");
      setDeleteTarget(null);
      await loadData();
    } catch (err: any) {
      toastError(err.message || "删除失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const refreshRates = async () => {
    setIsRefreshing(true);
    try {
      const rates = await apiRequest<FxRate[]>("/catalog/fx-rates/refresh", {
        method: "POST",
      });
      setFxRates(rates);
      success("公开参考汇率已刷新");
    } catch (err: any) {
      toastError(err.message || "汇率刷新失败");
    } finally {
      setIsRefreshing(false);
    }
  };

  const accountById = (id: string) => accounts.find((item) => item.id === id);
  const empty =
    (activeTab === "categories" && categories.length === 0) ||
    (activeTab === "providers" && providers.length === 0) ||
    (activeTab === "fx-rates" && fxRates.length === 0);

  return (
    <div className="space-y-4">
      <div className="instrument-inset flex items-center gap-1 overflow-x-auto p-1.5">
        <button
          className={tabClass(activeTab === "categories")}
          onClick={() => setActiveTab("categories")}
        >
          收支类别
        </button>
        <button
          className={tabClass(activeTab === "accounts")}
          onClick={() => setActiveTab("accounts")}
        >
          总账科目
        </button>
        <button
          className={tabClass(activeTab === "providers")}
          onClick={() => setActiveTab("providers")}
        >
          提供商
        </button>
        <button
          className={tabClass(activeTab === "fx-rates")}
          onClick={() => setActiveTab("fx-rates")}
        >
          汇率表
        </button>
      </div>

      <div className="instrument-panel flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">
            {activeTab === "categories" && "收入与支出类别"}
            {activeTab === "accounts" && "标准总账科目"}
            {activeTab === "providers" && "提供商"}
            {activeTab === "fx-rates" && "人民币参考汇率"}
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {activeTab === "categories" &&
              "维护记账时使用的类别及其对应总账科目。"}
            {activeTab === "accounts" &&
              "按小企业会计准则常用编号整理，科目由系统统一维护。"}
            {activeTab === "providers" && "维护提供商及其默认支出类别。"}
            {activeTab === "fx-rates" &&
              "显示 1 单位外币折合人民币，公开数据按最新工作日更新。"}
          </p>
        </div>
        {canEdit && activeTab !== "accounts" && (
          <div className="flex shrink-0 items-center gap-2">
            {activeTab === "fx-rates" && (
              <Button
                variant="outline"
                size="sm"
                isLoading={isRefreshing}
                onClick={refreshRates}
              >
                <ArrowsClockwise size={16} />
                <span>刷新公开汇率</span>
              </Button>
            )}
            <Button size="sm" onClick={openCreate}>
              <Plus size={16} />
              <span>{activeTab === "fx-rates" ? "手工汇率" : "新增"}</span>
            </Button>
          </div>
        )}
      </div>

      <div className="data-table-shell">
        {isLoading ? (
          <TableSkeleton rows={6} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={loadData} />
        ) : empty ? (
          <EmptyState
            title={activeTab === "fx-rates" ? "暂无参考汇率" : "暂无主数据"}
            description={
              activeTab === "fx-rates"
                ? "刷新公开汇率或添加一条手工汇率"
                : "使用上方新增按钮创建第一条数据"
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              {activeTab === "categories" && (
                <>
                  <thead>
                    <tr className="border-b border-border bg-surface-inset text-muted">
                      <th className="px-4 py-3 font-medium">类别名称</th>
                      <th className="px-4 py-3 font-medium">收支方向</th>
                      <th className="px-4 py-3 font-medium">对应总账科目</th>
                      <th className="px-4 py-3 font-medium">状态</th>
                      {canEdit && (
                        <th className="px-4 py-3 text-right font-medium">
                          操作
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {categories.map((category) => {
                      const account = accountById(category.account_id);
                      return (
                        <tr
                          key={category.id}
                          className="transition-colors hover:bg-surface-strong/50"
                        >
                          <td className="max-w-64 px-4 py-3 font-medium text-ink">
                            <span
                              className="block truncate"
                              title={category.name}
                            >
                              {category.name}
                            </span>
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            <Badge
                              variant={
                                category.kind === "income"
                                  ? "success"
                                  : "danger"
                              }
                            >
                              {category.kind === "income" ? "收入" : "支出"}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 text-muted whitespace-nowrap">
                            <span className="font-mono text-[11px] text-primary">
                              {account?.code || "-"}
                            </span>
                            <span className="ml-2">
                              {account?.name || "科目不存在"}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <Badge
                              variant={
                                category.is_active ? "success" : "default"
                              }
                            >
                              {category.is_active ? "启用" : "停用"}
                            </Badge>
                          </td>
                          {canEdit && (
                            <ActionCell
                              onEdit={() => openEdit(category)}
                              onToggle={() => toggleActive(category)}
                              onDelete={() => setDeleteTarget(category)}
                              active={category.is_active}
                            />
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </>
              )}

              {activeTab === "accounts" && (
                <>
                  <thead>
                    <tr className="border-b border-border bg-surface-inset text-muted">
                      <th className="px-4 py-3 font-medium">科目代码</th>
                      <th className="px-4 py-3 font-medium">科目名称</th>
                      <th className="px-4 py-3 font-medium">类别</th>
                      <th className="px-4 py-3 font-medium">系统用途</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {accounts.map((account) => (
                      <tr
                        key={account.id}
                        className="transition-colors hover:bg-surface-strong/50"
                      >
                        <td className="px-4 py-3 font-mono font-semibold text-primary">
                          {account.code}
                        </td>
                        <td className="px-4 py-3 font-medium text-ink">
                          {account.name}
                        </td>
                        <td className="px-4 py-3 text-muted">
                          {ACCOUNT_TYPE_LABELS[account.account_type] ||
                            account.account_type}
                        </td>
                        <td className="px-4 py-3 text-muted">
                          {ACCOUNT_PURPOSE_LABELS[account.subtype || ""] ||
                            "系统科目"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {activeTab === "providers" && (
                <>
                  <thead>
                    <tr className="border-b border-border bg-surface-inset text-muted">
                      <th className="px-4 py-3 font-medium">提供商名称</th>
                      <th className="px-4 py-3 font-medium">支出类别</th>
                      <th className="px-4 py-3 font-medium">状态</th>
                      {canEdit && (
                        <th className="px-4 py-3 text-right font-medium">
                          操作
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {providers.map((item) => (
                      <tr
                        key={item.id}
                        className="transition-colors hover:bg-surface-strong/50"
                      >
                        <td className="max-w-80 px-4 py-3 font-medium text-ink">
                          <span className="block truncate" title={item.name}>
                            {item.name}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-muted whitespace-nowrap">
                          {item.expense_category_name}
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={item.is_active ? "success" : "default"}
                          >
                            {item.is_active ? "启用" : "停用"}
                          </Badge>
                        </td>
                        {canEdit && (
                          <ActionCell
                            onEdit={() => openEdit(item)}
                            onToggle={() => toggleActive(item)}
                            onDelete={() => setDeleteTarget(item)}
                            active={item.is_active}
                          />
                        )}
                      </tr>
                    ))}
                  </tbody>
                </>
              )}

              {activeTab === "fx-rates" && (
                <>
                  <thead>
                    <tr className="border-b border-border bg-surface-inset text-muted">
                      <th className="px-4 py-3 font-medium">币种</th>
                      <th className="px-4 py-3 text-right font-medium">
                        1 外币折合 CNY
                      </th>
                      <th className="px-4 py-3 font-medium">数据日期</th>
                      <th className="px-4 py-3 font-medium">来源</th>
                      {canEdit && (
                        <th className="px-4 py-3 text-right font-medium">
                          操作
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {fxRates.map((rate) => (
                      <tr
                        key={rate.id}
                        className="transition-colors hover:bg-surface-strong/50"
                      >
                        <td className="px-4 py-3 font-mono font-semibold text-ink">
                          {rate.base_currency}
                        </td>
                        <td className="px-4 py-3 text-right font-mono font-semibold text-ink">
                          {formatFxRate(rate.rate)}
                        </td>
                        <td className="px-4 py-3 text-muted whitespace-nowrap">
                          {new Date(rate.effective_at).toLocaleDateString(
                            "zh-CN",
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <Badge
                            variant={
                              rate.source === "manual" ? "warning" : "info"
                            }
                          >
                            {rate.source === "manual" ? "手工" : "公开参考"}
                          </Badge>
                        </td>
                        {canEdit && (
                          <td className="px-4 py-3">
                            <div className="flex justify-end gap-1">
                              <IconButton
                                label="编辑汇率"
                                onClick={() => openEdit(rate)}
                              >
                                <PencilSimple size={16} />
                              </IconButton>
                              <IconButton
                                label="删除汇率"
                                danger
                                onClick={() => setDeleteTarget(rate)}
                              >
                                <Trash size={16} />
                              </IconButton>
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </>
              )}
            </table>
          </div>
        )}
      </div>

      <Modal
        isOpen={isEditorOpen}
        onClose={() => setIsEditorOpen(false)}
        title={editing ? "编辑主数据" : "新增主数据"}
        maxWidth="md"
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          {activeTab === "categories" && (
            <>
              <Input
                label="类别名称 *"
                maxLength={160}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                required
              />
              <Select
                label="收支方向 *"
                value={form.kind}
                onChange={(event) =>
                  handleKindChange(event.target.value as FormState["kind"])
                }
              >
                <option value="income">收入</option>
                <option value="expense">支出</option>
              </Select>
              <Select
                label="对应总账科目 *"
                value={form.accountId}
                onChange={(event) =>
                  setForm({ ...form, accountId: event.target.value })
                }
                required
              >
                {eligibleAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.code} - {account.name}
                  </option>
                ))}
              </Select>
              <StatusSelect
                value={form.isActive}
                onChange={(isActive) => setForm({ ...form, isActive })}
              />
            </>
          )}
          {activeTab === "providers" && (
            <>
              <Input
                label="提供商名称 *"
                maxLength={240}
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                required
              />
              <Select
                label="支出类别 *"
                value={form.expenseCategoryId}
                onChange={(event) =>
                  setForm({
                    ...form,
                    expenseCategoryId: event.target.value,
                  })
                }
                required
              >
                {expenseCategories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
              <StatusSelect
                value={form.isActive}
                onChange={(isActive) => setForm({ ...form, isActive })}
              />
            </>
          )}
          {activeTab === "fx-rates" && (
            <>
              <Select
                label="外币 *"
                value={form.currency}
                disabled={!!editing}
                onChange={(event) =>
                  setForm({ ...form, currency: event.target.value })
                }
              >
                {FX_CURRENCIES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {code} - {name}
                  </option>
                ))}
              </Select>
              <Input
                label="1 外币折合人民币 *"
                type="number"
                min="0.00000001"
                step="any"
                inputMode="decimal"
                placeholder="0.000000"
                value={form.rate}
                onChange={(event) =>
                  setForm({ ...form, rate: event.target.value })
                }
                required
              />
            </>
          )}
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setIsEditorOpen(false)}
            >
              取消
            </Button>
            <Button type="submit" size="sm" isLoading={isSubmitting}>
              保存
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="确认删除"
        maxWidth="sm"
      >
        <div className="space-y-4 text-sm">
          <p className="leading-relaxed text-muted">
            确认删除这条主数据？已被账单或业务引用的数据不能删除，可以改为停用。
          </p>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setDeleteTarget(null)}
            >
              取消
            </Button>
            <Button
              variant="danger"
              size="sm"
              isLoading={isSubmitting}
              onClick={handleDelete}
            >
              删除
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

const StatusSelect: React.FC<{
  value: boolean;
  onChange: (value: boolean) => void;
}> = ({ value, onChange }) => (
  <Select
    label="启用状态"
    value={value ? "active" : "inactive"}
    onChange={(event) => onChange(event.target.value === "active")}
  >
    <option value="active">启用</option>
    <option value="inactive">停用</option>
  </Select>
);

const IconButton: React.FC<{
  label: string;
  onClick: () => void;
  danger?: boolean;
  children: React.ReactNode;
}> = ({ label, onClick, danger = false, children }) => (
  <button
    type="button"
    title={label}
    aria-label={label}
    onClick={onClick}
    className={`inline-flex h-8 w-8 items-center justify-center rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 ${
      danger
        ? "text-muted hover:bg-danger/10 hover:text-danger"
        : "text-muted hover:bg-surface-strong hover:text-ink"
    }`}
  >
    {children}
  </button>
);

const ActionCell: React.FC<{
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
  active: boolean;
}> = ({ onEdit, onToggle, onDelete, active }) => (
  <td className="px-4 py-3">
    <div className="flex justify-end gap-1">
      <IconButton label="编辑" onClick={onEdit}>
        <PencilSimple size={16} />
      </IconButton>
      <IconButton label={active ? "停用" : "启用"} onClick={onToggle}>
        {active ? (
          <ToggleRight size={18} weight="fill" />
        ) : (
          <ToggleLeft size={18} />
        )}
      </IconButton>
      <IconButton label="删除" danger onClick={onDelete}>
        <Trash size={16} />
      </IconButton>
    </div>
  </td>
);
