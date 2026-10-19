/**
 * 设置 → AI 模型: which endpoints AI tasks may call (Anthropic, or any OpenAI-compatible relay), which one each task uses
 * with backups in order, and what it has cost. Keys are write-only: saved sealed on the server, shown as their last 4.
 * Admins change this here only; API and MCP tokens can't.
 */
import { useState } from "react";
import { clsx } from "clsx";
import { ArrowDown, ArrowUp, Lightning, Plus, Trash, X } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { useBook, useBookMutation, useBookQuery } from "@/api/queries";
import type { AiCapabilities, AiKind, AiProbe, AiProvider, AiRoute, AiRoutes, AiTask, AiUsageItem } from "@/api/types";
import { Badge, Button, Card, Chip, Empty, ErrorNote, Field, Input, Segmented, Select, Sheet, Skeleton, Switch } from "@/components/ui";
import { useToast } from "@/components/toast";

const KINDS: { value: AiKind; label: string }[] = [
  { value: "anthropic", label: "Anthropic" },
  { value: "openai_compatible", label: "OpenAI 兼容" },
];
const CAPS: [keyof AiCapabilities, string, string][] = [
  ["images", "图片", "能看截图"],
  ["pdf", "PDF", "能直接读 PDF；关掉则先用文字层，再转成图片"],
  ["structured", "结构化输出", "按 JSON Schema 作答；关掉则用 JSON 模式并校验、修一次"],
  ["tools", "工具调用", "AI 助手需要"],
  ["fallback", "服务端回退", "仅 Anthropic 官方；开启才发送 beta 请求头"],
];
const TASKS: { key: AiTask; label: string; hint: string }[] = [
  { key: "extract", label: "识别", hint: "截图与 PDF 读成记录" },
  { key: "agent", label: "AI 助手", hint: "按一句指令查账、记账、整理导入" },
];

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.detail : fallback;
}

function useCanEdit(): boolean {
  const role = useBook().data?.role;
  return role === "admin" || role === "owner";
}

export function AiModels() {
  const canEdit = useCanEdit();
  const providers = useBookQuery<AiProvider[]>("/ai/providers");
  const [open, setOpen] = useState<AiProvider | "new" | null>(null);
  const list = providers.data?.data ?? [];

  return (
    <div className="grid gap-6">
      <section className="grid gap-4" aria-labelledby="ai-providers">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 id="ai-providers" className="font-semibold">
              提供商
            </h2>
            <p className="text-sm text-ink-2">Anthropic 官方，或任何 OpenAI 兼容的地址（自己的中转站、其他厂商）。密钥只在服务器上加密保存。</p>
          </div>
          {canEdit && (
            <Button variant="primary" icon={<Plus size={16} weight="bold" />} onClick={() => setOpen("new")} className="shrink-0">
              添加
            </Button>
          )}
        </div>
        {providers.error ? (
          <ErrorNote error={providers.error} onRetry={() => providers.refetch()} />
        ) : !providers.data ? (
          <Skeleton className="h-24 w-full" />
        ) : list.length === 0 ? (
          <Card>
            <Empty title="还没有添加提供商">没添加时，识别使用服务器环境变量里的 BK_AI_API_KEY（如果设置了）。</Empty>
          </Card>
        ) : (
          <Card className="px-6 py-2 max-sm:px-5">
            <ul className="divide-y divide-line">
              {list.map((p) => (
                <ProviderRow key={p.id} provider={p} canEdit={canEdit} onOpen={() => setOpen(p)} />
              ))}
            </ul>
          </Card>
        )}
      </section>

      <Routes providers={list} canEdit={canEdit} />
      <Usage />

      <Sheet open={open !== null} onClose={() => setOpen(null)} title={open === "new" ? "添加 AI 提供商" : open ? open.name : ""} width={560}>
        {open !== null && <ProviderForm key={open === "new" ? "new" : open.id} provider={open === "new" ? null : open} onDone={() => setOpen(null)} />}
      </Sheet>
    </div>
  );
}

function ProviderRow({ provider: p, canEdit, onOpen }: { provider: AiProvider; canEdit: boolean; onOpen: () => void }) {
  const toast = useToast();
  const [probe, setProbe] = useState<AiProbe | null>(null);
  const test = useBookMutation(async (_: void, b) => (await api.post<AiProbe>(`/books/${b}/ai/providers/${p.id}:test`, {})).data);
  return (
    <li className="grid gap-2 py-3.5">
      <div className="flex items-center gap-4">
        <button type="button" onClick={onOpen} disabled={!canEdit} className="-mx-2 min-w-0 flex-1 rounded-field px-2 py-1 text-left transition-colors duration-150 enabled:hover:bg-well">
          <span className="flex items-center gap-2">
            <span className={clsx("truncate font-medium", !p.enabled && "text-ink-3")}>{p.name}</span>
            <Badge>{p.kind === "anthropic" ? "Anthropic" : "OpenAI 兼容"}</Badge>
            {!p.enabled && <Badge tone="warn">已停用</Badge>}
          </span>
          <span className="mt-0.5 block truncate text-sm text-ink-3">
            <span className="num">{p.base_url ?? "官方地址"}</span> · 默认 <span className="num">{p.default_model}</span> · 密钥 <span className="num">{p.key_hint ?? "未设置"}</span>
          </span>
        </button>
        {canEdit && (
          <Button
            size="sm"
            variant="ghost"
            icon={<Lightning size={14} />}
            loading={test.isPending}
            onClick={async () => {
              try {
                setProbe(await test.mutateAsync());
              } catch (e) {
                toast({ tone: "error", text: errorText(e, "测试失败：请稍后重试。") });
              }
            }}
          >
            测试连接
          </Button>
        )}
      </div>
      {probe && (
        <div className={clsx("rounded-field px-4 py-3 text-sm", probe.ok ? "bg-pos-wash" : "bg-warn-wash")} aria-live="polite">
          {probe.ok ? (
            <p className="font-medium">
              连接正常 · <span className="num">{probe.model}</span> 回复用时 <span className="num">{probe.latency_ms} ms</span>
            </p>
          ) : (
            <p className="font-medium text-warn-text">{probe.error}</p>
          )}
          {probe.models ? (
            <p className="mt-1 text-ink-2">
              可用模型 {probe.models.length} 个：<span className="num">{probe.models.slice(0, 12).join("、")}</span>
              {probe.models.length > 12 && " …"}
            </p>
          ) : (
            probe.models_error && <p className="mt-1 text-ink-3">模型列表读不到：{probe.models_error}</p>
          )}
          <p className="mt-1 text-ink-3">
            已开能力：
            {CAPS.filter(([k]) => probe.capabilities[k])
              .map(([, label]) => label)
              .join("、") || "无"}
          </p>
        </div>
      )}
    </li>
  );
}

function ProviderForm({ provider, onDone }: { provider: AiProvider | null; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState(() => ({
    name: provider?.name ?? "",
    kind: provider?.kind ?? ("openai_compatible" as AiKind),
    base_url: provider?.base_url ?? "",
    api_key: "",
    models: (provider?.models ?? []).join(", "),
    default_model: provider?.default_model ?? "",
    timeout_seconds: String(provider?.timeout_seconds ?? 120),
    enabled: provider?.enabled ?? true,
    capabilities: provider?.capabilities ?? null,
    effort: provider?.options.effort ?? "",
    max_tokens_param: provider?.options.max_tokens_param ?? "",
    prices: Object.fromEntries(Object.entries(provider?.prices ?? {}).map(([m, p]) => [m, { input: String(p.input), output: String(p.output) }])) as Record<string, { input: string; output: string }>,
  }));
  const models = f.models
    .split(/[,，\s]+/)
    .map((m) => m.trim())
    .filter(Boolean);
  const urlChanged = provider !== null && (provider.base_url ?? "") !== f.base_url.trim().replace(/\/+$/, "");
  const needsKey = provider === null || urlChanged;
  const caps: AiCapabilities = f.capabilities ?? { images: true, pdf: f.kind === "anthropic", structured: true, tools: true, fallback: false };

  const body = () => {
    const prices = Object.fromEntries(
      Object.entries(f.prices)
        .filter(([m, p]) => models.includes(m) && p.input.trim() !== "" && p.output.trim() !== "")
        .map(([m, p]) => [m, { input: Number(p.input), output: Number(p.output) }]),
    );
    const out: Record<string, unknown> = {
      name: f.name.trim(),
      base_url: f.base_url.trim() || null,
      models,
      default_model: f.default_model || models[0] || null,
      timeout_seconds: Number(f.timeout_seconds) || 120,
      enabled: f.enabled,
      capabilities: caps,
      options: { effort: f.kind === "anthropic" ? f.effort || null : null, max_tokens_param: f.kind === "openai_compatible" ? f.max_tokens_param || null : null },
      prices,
    };
    if (f.api_key.trim()) out.api_key = f.api_key.trim();
    if (provider) out.expected_version = provider.version;
    else out.kind = f.kind;
    return out;
  };
  const save = useBookMutation(async (_: void, b) => (provider ? api.patch<AiProvider>(`/books/${b}/ai/providers/${provider.id}`, body()) : api.post<AiProvider>(`/books/${b}/ai/providers`, body())));
  const remove = useBookMutation(async (_: void, b) => api.del(`/books/${b}/ai/providers/${provider?.id}`));

  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await save.mutateAsync();
          toast({ tone: "ok", text: provider ? `已保存 ${f.name}` : `已添加 ${f.name}，可以点“测试连接”试一下` });
          onDone();
        } catch {
          /* inline */
        }
      }}
    >
      {!provider && <Segmented label="类型" value={f.kind} onChange={(kind) => setF({ ...f, kind, capabilities: null })} options={KINDS} />}
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        <Field label="名称" required>
          {(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={f.kind === "anthropic" ? "Anthropic 官方" : "我的中转站"} autoFocus />}
        </Field>
        <Field label="超时（秒）">{(id) => <Input id={id} inputMode="numeric" className="num" value={f.timeout_seconds} onChange={(e) => setF({ ...f, timeout_seconds: e.target.value })} />}</Field>
        <Field label="Base URL" hint={f.kind === "anthropic" ? "留空 = 官方地址" : "如 https://relay.example.com/v1"} required={f.kind === "openai_compatible"} className="col-span-full">
          {(id, note) => <Input id={id} aria-describedby={note} className="num" value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder="https://" />}
        </Field>
        <Field
          label="API 密钥"
          hint={provider && !urlChanged ? `已保存 ${provider.key_hint ?? ""}；留空不改` : urlChanged ? "改了地址，请重新填写密钥" : "保存后只显示末 4 位"}
          required={needsKey}
          className="col-span-full"
        >
          {(id, note) => <Input id={id} aria-describedby={note} type="password" autoComplete="off" className="num" value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })} />}
        </Field>
        <Field label="模型" hint="逗号分隔" required className="col-span-full">
          {(id, note) => (
            <Input
              id={id}
              aria-describedby={note}
              className="num"
              value={f.models}
              onChange={(e) => setF({ ...f, models: e.target.value })}
              placeholder={f.kind === "anthropic" ? "claude-opus-5-5, claude-sonnet-5-5" : "model-a, model-b"}
            />
          )}
        </Field>
        <Field label="默认模型">
          {(id) => (
            <Select id={id} value={f.default_model || models[0] || ""} onChange={(e) => setF({ ...f, default_model: e.target.value })}>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {f.kind === "anthropic" ? (
          <Field label="推理强度" hint="越高越慢越贵">
            {(id, note) => (
              <Select id={id} aria-describedby={note} value={f.effort} onChange={(e) => setF({ ...f, effort: e.target.value })}>
                <option value="">模型默认</option>
                {["low", "medium", "high", "xhigh", "max"].map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : (
          <Field label="长度参数" hint="新模型多用 max_completion_tokens">
            {(id, note) => (
              <Select id={id} aria-describedby={note} value={f.max_tokens_param} onChange={(e) => setF({ ...f, max_tokens_param: e.target.value })}>
                <option value="">max_tokens</option>
                <option value="max_completion_tokens">max_completion_tokens</option>
              </Select>
            )}
          </Field>
        )}
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium text-ink-2">能力（不支持的会自动降级）</legend>
        <div className="flex flex-wrap gap-2">
          {CAPS.filter(([k]) => k !== "fallback" || f.kind === "anthropic").map(([k, label, hint]) => (
            <Chip key={k} on={caps[k]} title={hint} onClick={() => setF({ ...f, capabilities: { ...caps, [k]: !caps[k] } })}>
              {label}
            </Chip>
          ))}
        </div>
      </fieldset>
      {models.length > 0 && (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium text-ink-2">价格（美元 / 百万 token，可选，用于估算费用）</legend>
          {models.map((m) => {
            const price = f.prices[m] ?? { input: "", output: "" };
            const set = (patch: Partial<typeof price>) => setF({ ...f, prices: { ...f.prices, [m]: { ...price, ...patch } } });
            return (
              <div key={m} className="grid grid-cols-[minmax(0,1fr)_7rem_7rem] items-center gap-2">
                <span className="num truncate text-sm">{m}</span>
                <Input aria-label={`${m} 输入价格`} inputMode="decimal" className="num" placeholder="输入" value={price.input} onChange={(e) => set({ input: e.target.value })} />
                <Input aria-label={`${m} 输出价格`} inputMode="decimal" className="num" placeholder="输出" value={price.output} onChange={(e) => set({ output: e.target.value })} />
              </div>
            );
          })}
        </fieldset>
      )}
      <div className="flex items-center justify-between gap-4 rounded-field bg-well px-4 py-3">
        <span>
          <span className="block font-medium">启用</span>
          <span className="block text-sm text-ink-2">停用后，任务会跳到下一个备用</span>
        </span>
        <Switch label="启用" checked={f.enabled} onChange={(enabled) => setF({ ...f, enabled })} />
      </div>
      {save.error && <p className="text-sm text-neg">{errorText(save.error, "保存失败：请稍后重试。")}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" size="lg" className="flex-1" disabled={!f.name.trim() || !models.length || (needsKey && !f.api_key.trim())} loading={save.isPending}>
          {provider ? "保存" : "添加"}
        </Button>
        {provider && (
          <Button
            size="lg"
            variant="ghost"
            icon={<Trash size={16} />}
            loading={remove.isPending}
            onClick={async () => {
              try {
                await remove.mutateAsync();
                toast({ tone: "ok", text: `已删除 ${provider.name}` });
                onDone();
              } catch (e) {
                toast({ tone: "error", text: errorText(e, "删除失败：请稍后重试。") });
              }
            }}
          >
            删除
          </Button>
        )}
      </div>
    </form>
  );
}

function Routes({ providers, canEdit }: { providers: AiProvider[]; canEdit: boolean }) {
  const toast = useToast();
  const routes = useBookQuery<AiRoutes>("/ai/routes");
  const [draft, setDraft] = useState<AiRoutes | null>(null);
  const current: AiRoutes = draft ?? routes.data?.data ?? { extract: [], agent: [] };
  const save = useBookMutation(async (body: AiRoutes, b) => api.put<AiRoutes>(`/books/${b}/ai/routes`, body));
  const usable = providers.filter((p) => p.enabled && p.has_key);
  const set = (task: AiTask, rows: AiRoute[]) => setDraft({ ...current, [task]: rows });

  return (
    <section className="grid gap-4" aria-labelledby="ai-routes">
      <div>
        <h2 id="ai-routes" className="font-semibold">
          任务分配
        </h2>
        <p className="text-sm text-ink-2">每个任务按顺序用第一个；它连不上时自动换下一个。都不设时，识别使用 BK_AI_API_KEY。</p>
      </div>
      <Card className="grid gap-5 p-5">
        {TASKS.map((task) => {
          const rows = current[task.key];
          return (
            <div key={task.key} className="grid gap-2">
              <p className="text-sm">
                <span className="font-medium">{task.label}</span>
                <span className="text-ink-3"> · {task.hint}</span>
              </p>
              {rows.length === 0 && <p className="text-sm text-ink-3">未分配</p>}
              <ol className="grid gap-2">
                {rows.map((r, i) => {
                  const p = providers.find((x) => x.id === r.provider_id);
                  return (
                    <li key={`${r.provider_id}-${i}`} className="flex items-center gap-2">
                      <span className="num w-5 shrink-0 text-sm text-ink-3">{i + 1}</span>
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{p?.name ?? r.provider_name ?? r.provider_id}</span>
                      <Select
                        aria-label={`${task.label} 第 ${i + 1} 个的模型`}
                        value={r.model}
                        disabled={!canEdit}
                        className="max-w-56"
                        onChange={(e) =>
                          set(
                            task.key,
                            rows.map((x, j) => (j === i ? { ...x, model: e.target.value } : x)),
                          )
                        }
                      >
                        {(p?.models ?? [r.model]).map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </Select>
                      {canEdit && (
                        <>
                          <Button size="sm" variant="ghost" aria-label="上移" icon={<ArrowUp size={14} />} disabled={i === 0} onClick={() => set(task.key, swap(rows, i, i - 1))} />
                          <Button size="sm" variant="ghost" aria-label="下移" icon={<ArrowDown size={14} />} disabled={i === rows.length - 1} onClick={() => set(task.key, swap(rows, i, i + 1))} />
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label="移除"
                            icon={<X size={14} />}
                            onClick={() =>
                              set(
                                task.key,
                                rows.filter((_, j) => j !== i),
                              )
                            }
                          />
                        </>
                      )}
                    </li>
                  );
                })}
              </ol>
              {canEdit && usable.length > 0 && rows.length < 5 && (
                <Select
                  aria-label={`给${task.label}添加提供商`}
                  value=""
                  className="max-w-72"
                  onChange={(e) => {
                    const p = usable.find((x) => x.id === e.target.value);
                    if (p) set(task.key, [...rows, { provider_id: p.id, model: p.default_model ?? p.models[0] ?? "" }]);
                  }}
                >
                  <option value="">＋ 添加{rows.length ? "备用" : ""}提供商</option>
                  {usable.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </Select>
              )}
            </div>
          );
        })}
        {canEdit && draft && (
          <div className="flex gap-2">
            <Button
              variant="primary"
              loading={save.isPending}
              onClick={async () => {
                try {
                  await save.mutateAsync({
                    extract: current.extract.map(({ provider_id, model }) => ({ provider_id, model })),
                    agent: current.agent.map(({ provider_id, model }) => ({ provider_id, model })),
                  });
                  setDraft(null);
                  toast({ tone: "ok", text: "已保存任务分配" });
                } catch (e) {
                  toast({ tone: "error", text: errorText(e, "保存失败：请稍后重试。") });
                }
              }}
            >
              保存分配
            </Button>
            <Button variant="ghost" onClick={() => setDraft(null)}>
              放弃修改
            </Button>
          </div>
        )}
      </Card>
    </section>
  );
}

function swap<T>(rows: T[], i: number, j: number): T[] {
  const next = [...rows];
  [next[i], next[j]] = [next[j]!, next[i]!];
  return next;
}

function Usage() {
  const usage = useBookQuery<{ days: number; items: AiUsageItem[] }>("/ai/usage", { days: 30 });
  const items = usage.data?.data.items ?? [];
  const total = items.reduce((s, u) => s + (u.cost_usd ?? 0), 0);
  return (
    <section className="grid gap-4" aria-labelledby="ai-usage">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="ai-usage" className="font-semibold">
          近 30 天用量
        </h2>
        {items.some((u) => u.cost_usd !== null) && <span className="figure text-lg">≈ ${total.toFixed(2)}</span>}
      </div>
      {usage.error ? (
        <ErrorNote error={usage.error} onRetry={() => usage.refetch()} />
      ) : !usage.data ? (
        <Skeleton className="h-16 w-full" />
      ) : items.length === 0 ? (
        <p className="text-sm text-ink-3">还没有调用。</p>
      ) : (
        <Card className="px-6 py-2 max-sm:px-5">
          <ul className="divide-y divide-line">
            {items.map((u) => (
              <li key={`${u.provider}-${u.model}-${u.task}`} className="flex items-center gap-4 py-3 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {u.provider} · <span className="num">{u.model}</span>
                  </span>
                  <span className="block text-ink-3">
                    {u.task_label} · <span className="num">{u.calls}</span> 次 · 输入 <span className="num">{u.input_tokens.toLocaleString()}</span> · 输出{" "}
                    <span className="num">{u.output_tokens.toLocaleString()}</span> token
                  </span>
                </span>
                <span className="num shrink-0">{u.cost_usd === null ? "未设价格" : `≈ $${u.cost_usd.toFixed(2)}${u.cost_complete ? "" : "+"}`}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}
