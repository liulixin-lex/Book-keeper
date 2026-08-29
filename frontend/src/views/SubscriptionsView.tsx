import React, { useState, useEffect } from "react";
import { apiRequest } from "../api/client";
import { Provider, Subscription } from "../types/api";
import { formatMoney } from "../utils/format";
import { Button, Input, Select, Badge } from "../components/ui/core";
import { Modal } from "../components/ui/modals";
import {
  TableSkeleton,
  ErrorState,
  EmptyState,
} from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import { Plus, ArrowClockwise, CreditCard } from "@phosphor-icons/react";

export const SubscriptionsView: React.FC = () => {
  const { user } = useAuth();
  const { success, error: toastError } = useToast();

  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [formData, setFormData] = useState({
    counterparty_id: "",
    name: "",
    billing_cycle: "monthly",
    currency: "USD",
    expected_amount: "",
    renewal_date: "2026-09-01",
    auto_renew: true,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [subsRes, cpsRes] = await Promise.all([
        apiRequest<Subscription[]>("/subscriptions"),
        apiRequest<Provider[]>("/catalog/providers?active_only=true"),
      ]);
      setSubscriptions(subsRes);
      setProviders(cpsRes);
      if (cpsRes.length > 0 && !formData.counterparty_id) {
        setFormData((prev) => ({ ...prev, counterparty_id: cpsRes[0].id }));
      }
    } catch (err: any) {
      setError(err.message || "加载订阅列表失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.counterparty_id) {
      toastError("请填写订阅名称并选择供应商");
      return;
    }

    setIsSubmitting(true);
    try {
      await apiRequest("/subscriptions", {
        method: "POST",
        body: JSON.stringify(formData),
      });
      success("订阅项目添加成功");
      setIsModalOpen(false);
      fetchData();
    } catch (err: any) {
      toastError(err.message || "添加订阅失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTriggerCharge = async (sub: Subscription) => {
    if (!sub.expected_amount) {
      toastError("请先为该订阅设置预计金额");
      return;
    }
    try {
      await apiRequest(`/subscriptions/${sub.id}/charges`, {
        method: "POST",
        body: JSON.stringify({
          accounting_date: new Date().toISOString().split("T")[0],
          description: `订阅周期扣费: ${sub.name}`,
          cost: {
            amount: sub.expected_amount,
            currency: sub.currency,
          },
          post: true,
        }),
      });
      success(`已为「${sub.name}」生成当期预提/扣费草稿凭证`);
    } catch (err: any) {
      toastError(err.message || "扣费生成失败");
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="instrument-panel flex items-center justify-between p-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            SaaS 与上游周期性订阅管理
          </h3>
          <p className="text-xs text-muted">
            追踪按月/按年计费的云服务、域名、专线及 API
            订阅，自动预提与按期过账。
          </p>
        </div>

        {user?.role !== "viewer" && (
          <Button size="sm" onClick={() => setIsModalOpen(true)}>
            <Plus size={16} />
            <span>新增订阅计划</span>
          </Button>
        )}
      </div>

      {/* Subscriptions Table */}
      <div className="data-table-shell">
        {isLoading ? (
          <TableSkeleton rows={4} cols={6} />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchData} />
        ) : subscriptions.length === 0 ? (
          <EmptyState
            title="暂无周期订阅记录"
            description="添加 OpenAI API、AWS、Vercel 等定期扣费服务"
            icon={
              <ArrowClockwise
                size={40}
                weight="duotone"
                className="text-primary"
              />
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-surface-inset text-muted border-b border-border">
                  <th className="py-3 px-4 font-medium">订阅名称</th>
                  <th className="py-3 px-4 font-medium">计费周期</th>
                  <th className="py-3 px-4 font-medium">预计费用</th>
                  <th className="py-3 px-4 font-medium">下次续费/扣费日</th>
                  <th className="py-3 px-4 font-medium">自动续期</th>
                  <th className="py-3 px-4 font-medium text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {subscriptions.map((s) => (
                  <tr
                    key={s.id}
                    className="hover:bg-surface-strong/50 transition-colors"
                  >
                    <td className="py-3 px-4 font-medium text-ink flex items-center gap-2">
                      <CreditCard size={16} className="text-primary" />
                      <span>{s.name}</span>
                    </td>
                    <td className="py-3 px-4 text-muted whitespace-nowrap">
                      {s.billing_cycle === "monthly"
                        ? "按月 (Monthly)"
                        : "按年 (Yearly)"}
                    </td>
                    <td className="py-3 px-4 font-mono font-semibold text-ink whitespace-nowrap">
                      {s.currency} {formatMoney(s.expected_amount)}
                    </td>
                    <td className="py-3 px-4 text-muted whitespace-nowrap">
                      {s.renewal_date || "-"}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <Badge variant={s.auto_renew ? "success" : "default"}>
                        {s.auto_renew ? "开启" : "关闭"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-center whitespace-nowrap">
                      {user?.role !== "viewer" && (
                        <button
                          onClick={() => handleTriggerCharge(s)}
                          className="text-primary hover:underline text-xs"
                        >
                          生成扣费草稿
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="新建订阅计划"
        maxWidth="md"
      >
        <form onSubmit={handleCreate} className="space-y-4 text-xs">
          <Input
            label="订阅服务名称 *"
            placeholder="例如：AWS 云服务器 / OpenAI API 基础套餐"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
          />

          <Select
            label="提供商 *"
            value={formData.counterparty_id}
            onChange={(e) =>
              setFormData({ ...formData, counterparty_id: e.target.value })
            }
            required
          >
            {providers.map((cp) => (
              <option key={cp.id} value={cp.id}>
                {cp.name} - {cp.expense_category_name}
              </option>
            ))}
          </Select>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Select
              label="计费周期"
              value={formData.billing_cycle}
              onChange={(e) =>
                setFormData({ ...formData, billing_cycle: e.target.value })
              }
            >
              <option value="monthly">每月</option>
              <option value="yearly">每年</option>
            </Select>

            <Input
              label="预估金额 *"
              placeholder="0.00"
              value={formData.expected_amount}
              onChange={(e) =>
                setFormData({ ...formData, expected_amount: e.target.value })
              }
              required
            />

            <Select
              label="币种"
              value={formData.currency}
              onChange={(e) =>
                setFormData({ ...formData, currency: e.target.value })
              }
            >
              <option value="USD">USD</option>
              <option value="CNY">CNY</option>
              <option value="EUR">EUR</option>
              <option value="GBP">GBP</option>
              <option value="JPY">JPY</option>
              <option value="KRW">KRW</option>
              <option value="SGD">SGD</option>
              <option value="PHP">PHP</option>
            </Select>
          </div>

          <Input
            label="续费日期"
            type="date"
            value={formData.renewal_date}
            onChange={(e) =>
              setFormData({ ...formData, renewal_date: e.target.value })
            }
          />

          <div className="flex justify-end gap-2 pt-4 border-t border-border">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setIsModalOpen(false)}
            >
              取消
            </Button>
            <Button type="submit" size="sm" isLoading={isSubmitting}>
              确认创建
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
