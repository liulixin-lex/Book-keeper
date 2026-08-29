import React, { useState, useEffect } from "react";
import { apiRequest } from "../api/client";
import { AIProvider } from "../types/api";
import { Button, Input, Select, Badge } from "../components/ui/core";
import { Modal } from "../components/ui/modals";
import {
  TableSkeleton,
  ErrorState,
  EmptyState,
} from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import { Plus, Lightning } from "@phosphor-icons/react";

export const AIProvidersView: React.FC = () => {
  const { success, error: toastError } = useToast();

  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [currentProviderId, setCurrentProviderId] = useState<string | null>(
    null,
  );
  const [isTesting, setIsTesting] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    name: "",
    protocol: "chat_completions" as
      "chat_completions" | "responses" | "anthropic_messages",
    base_url: "https://api.aiaimax.com/v1",
    model: "",
    reasoning_effort: "medium" as AIProvider["reasoning_effort"],
    timeout_seconds: 120,
    api_key: "",
    use_environment_api_key: false,
    probe_before_save: true,
  });

  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchProviders = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiRequest<AIProvider[]>("/ai/providers");
      setProviders(res);
    } catch (err: any) {
      setError(err.message || "加载 AI 供应商失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  const handleOpenCreate = () => {
    setIsEditing(false);
    setCurrentProviderId(null);
    setFormData({
      name: "",
      protocol: "chat_completions",
      base_url: "https://api.aiaimax.com/v1",
      model: "",
      reasoning_effort: "medium",
      timeout_seconds: 120,
      api_key: "",
      use_environment_api_key: false,
      probe_before_save: true,
    });
    setIsModalOpen(true);
  };

  const handleOpenEdit = (provider: AIProvider) => {
    setIsEditing(true);
    setCurrentProviderId(provider.id);
    setFormData({
      name: provider.name,
      protocol: provider.protocol,
      base_url: provider.base_url,
      model: provider.model,
      reasoning_effort: provider.reasoning_effort,
      timeout_seconds: provider.timeout_seconds,
      api_key: "",
      use_environment_api_key: provider.api_key_source === "environment",
      probe_before_save: true,
    });
    setIsModalOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      if (isEditing && currentProviderId) {
        const payload: any = {
          name: formData.name,
          protocol: formData.protocol,
          base_url: formData.base_url,
          model: formData.model,
          reasoning_effort: formData.reasoning_effort,
          timeout_seconds: formData.timeout_seconds,
          probe_before_save: formData.probe_before_save,
        };
        if (formData.api_key) {
          payload.api_key = formData.api_key;
        } else if (formData.use_environment_api_key) {
          payload.use_environment_api_key = true;
        }
        await apiRequest(`/ai/providers/${currentProviderId}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        success("供应商变更已提交审批");
      } else {
        await apiRequest("/ai/providers", {
          method: "POST",
          body: JSON.stringify({
            name: formData.name,
            protocol: formData.protocol,
            base_url: formData.base_url,
            model: formData.model,
            reasoning_effort: formData.reasoning_effort,
            timeout_seconds: formData.timeout_seconds,
            api_key: formData.api_key || undefined,
            use_environment_api_key: formData.use_environment_api_key,
            probe_before_save: formData.probe_before_save,
          }),
        });
        success("新建供应商已提交审批");
      }
      setIsModalOpen(false);
      fetchProviders();
    } catch (err: any) {
      toastError(err.message || "操作失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTestProvider = async (p: AIProvider) => {
    setIsTesting(p.id);
    try {
      const res = await apiRequest(`/ai/providers/${p.id}/test`, {
        method: "POST",
      });
      if (res.ok) {
        success(`供应商「${p.name}」连通性测试通过！`);
      } else {
        toastError(`测试失败: ${res.error || "无法建立连接"}`);
      }
      fetchProviders();
    } catch (err: any) {
      toastError(err.message || "测试失败");
    } finally {
      setIsTesting(null);
    }
  };

  const handleDeleteProvider = async (p: AIProvider) => {
    if (!confirm(`确定要停用/删除供应商「${p.name}」吗？`)) return;
    try {
      await apiRequest(`/ai/providers/${p.id}`, { method: "DELETE" });
      success("删除申请已提交审批");
      fetchProviders();
    } catch (err: any) {
      toastError(err.message || "删除失败");
    }
  };

  return (
    <div className="space-y-4">
      {/* Top action */}
      <div className="instrument-panel flex items-center justify-between p-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            AI 模型与协议供应商
          </h3>
          <p className="text-xs text-muted">
            配置用于账单分析与自动操作的 LLM
            服务。所有供应商密钥采用主密钥加密存储，且不向前端明文回显。
          </p>
        </div>

        <Button size="sm" onClick={handleOpenCreate}>
          <Plus size={16} />
          <span>添加供应商</span>
        </Button>
      </div>

      {/* Providers Table Surface */}
      <div className="data-table-shell">
        {isLoading ? (
          <TableSkeleton rows={4} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchProviders} />
        ) : providers.length === 0 ? (
          <EmptyState
            title="暂无配置的 AI 供应商"
            description="点击上方按钮添加 OpenAI、Anthropic 或自建兼容协议的供应商"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-surface-inset text-muted border-b border-border">
                  <th className="py-3 px-4 font-medium">供应商名称</th>
                  <th className="py-3 px-4 font-medium">协议</th>
                  <th className="py-3 px-4 font-medium">模型 ID</th>
                  <th className="py-3 px-4 font-medium">推理强度</th>
                  <th className="py-3 px-4 font-medium">API Base URL</th>
                  <th className="py-3 px-4 font-medium">Key 状态</th>
                  <th className="py-3 px-4 font-medium">连通状态</th>
                  <th className="py-3 px-4 font-medium text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {providers.map((p) => (
                  <tr
                    key={p.id}
                    className="hover:bg-surface-strong/50 transition-colors"
                  >
                    <td className="py-3 px-4 font-medium text-ink flex items-center gap-2">
                      <Lightning size={16} className="text-primary" />
                      <span>{p.name}</span>
                    </td>
                    <td className="py-3 px-4 text-muted whitespace-nowrap font-mono text-[11px]">
                      {p.protocol}
                    </td>
                    <td className="py-3 px-4 text-ink font-mono font-medium">
                      {p.model}
                    </td>
                    <td className="py-3 px-4 text-muted font-mono text-[11px]">
                      {p.reasoning_effort}
                    </td>
                    <td className="py-3 px-4 text-muted font-mono text-[11px] max-w-[200px] truncate">
                      {p.base_url}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <Badge variant={p.has_api_key ? "success" : "default"}>
                        {p.has_api_key ? "已配置密钥" : "未设密钥"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      {p.last_test_status === "ok" ? (
                        <Badge variant="success">正常</Badge>
                      ) : p.last_test_status === "failed" ? (
                        <Badge
                          variant="danger"
                          title={p.last_test_error || undefined}
                        >
                          异常
                        </Badge>
                      ) : (
                        <Badge variant="default">未测试</Badge>
                      )}
                    </td>
                    <td className="py-3 px-4 text-center whitespace-nowrap space-x-2">
                      <button
                        onClick={() => handleOpenEdit(p)}
                        className="text-ink hover:underline text-xs"
                      >
                        编辑
                      </button>
                      <button
                        onClick={() => handleTestProvider(p)}
                        disabled={isTesting === p.id}
                        className="text-primary hover:underline text-xs"
                      >
                        {isTesting === p.id ? "测试中..." : "测试连通"}
                      </button>
                      <button
                        onClick={() => handleDeleteProvider(p)}
                        className="text-danger hover:underline text-xs"
                      >
                        删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create / Edit Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={isEditing ? "修改 AI 供应商" : "添加 AI 供应商"}
        maxWidth="lg"
      >
        <form onSubmit={handleSubmit} className="space-y-4 text-xs">
          <Input
            label="供应商名称 *"
            placeholder="例如：OpenAI-GPT4o / DeepSeek"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Select
              label="接口协议 *"
              value={formData.protocol}
              onChange={(e) =>
                setFormData({ ...formData, protocol: e.target.value as any })
              }
            >
              <option value="chat_completions">
                chat_completions (OpenAI标准)
              </option>
              <option value="responses">responses (OpenAI最新规范)</option>
              <option value="anthropic_messages">
                anthropic_messages (Claude)
              </option>
            </Select>

            <Select
              label="推理思考强度 (Reasoning Effort)"
              value={formData.reasoning_effort}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  reasoning_effort: e.target
                    .value as AIProvider["reasoning_effort"],
                })
              }
            >
              <option value="none">none (关闭)</option>
              <option value="minimal">minimal (最少)</option>
              <option value="low">low (低)</option>
              <option value="medium">medium (中)</option>
              <option value="high">high (高)</option>
              <option value="xhigh">xhigh (很高)</option>
              <option value="max">max (最大)</option>
              <option value="ultra">ultra (极致)</option>
            </Select>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Input
              label="API Base URL *"
              placeholder="https://api.aiaimax.com/v1"
              value={formData.base_url}
              onChange={(e) =>
                setFormData({ ...formData, base_url: e.target.value })
              }
              required
            />
            <Input
              label="模型名称 (Model ID) *"
              placeholder="请输入服务商实际模型 ID"
              value={formData.model}
              onChange={(e) =>
                setFormData({ ...formData, model: e.target.value })
              }
              required
            />
          </div>

          <div className="space-y-2 pt-2 border-t border-border">
            <Input
              label="API Key (仅写入，不回显)"
              type="password"
              placeholder="sk-••••••••••••••••"
              value={formData.api_key}
              onChange={(e) =>
                setFormData({ ...formData, api_key: e.target.value })
              }
            />
            <label className="flex items-center gap-2 text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={formData.use_environment_api_key}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    use_environment_api_key: e.target.checked,
                  })
                }
                className="rounded text-primary focus:ring-primary"
              />
              <span>使用环境变量中预设的 OPENAI_API_KEY</span>
            </label>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <label className="flex items-center gap-2 text-ink cursor-pointer">
              <input
                type="checkbox"
                checked={formData.probe_before_save}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    probe_before_save: e.target.checked,
                  })
                }
                className="rounded text-primary focus:ring-primary"
              />
              <span>保存前发送探测请求验证连通性</span>
            </label>
          </div>

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
              提交审批创建
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
