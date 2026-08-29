import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  Check,
  CheckCircle,
  FileArrowUp,
  FileText,
  MagnifyingGlass,
  Plus,
  Prohibit,
  Receipt,
  ShieldCheck,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Badge, Button } from "../components/ui/core";
import { useToast } from "../context/ToastContext";
import {
  AICommand,
  AIWorkflow,
  Category,
  LedgerProposal,
  Provider,
} from "../types/api";
import { AIProposalEditor } from "./AIProposalEditor";
import { AIWorkflowGuidance } from "./AIWorkflowGuidance";
import { AIWorkflowPreview } from "./AIWorkflowPreview";

interface AIWriteWorkbenchProps {
  providerId: string;
}

const statusMeta: Record<
  string,
  {
    label: string;
    variant: "default" | "info" | "warning" | "success" | "danger";
  }
> = {
  collecting: { label: "收集资料", variant: "info" },
  extracting: { label: "正在解析", variant: "info" },
  needs_input: { label: "需要补充", variant: "warning" },
  draft: { label: "提案草稿", variant: "default" },
  validating: { label: "正在校验", variant: "info" },
  ready: { label: "等待确认", variant: "success" },
  committing: { label: "正在提交", variant: "warning" },
  committed: { label: "已写入", variant: "success" },
  pending_approval: { label: "等待审批", variant: "warning" },
  cancelled: { label: "已取消", variant: "default" },
  expired: { label: "已过期", variant: "danger" },
  failed: { label: "处理失败", variant: "danger" },
  unknown: { label: "状态未知", variant: "warning" },
};

const commandIcon = (command: string) => {
  if (command.includes("收入")) return Receipt;
  if (command.includes("支出")) return FileText;
  if (command.includes("冲正") || command.includes("删除")) return Prohibit;
  return FileArrowUp;
};

const terminalStatuses = new Set([
  "committed",
  "pending_approval",
  "cancelled",
  "expired",
  "failed",
]);

export const AIWriteWorkbench: React.FC<AIWriteWorkbenchProps> = ({
  providerId,
}) => {
  const { success, error: toastError } = useToast();
  const [commands, setCommands] = useState<AICommand[]>([]);
  const [workflow, setWorkflow] = useState<AIWorkflow | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [sourceText, setSourceText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [guidanceText, setGuidanceText] = useState("");
  const [activeProposalId, setActiveProposalId] = useState<string | null>(null);
  const [selectedProposalIds, setSelectedProposalIds] = useState<Set<string>>(
    new Set(),
  );
  const [isLoading, setIsLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [executionUnknown, setExecutionUnknown] = useState(false);
  const confirmKeyRef = useRef<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);

  const loadInitial = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [commandResult, providerRows, categoryRows] = await Promise.all([
        apiRequest<{ items: AICommand[] }>("/ai/commands"),
        apiRequest<Provider[]>("/catalog/providers"),
        apiRequest<Category[]>("/catalog/categories"),
      ]);
      setCommands(
        commandResult.items.filter(
          (command) => command.effect === "propose" && command.starts_workflow,
        ),
      );
      setProviders(providerRows);
      setCategories(categoryRows);
    } catch (loadError) {
      setError((loadError as Error).message || "加载记账工作台失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadInitial();
  }, []);

  useEffect(() => {
    if (!workflow?.proposals.length) {
      setActiveProposalId(null);
      setSelectedProposalIds(new Set());
      return;
    }
    const available = workflow.proposals.map((proposal) => proposal.id);
    setActiveProposalId((current) =>
      current && available.includes(current) ? current : available[0],
    );
    setSelectedProposalIds(
      new Set(
        workflow.selected_proposal_ids.length
          ? workflow.selected_proposal_ids
          : available,
      ),
    );
  }, [workflow]);

  const activeProposal = useMemo(
    () =>
      workflow?.proposals.find((proposal) => proposal.id === activeProposalId),
    [activeProposalId, workflow],
  );

  const create = async (command: string) => {
    setAction("create");
    setError(null);
    try {
      const created = await apiRequest<AIWorkflow>("/ai/workflows", {
        method: "POST",
        body: JSON.stringify({ command, provider_id: providerId || null }),
      });
      setWorkflow(created);
      setSourceText("");
      setFiles([]);
      setGuidanceText("");
      setExecutionUnknown(false);
      confirmKeyRef.current = null;
    } catch (createError) {
      toastError((createError as Error).message || "创建工作流失败");
    } finally {
      setAction(null);
    }
  };

  const refresh = async () => {
    if (!workflow) return;
    setAction("refresh");
    try {
      const current = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}`,
      );
      setWorkflow(current);
      setExecutionUnknown(false);
    } catch (refreshError) {
      toastError((refreshError as Error).message || "读取工作流状态失败");
    } finally {
      setAction(null);
    }
  };

  const persistPendingSources = async () => {
    if (!workflow) throw new Error("工作流不存在");
    let current = workflow;
    const text = sourceText.trim();
    if (text) {
      current = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/inputs/text`,
        {
          method: "POST",
          body: JSON.stringify({ text }),
        },
      );
      setWorkflow(current);
      setSourceText("");
    }
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      current = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/inputs/file`,
        {
          method: "POST",
          body: form,
        },
      );
      setWorkflow(current);
      setFiles((pending) => pending.filter((item) => item !== file));
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
    return current;
  };

  const sendGuidance = async () => {
    if (!workflow || !guidanceText.trim()) return;
    if (!providerId) {
      toastError("请先选择可用的 AI 供应商");
      return;
    }
    setAction("guidance");
    setError(null);
    const message = guidanceText.trim();
    try {
      await persistPendingSources();
      const guided = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/guidance`,
        {
          method: "POST",
          body: JSON.stringify({ message, provider_id: providerId }),
        },
      );
      setWorkflow(guided);
      setGuidanceText("");
    } catch (guidanceError) {
      const messageText = (guidanceError as Error).message || "AI 判断资料失败";
      setError(messageText);
      toastError(messageText);
      await refresh();
    } finally {
      setAction(null);
    }
  };

  const analyze = async () => {
    if (
      !workflow ||
      (workflow.input_count === 0 && !sourceText.trim() && files.length === 0)
    ) {
      toastError("请先添加账务资料");
      return;
    }
    if (!providerId) {
      toastError("请先选择可用的 AI 供应商");
      return;
    }
    setAction("analyze");
    setError(null);
    try {
      await persistPendingSources();
      const analyzed = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/analyze`,
        {
          method: "POST",
          body: JSON.stringify({ provider_id: providerId }),
        },
      );
      setWorkflow(analyzed);
    } catch (analyzeError) {
      const message = (analyzeError as Error).message || "资料解析失败";
      setError(message);
      toastError(message);
      await refresh();
    } finally {
      setAction(null);
    }
  };

  const saveProposal = async (
    proposal: LedgerProposal,
    changes: Record<string, unknown>,
  ) => {
    if (!workflow) return;
    setAction(`save:${proposal.id}`);
    try {
      const updated = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/proposals/${proposal.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            expected_version: proposal.version,
            changes,
          }),
        },
      );
      setWorkflow(updated);
      success("提案已更新");
    } catch (saveError) {
      toastError((saveError as Error).message || "保存提案失败");
    } finally {
      setAction(null);
    }
  };

  const validate = async () => {
    if (!workflow || selectedProposalIds.size === 0) return;
    setAction("validate");
    try {
      const validated = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/validate`,
        {
          method: "POST",
          body: JSON.stringify({
            proposal_ids: Array.from(selectedProposalIds),
          }),
        },
      );
      setWorkflow(validated);
      if (validated.status === "ready") {
        success("规则校验通过，提案已冻结");
      } else {
        editorRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }
    } catch (validateError) {
      toastError((validateError as Error).message || "校验失败");
    } finally {
      setAction(null);
    }
  };

  const confirm = async () => {
    if (!workflow?.canonical_hash) return;
    setAction("confirm");
    if (!confirmKeyRef.current) confirmKeyRef.current = crypto.randomUUID();
    try {
      await apiRequest(`/ai/workflows/${workflow.id}/confirm`, {
        method: "POST",
        idempotencyKey: confirmKeyRef.current,
        body: JSON.stringify({
          workflow_version: workflow.version,
          canonical_hash: workflow.canonical_hash,
          proposal_ids: workflow.selected_proposal_ids,
        }),
      });
      confirmKeyRef.current = null;
      await refresh();
      success(
        workflow.command === "/冲正" || workflow.command.startsWith("/删除")
          ? "冲正已进入审批"
          : "账务已写入并完成核对",
      );
    } catch (confirmError) {
      setExecutionUnknown(true);
      toastError((confirmError as Error).message || "提交状态未知，请查询状态");
    } finally {
      setAction(null);
    }
  };

  const cancel = async () => {
    if (!workflow) return;
    setAction("cancel");
    try {
      const cancelled = await apiRequest<AIWorkflow>(
        `/ai/workflows/${workflow.id}/cancel`,
        { method: "POST" },
      );
      setWorkflow(cancelled);
    } catch (cancelError) {
      toastError((cancelError as Error).message || "取消工作流失败");
    } finally {
      setAction(null);
    }
  };

  if (isLoading) {
    return (
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="h-96 animate-pulse rounded-lg bg-surface-strong" />
        <div className="h-96 animate-pulse rounded-lg bg-surface-strong" />
      </div>
    );
  }

  if (error && !workflow) {
    return (
      <div className="flex min-h-72 flex-col items-center justify-center gap-3 rounded-lg border border-danger/25 bg-danger/5 p-6 text-center">
        <WarningCircle size={24} className="text-danger" />
        <p className="text-sm text-ink">{error}</p>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void loadInitial()}
        >
          <ArrowClockwise size={16} />
          重试
        </Button>
      </div>
    );
  }

  if (!workflow) {
    return (
      <section className="instrument-panel p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {commands.map((command) => {
            const Icon = commandIcon(command.command);
            return (
              <button
                key={command.command}
                type="button"
                disabled={action === "create"}
                onClick={() => void create(command.command)}
                className="instrument-control group flex min-h-24 items-start gap-3 p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5 disabled:opacity-50"
              >
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-strong text-primary group-hover:bg-primary/10">
                  <Icon size={19} />
                </span>
                <span className="min-w-0">
                  <span className="block font-mono text-xs font-semibold text-ink">
                    {command.command}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted">
                    {command.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </section>
    );
  }

  const state =
    statusMeta[executionUnknown ? "unknown" : workflow.status] ||
    statusMeta.unknown;
  const collecting =
    workflow.proposals.length === 0 && !terminalStatuses.has(workflow.status);
  const completed = terminalStatuses.has(workflow.status);
  const guidanceInputCount = workflow.messages.filter(
    (message) => message.role === "user",
  ).length;
  const persistedTextCount = Math.max(
    0,
    workflow.input_count - workflow.attachment_count - guidanceInputCount,
  );

  return (
    <div className="space-y-3 pb-20 lg:pb-0">
      <div className="instrument-strip flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Receipt size={17} />
          </span>
          <div className="min-w-0">
            <div className="truncate font-mono text-xs font-semibold text-ink">
              {workflow.command}
            </div>
            <div className="truncate text-[10px] text-muted">{workflow.id}</div>
          </div>
          <Badge variant={state.variant}>{state.label}</Badge>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            title="查询状态"
            aria-label="查询状态"
            disabled={action === "refresh"}
            onClick={() => void refresh()}
            className="rounded-md p-1.5 text-muted hover:bg-surface-strong hover:text-ink disabled:opacity-40"
          >
            <ArrowClockwise
              size={16}
              className={action === "refresh" ? "animate-spin" : ""}
            />
          </button>
          {!completed && workflow.status !== "committing" && (
            <button
              type="button"
              title="取消工作流"
              aria-label="取消工作流"
              onClick={() => void cancel()}
              className="rounded-md p-1.5 text-muted hover:bg-danger/10 hover:text-danger"
            >
              <Trash size={16} />
            </button>
          )}
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setWorkflow(null)}
            disabled={!completed}
          >
            <Plus size={15} />
            新建
          </Button>
        </div>
      </div>

      {executionUnknown && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-warning/35 bg-warning/10 px-3 py-2.5 text-xs text-ink">
          <span className="flex items-center gap-2">
            <WarningCircle size={16} className="text-warning" />
            执行状态未知
          </span>
          <Button size="sm" variant="secondary" onClick={() => void refresh()}>
            <MagnifyingGlass size={15} />
            查询状态
          </Button>
        </div>
      )}

      {collecting ? (
        <section className="instrument-panel overflow-hidden">
          <div className="grid lg:grid-cols-[minmax(0,1.08fr)_minmax(320px,.92fr)]">
            <div className="min-w-0 p-4 sm:p-5">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-xs font-semibold text-ink">账务资料</h3>
                <span className="text-[10px] tabular-nums text-muted">
                  {persistedTextCount} 条文本 · {workflow.attachment_count}{" "}
                  个附件
                </span>
              </div>
              <div className="space-y-4">
                <textarea
                  value={sourceText}
                  onChange={(event) => setSourceText(event.target.value)}
                  rows={10}
                  placeholder="粘贴账务资料"
                  className="w-full resize-y rounded-lg border border-border bg-surface-inset p-3 text-sm leading-6 text-ink shadow-control-inset outline-none placeholder:text-muted/70 focus:border-primary"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".txt,.md,.csv,.xls,.xlsx,.pdf,image/*"
                    className="sr-only"
                    onChange={(event) =>
                      setFiles(
                        Array.from(event.target.files || []).slice(0, 10),
                      )
                    }
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    <FileArrowUp size={16} />
                    添加附件
                  </Button>
                  <span className="text-xs text-muted">
                    {files.length
                      ? `待上传 ${files.length} 个文件`
                      : workflow.attachment_count
                        ? `已接收 ${workflow.attachment_count} 个文件`
                        : "未选择附件"}
                  </span>
                </div>
                {files.length > 0 && (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {files.map((file) => (
                      <div
                        key={`${file.name}-${file.size}`}
                        className="flex min-w-0 items-center justify-between gap-2 rounded-lg border border-border px-3 py-2 text-xs"
                      >
                        <span className="min-w-0 truncate text-ink">
                          {file.name}
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-muted">
                          {(file.size / 1024 / 1024).toFixed(1)} MB
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {error && (
                  <div className="rounded-lg border border-danger/25 bg-danger/5 p-3 text-xs text-danger">
                    {error}
                  </div>
                )}
                <div className="flex justify-end border-t border-border pt-3">
                  <Button
                    size="sm"
                    isLoading={action === "analyze"}
                    disabled={
                      !providerId ||
                      (workflow.input_count === 0 &&
                        !sourceText.trim() &&
                        files.length === 0) ||
                      action === "guidance"
                    }
                    onClick={() => void analyze()}
                  >
                    <MagnifyingGlass size={16} />
                    资料已齐，开始解析
                  </Button>
                </div>
              </div>
            </div>

            <div className="min-w-0 border-t border-border lg:border-l lg:border-t-0">
              <AIWorkflowGuidance
                messages={workflow.messages}
                value={guidanceText}
                disabled={!providerId || action === "analyze"}
                isSending={action === "guidance"}
                onChange={setGuidanceText}
                onSend={() => void sendGuidance()}
              />
            </div>
          </div>
        </section>
      ) : completed ? (
        <section className="instrument-panel p-6">
          <div className="flex min-h-52 flex-col items-center justify-center gap-3 text-center">
            <span
              className={`flex size-12 items-center justify-center rounded-lg ${
                workflow.status === "failed" || workflow.status === "expired"
                  ? "bg-danger/10 text-danger"
                  : workflow.status === "pending_approval"
                    ? "bg-warning/10 text-warning"
                    : "bg-success/10 text-success"
              }`}
            >
              {workflow.status === "cancelled" ? (
                <Prohibit size={24} />
              ) : workflow.status === "failed" ||
                workflow.status === "expired" ? (
                <WarningCircle size={24} />
              ) : (
                <CheckCircle size={24} />
              )}
            </span>
            <div className="text-sm font-semibold text-ink">{state.label}</div>
            {workflow.result.records && (
              <div className="text-xs text-muted">
                已核对 {workflow.result.records.length} 条记录
              </div>
            )}
            {workflow.status === "failed" && workflow.error && (
              <div className="max-w-lg text-xs text-danger">
                {workflow.error}
              </div>
            )}
            {workflow.result.approvals &&
              workflow.result.approvals.length > 0 && (
                <div className="text-xs text-muted">
                  {workflow.result.approvals.length} 项等待管理员审批
                </div>
              )}
          </div>
        </section>
      ) : (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1.15fr)_minmax(340px,.85fr)]">
          <section
            ref={editorRef}
            className="instrument-panel min-w-0 overflow-hidden"
          >
            {workflow.proposals.length > 1 && (
              <div className="data-table-shell overflow-x-auto border-b border-border">
                <table className="w-full min-w-[560px] text-left text-xs">
                  <thead className="bg-surface-inset text-muted">
                    <tr>
                      <th className="w-10 px-3 py-2 font-medium">选</th>
                      <th className="px-3 py-2 font-medium">序号</th>
                      <th className="px-3 py-2 font-medium">摘要</th>
                      <th className="px-3 py-2 font-medium">金额</th>
                      <th className="px-3 py-2 font-medium">状态</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {workflow.proposals.map((proposal) => (
                      <tr
                        key={proposal.id}
                        onClick={() => setActiveProposalId(proposal.id)}
                        className={`cursor-pointer transition-colors hover:bg-surface-strong/50 ${
                          activeProposalId === proposal.id ? "bg-primary/5" : ""
                        }`}
                      >
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={selectedProposalIds.has(proposal.id)}
                            onClick={(event) => event.stopPropagation()}
                            onChange={(event) => {
                              const next = new Set(selectedProposalIds);
                              if (event.target.checked) next.add(proposal.id);
                              else next.delete(proposal.id);
                              setSelectedProposalIds(next);
                            }}
                            className="accent-primary"
                          />
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {proposal.sequence}
                        </td>
                        <td className="max-w-56 truncate px-3 py-2">
                          {String(proposal.fields.description?.value || "-")}
                        </td>
                        <td className="px-3 py-2 font-mono">
                          {String(
                            proposal.fields.gross?.value ||
                              proposal.fields.cost?.value ||
                              "-",
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <Badge
                            variant={
                              proposal.validation.valid ? "success" : "warning"
                            }
                          >
                            {proposal.validation.valid ? "通过" : "待处理"}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="border-b border-border px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-xs font-semibold text-ink">
                  提案 {activeProposal?.sequence || 1}
                </h3>
                {activeProposal && (
                  <span className="font-mono text-[10px] text-muted">
                    v{activeProposal.version}
                  </span>
                )}
              </div>
            </div>
            <div className="p-4">
              {activeProposal && (
                <AIProposalEditor
                  proposal={activeProposal}
                  providers={providers}
                  categories={categories}
                  isSaving={action === `save:${activeProposal.id}`}
                  onSave={(changes) =>
                    void saveProposal(activeProposal, changes)
                  }
                />
              )}
            </div>
          </section>

          <aside className="instrument-panel min-w-0 overflow-hidden lg:sticky lg:top-0 lg:self-start">
            <AIWorkflowPreview proposal={activeProposal} />
          </aside>
        </div>
      )}

      {!collecting && !completed && (
        <div className="instrument-strip fixed inset-x-0 bottom-0 z-30 rounded-none border-x-0 border-b-0 px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur lg:static lg:rounded-lg lg:border">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-3">
            <div className="min-w-0 text-xs text-muted">
              {workflow.status === "ready" ? (
                <span className="flex items-center gap-2 text-success">
                  <ShieldCheck size={16} />
                  {workflow.selected_proposal_ids.length} 条提案已冻结
                </span>
              ) : (
                <span>{selectedProposalIds.size} 条提案待校验</span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {workflow.status === "ready" ? (
                <Button
                  size="sm"
                  isLoading={action === "confirm"}
                  onClick={() => void confirm()}
                >
                  <Check size={16} />
                  确认写入
                </Button>
              ) : (
                <Button
                  size="sm"
                  isLoading={action === "validate"}
                  disabled={selectedProposalIds.size === 0}
                  onClick={() => void validate()}
                >
                  <ShieldCheck size={16} />
                  执行规则校验
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
