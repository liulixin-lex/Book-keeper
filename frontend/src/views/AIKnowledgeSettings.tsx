import React, { useEffect, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  Database,
  FloppyDisk,
  PlugsConnected,
  WarningCircle,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Badge, Button, Input } from "../components/ui/core";
import { useToast } from "../context/ToastContext";
import { AIEmbeddingProvider, KnowledgeStatus } from "../types/api";

interface ProviderForm {
  name: string;
  baseUrl: string;
  model: string;
  dimension: string;
  apiKey: string;
  timeout: string;
  batchSize: string;
}

const emptyForm: ProviderForm = {
  name: "业务知识嵌入",
  baseUrl: "",
  model: "",
  dimension: "",
  apiKey: "",
  timeout: "60",
  batchSize: "32",
};

export const AIKnowledgeSettings: React.FC = () => {
  const { success, error: toastError } = useToast();
  const [status, setStatus] = useState<KnowledgeStatus | null>(null);
  const [providers, setProviders] = useState<AIEmbeddingProvider[]>([]);
  const [form, setForm] = useState<ProviderForm>(emptyForm);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [knowledge, result] = await Promise.all([
        apiRequest<KnowledgeStatus>("/ai/knowledge/status"),
        apiRequest<{ items: AIEmbeddingProvider[] }>("/ai/embedding-providers"),
      ]);
      setStatus(knowledge);
      setProviders(result.items);
      const selected =
        result.items.find((provider) => provider.is_active) || result.items[0];
      if (selected) {
        setSelectedId(selected.id);
        setForm({
          name: selected.name,
          baseUrl: selected.base_url,
          model: selected.model,
          dimension: String(selected.dimension),
          apiKey: "",
          timeout: String(selected.timeout_seconds),
          batchSize: String(selected.batch_size),
        });
      }
    } catch (loadError) {
      setError((loadError as Error).message || "加载知识库状态失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    const dimension = Number(form.dimension);
    if (
      !form.name.trim() ||
      !form.baseUrl.trim() ||
      !form.model.trim() ||
      dimension < 1
    ) {
      toastError("请完整填写嵌入服务配置");
      return;
    }
    setAction("save");
    try {
      const current = providers.find((provider) => provider.id === selectedId);
      const body = {
        name: form.name.trim(),
        base_url: form.baseUrl.trim(),
        model: form.model.trim(),
        dimension,
        timeout_seconds: Number(form.timeout),
        batch_size: Number(form.batchSize),
        is_active: true,
        ...(form.apiKey ? { api_key: form.apiKey } : {}),
      };
      if (current) {
        await apiRequest(`/ai/embedding-providers/${current.id}`, {
          method: "PATCH",
          body: JSON.stringify({ expected_version: current.version, ...body }),
        });
      } else {
        await apiRequest("/ai/embedding-providers", {
          method: "POST",
          body: JSON.stringify(body),
        });
      }
      setForm((value) => ({ ...value, apiKey: "" }));
      success("嵌入服务配置已保存");
      await load();
    } catch (saveError) {
      toastError((saveError as Error).message || "保存嵌入服务失败");
    } finally {
      setAction(null);
    }
  };

  const test = async () => {
    if (!selectedId) return;
    setAction("test");
    try {
      const result = await apiRequest<{ ok: boolean; error?: string | null }>(
        `/ai/embedding-providers/${selectedId}/test`,
        { method: "POST" },
      );
      if (!result.ok) throw new Error(result.error || "连接测试失败");
      success("嵌入服务连接正常");
      await load();
    } catch (testError) {
      toastError((testError as Error).message || "连接测试失败");
    } finally {
      setAction(null);
    }
  };

  const rebuild = async () => {
    setAction("rebuild");
    try {
      const result = await apiRequest<{ queued: number }>(
        "/ai/knowledge/rebuild",
        {
          method: "POST",
        },
      );
      success(`已加入 ${result.queued} 个索引任务`);
      await load();
    } catch (rebuildError) {
      toastError((rebuildError as Error).message || "启动重建失败");
    } finally {
      setAction(null);
    }
  };

  if (isLoading) {
    return <div className="h-96 animate-pulse rounded-lg bg-surface-strong" />;
  }

  if (error) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center gap-3 rounded-lg border border-danger/25 bg-danger/5 p-6">
        <WarningCircle size={24} className="text-danger" />
        <div className="text-sm text-ink">{error}</div>
        <Button size="sm" variant="secondary" onClick={() => void load()}>
          <ArrowClockwise size={16} />
          重试
        </Button>
      </div>
    );
  }

  const active = providers.find((provider) => provider.id === selectedId);
  const pending = status?.jobs.pending || 0;
  const failed = status?.jobs.failed || 0;

  return (
    <div className="space-y-4">
      <section className="grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["知识文档", status?.documents || 0],
          ["索引分块", status?.chunks || 0],
          ["待处理", pending],
          ["失败任务", failed],
        ].map(([label, value]) => (
          <div key={label} className="bg-surface px-4 py-3">
            <div className="text-[10px] text-muted">{label}</div>
            <div className="mt-1 font-mono text-lg font-semibold text-ink">
              {value}
            </div>
          </div>
        ))}
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="instrument-panel p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="flex items-center gap-2 text-xs font-semibold text-ink">
              <PlugsConnected size={17} className="text-primary" />
              嵌入服务
            </h3>
            {active && (
              <Badge
                variant={
                  active.last_test_status === "ok" ? "success" : "warning"
                }
              >
                {active.last_test_status === "ok" ? "连接正常" : "等待测试"}
              </Badge>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input
              label="名称"
              value={form.name}
              onChange={(event) =>
                setForm((value) => ({ ...value, name: event.target.value }))
              }
            />
            <Input
              label="Base URL"
              value={form.baseUrl}
              onChange={(event) =>
                setForm((value) => ({ ...value, baseUrl: event.target.value }))
              }
              placeholder="https://example.com"
            />
            <Input
              label="模型"
              value={form.model}
              onChange={(event) =>
                setForm((value) => ({ ...value, model: event.target.value }))
              }
            />
            <Input
              label="维度"
              type="number"
              min={1}
              value={form.dimension}
              onChange={(event) =>
                setForm((value) => ({
                  ...value,
                  dimension: event.target.value,
                }))
              }
            />
            <Input
              label="API Key"
              type="password"
              autoComplete="new-password"
              value={form.apiKey}
              onChange={(event) =>
                setForm((value) => ({ ...value, apiKey: event.target.value }))
              }
              placeholder={active?.has_api_key ? "保持现有密钥" : "输入密钥"}
            />
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="超时（秒）"
                type="number"
                min={1}
                value={form.timeout}
                onChange={(event) =>
                  setForm((value) => ({
                    ...value,
                    timeout: event.target.value,
                  }))
                }
              />
              <Input
                label="批量大小"
                type="number"
                min={1}
                value={form.batchSize}
                onChange={(event) =>
                  setForm((value) => ({
                    ...value,
                    batchSize: event.target.value,
                  }))
                }
              />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-border pt-3">
            {active && (
              <Button
                size="sm"
                variant="secondary"
                isLoading={action === "test"}
                onClick={() => void test()}
              >
                <CheckCircle size={16} />
                测试连接
              </Button>
            )}
            <Button
              size="sm"
              isLoading={action === "save"}
              onClick={() => void save()}
            >
              <FloppyDisk size={16} />
              保存配置
            </Button>
          </div>
        </section>

        <aside className="instrument-panel p-4">
          <h3 className="flex items-center gap-2 text-xs font-semibold text-ink">
            <Database size={17} className="text-primary" />
            索引状态
          </h3>
          <dl className="mt-4 space-y-3 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">向量后端</dt>
              <dd className="text-right font-mono text-ink">
                {status?.vector_backend}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">当前版本</dt>
              <dd className="font-mono text-ink">
                v{active?.index_version || 0}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">构建版本</dt>
              <dd className="font-mono text-ink">
                {active?.pending_index_version
                  ? `v${active.pending_index_version}`
                  : "-"}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">降级检索</dt>
              <dd className="text-success">
                {status?.fallback_available ? "可用" : "不可用"}
              </dd>
            </div>
          </dl>
          <Button
            className="mt-5 w-full"
            size="sm"
            variant="secondary"
            isLoading={action === "rebuild"}
            onClick={() => void rebuild()}
          >
            <ArrowClockwise size={16} />
            全量重建
          </Button>
        </aside>
      </div>
    </div>
  );
};
