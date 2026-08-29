import React, { useEffect, useState } from "react";
import {
  ArrowClockwise,
  LockKey,
  Plugs,
  WarningCircle,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Badge, Button } from "../components/ui/core";
import { useToast } from "../context/ToastContext";
import { AIPlugin } from "../types/api";

export const AIPluginSettings: React.FC = () => {
  const { success, error: toastError } = useToast();
  const [plugins, setPlugins] = useState<AIPlugin[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiRequest<{ items: AIPlugin[] }>("/ai/plugins");
      setPlugins(result.items);
    } catch (loadError) {
      setError((loadError as Error).message || "加载插件失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const toggle = async (plugin: AIPlugin) => {
    setUpdatingId(plugin.id);
    try {
      const updated = await apiRequest<AIPlugin>(`/ai/plugins/${plugin.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !plugin.enabled }),
      });
      setPlugins((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      success(updated.enabled ? "插件已启用" : "插件已停用");
    } catch (toggleError) {
      toastError((toggleError as Error).message || "更新插件失败");
    } finally {
      setUpdatingId(null);
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

  return (
    <section className="data-table-shell instrument-panel overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-left text-xs">
          <thead className="bg-surface-inset text-muted">
            <tr>
              <th className="px-4 py-3 font-medium">插件</th>
              <th className="px-4 py-3 font-medium">命令</th>
              <th className="px-4 py-3 font-medium">权限</th>
              <th className="px-4 py-3 font-medium">健康</th>
              <th className="px-4 py-3 text-right font-medium">状态</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {plugins.map((plugin) => (
              <tr
                key={plugin.id}
                className="align-top transition-colors hover:bg-surface-strong/50"
              >
                <td className="px-4 py-3">
                  <div className="flex items-start gap-2.5">
                    <span className="mt-0.5 text-primary">
                      {plugin.core ? (
                        <LockKey size={16} />
                      ) : (
                        <Plugs size={16} />
                      )}
                    </span>
                    <div>
                      <div className="font-medium text-ink">{plugin.name}</div>
                      <div className="mt-0.5 font-mono text-[10px] text-muted">
                        {plugin.id} · v{plugin.version}
                      </div>
                    </div>
                  </div>
                </td>
                <td className="max-w-72 px-4 py-3 text-ink">
                  {plugin.commands.length ? plugin.commands.join(" · ") : "-"}
                </td>
                <td className="px-4 py-3 text-muted">
                  {plugin.permissions.join(" · ")}
                </td>
                <td className="px-4 py-3">
                  <Badge
                    variant={
                      plugin.health_status === "healthy" ? "success" : "danger"
                    }
                  >
                    {plugin.health_status === "healthy" ? "正常" : "异常"}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-right">
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={plugin.enabled}
                      disabled={plugin.core || updatingId === plugin.id}
                      onChange={() => void toggle(plugin)}
                      className="size-4 accent-primary disabled:opacity-50"
                    />
                    <span className="text-muted">
                      {plugin.enabled ? "启用" : "停用"}
                    </span>
                  </label>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};
