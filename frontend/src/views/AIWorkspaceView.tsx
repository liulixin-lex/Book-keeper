import React, { useEffect, useState } from "react";
import {
  ArrowCounterClockwise,
  Database,
  FloppyDisk,
  Globe,
  Plugs,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Button } from "../components/ui/core";
import { ErrorState, TableSkeleton } from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import { AIWorkspaceSettings } from "../types/api";
import { AIKnowledgeSettings } from "./AIKnowledgeSettings";
import { AIPluginSettings } from "./AIPluginSettings";

type SettingsTab = "strategy" | "knowledge" | "plugins";

export const AIWorkspaceView: React.FC = () => {
  const { success, error: toastError } = useToast();
  const [activeTab, setActiveTab] = useState<SettingsTab>("strategy");
  const [settings, setSettings] = useState<AIWorkspaceSettings | null>(null);
  const [agentsMd, setAgentsMd] = useState("");
  const [webAccess, setWebAccess] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchSettings = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await apiRequest<AIWorkspaceSettings>("/ai/settings");
      setSettings(result);
      setAgentsMd(result.agents_md);
      setWebAccess(result.web_access_enabled);
    } catch (loadError) {
      setError((loadError as Error).message || "加载工作区 AI 设置失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchSettings();
  }, []);

  const save = async () => {
    if (!settings) return;
    setIsSaving(true);
    try {
      await apiRequest("/ai/settings", {
        method: "PATCH",
        body: JSON.stringify({
          version: settings.version,
          agents_md: agentsMd,
          web_access_enabled: webAccess,
        }),
      });
      success("AI 运行策略变更已提交审批");
      await fetchSettings();
    } catch (saveError) {
      toastError((saveError as Error).message || "保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) return <TableSkeleton rows={6} cols={2} />;
  if (error) return <ErrorState message={error} onRetry={fetchSettings} />;

  const tabs = [
    { key: "strategy" as const, label: "运行策略", icon: SlidersHorizontal },
    { key: "knowledge" as const, label: "知识库", icon: Database },
    { key: "plugins" as const, label: "插件", icon: Plugs },
  ];

  return (
    <div className="space-y-4">
      <div className="instrument-inset flex overflow-x-auto p-1">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`flex h-8 shrink-0 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors ${
                activeTab === tab.key
                  ? "bg-primary text-primary-ink"
                  : "text-muted hover:bg-surface-strong hover:text-ink"
              }`}
            >
              <Icon size={15} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === "knowledge" && <AIKnowledgeSettings />}
      {activeTab === "plugins" && <AIPluginSettings />}
      {activeTab === "strategy" && (
        <div className="space-y-4">
          <section className="instrument-panel flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-ink">
                账本 AI 运行策略
              </h3>
              <p className="mt-1 text-xs text-muted">
                AGENTS.md · v{settings?.version || 1}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void fetchSettings()}
                disabled={isSaving}
              >
                <ArrowCounterClockwise size={16} />
                刷新
              </Button>
              <Button
                size="sm"
                onClick={() => void save()}
                isLoading={isSaving}
              >
                <FloppyDisk size={16} />
                提交审批
              </Button>
            </div>
          </section>

          <section className="instrument-panel flex items-center justify-between gap-4 p-4">
            <div className="flex min-w-0 items-center gap-3">
              <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Globe size={18} />
              </span>
              <div className="min-w-0">
                <div className="text-xs font-semibold text-ink">联网搜索</div>
                <div className="mt-0.5 text-[11px] text-muted">
                  仅用于只读查询
                </div>
              </div>
            </div>
            <label className="inline-flex shrink-0 items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                checked={webAccess}
                onChange={(event) => setWebAccess(event.target.checked)}
                className="size-4 accent-primary"
              />
              {webAccess ? "启用" : "停用"}
            </label>
          </section>

          <section className="instrument-panel p-4">
            <div className="mb-2 flex items-center justify-between text-xs text-muted">
              <span className="font-medium">AGENTS.md</span>
              <span className="font-mono">v{settings?.version || 1}</span>
            </div>
            <textarea
              value={agentsMd}
              onChange={(event) => setAgentsMd(event.target.value)}
              rows={20}
              className="w-full rounded-lg border border-border bg-surface-inset p-4 font-mono text-xs leading-relaxed text-ink shadow-control-inset outline-none focus:border-primary"
            />
          </section>
        </div>
      )}
    </div>
  );
};
