/**
 * AI 助手: say what to do in one sentence, watch each step it takes, answer if it asks, and take the whole run back
 * with one click (its writes share one change set). It works with your permissions ∩ the chosen tier; with files
 * attached it only reads and stages, so text inside a file cannot get anything booked or deleted.
 */
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { clsx } from "clsx";
import { ArrowCounterClockwise, CheckCircle, ChatCircleDots, Paperclip, ShieldWarning, Sparkle, Stop, X, XCircle } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { useBookMutation, useBookQuery, useLabel, useUndo } from "@/api/queries";
import type { AgentRun, AgentRunDetail, AgentStatus, AgentStep, Playbook, TokenTier } from "@/api/types";
import { Badge, Button, Card, Chip, Empty, ErrorNote, Input, PageHeader, Segmented, Select, Skeleton, Textarea } from "@/components/ui";
import { useToast } from "@/components/toast";
import { shortDate } from "@/lib/format";

const ACTIVE: AgentStatus[] = ["queued", "running", "waiting"];
const STATUS: Record<AgentStatus, { label: string; tone: "neutral" | "pos" | "neg" | "warn" }> = {
  queued: { label: "排队中", tone: "neutral" },
  running: { label: "进行中", tone: "neutral" },
  waiting: { label: "等你回答", tone: "warn" },
  done: { label: "完成", tone: "pos" },
  failed: { label: "没完成", tone: "neg" },
  cancelled: { label: "已停止", tone: "neutral" },
};
const TIERS: TokenTier[] = ["user_read", "user_write", "admin_read", "admin_write"];

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.detail : fallback;
}

function when(at: string): string {
  return `${shortDate(at.slice(0, 10))} ${new Date(at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" })}`;
}

export default function Assistant() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("run");
  const status = useBookQuery<{ extract: boolean; agent: boolean }>("/ai/status");
  const runs = useBookQuery<AgentRun[]>("/agent/runs", { limit: 20 }, { refetchInterval: (d) => (d?.data.some((r) => ACTIVE.includes(r.status)) ? 3000 : false) });
  const open = (id: string) => setParams({ run: id });
  const detail = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // On a phone the run opens below the list: bring it into view when one is picked.
    if (selected && !window.matchMedia("(min-width: 1024px)").matches) detail.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [selected]);
  const list = runs.data?.data ?? [];
  const current = selected ?? list[0]?.id ?? null;

  return (
    <>
      <PageHeader title="AI 助手" />
      <div className="grid gap-5 lg:grid-cols-12 lg:items-start">
        <div className="grid gap-5 lg:col-span-5">
          {status.data && !status.data.data.agent ? (
            <Card>
              <Empty icon={<Sparkle size={22} />} title="AI 助手还没配置">
                管理员在{" "}
                <Link to="/settings/ai-models" className="font-medium text-ink underline underline-offset-2">
                  设置 → AI 模型
                </Link>{" "}
                给“AI 助手”分配一个模型后就能用。
              </Empty>
            </Card>
          ) : (
            <Composer onStarted={open} />
          )}
          <section aria-labelledby="runs-title" className="grid gap-2">
            <h2 id="runs-title" className="pl-6 text-sm font-semibold text-ink-2 max-sm:pl-5">
              最近
            </h2>
            {runs.error ? (
              <ErrorNote error={runs.error} onRetry={() => runs.refetch()} />
            ) : !runs.data ? (
              <Skeleton className="h-32 w-full" />
            ) : list.length === 0 ? (
              <p className="pl-6 text-sm text-ink-3 max-sm:pl-5">还没有让 AI 做过事。</p>
            ) : (
              <Card className="p-1.5">
                <ul className="grid gap-0.5">
                  {list.map((r) => (
                    <li key={r.id}>
                      <button
                        type="button"
                        onClick={() => open(r.id)}
                        aria-current={r.id === current ? "true" : undefined}
                        className={clsx(
                          "flex w-full items-center gap-3 rounded-[14px] px-3.5 py-2.5 text-left transition-colors duration-150",
                          r.id === current ? "shadow-lift ring-1 ring-line" : "hover:bg-well",
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{r.instruction}</span>
                          <span className="block text-sm text-ink-3">{when(r.created_at)}</span>
                        </span>
                        <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </section>
        </div>
        <div ref={detail} className="scroll-mt-4 lg:col-span-7">
          {current ? <RunView key={current} runId={current} /> : null}
        </div>
      </div>
    </>
  );
}

function Composer({ onStarted }: { onStarted: (id: string) => void }) {
  const label = useLabel();
  const toast = useToast();
  const [text, setText] = useState("");
  const [tier, setTier] = useState<TokenTier>("user_write");
  const [files, setFiles] = useState<{ id: string; name: string }[]>([]);
  const [playbook, setPlaybook] = useState<string | null>(null);
  const scenarios = (useBookQuery<Playbook[]>("/ai/playbooks").data?.data ?? []).filter((p) => p.tiers.includes(tier));
  const chosen = scenarios.find((p) => p.code === playbook) ?? null;
  const picker = useRef<HTMLInputElement>(null);
  const upload = useBookMutation(async (list: File[], b) => {
    const out: { id: string; name: string }[] = [];
    for (const file of list) {
      const form = new FormData();
      form.append("file", file);
      const res = await api.upload<{ id: string; original_name: string }>(`/books/${b}/files`, form);
      out.push({ id: res.data.id, name: res.data.original_name });
    }
    return out;
  });
  const start = useBookMutation(
    async (_: void, b) => (await api.post<AgentRun>(`/books/${b}/agent/runs`, { instruction: text.trim(), tier, file_ids: files.map((f) => f.id), playbook: chosen?.code ?? null })).data,
  );

  return (
    <Card className="p-6 max-sm:p-5">
      <form
        className="grid gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            const run = await start.mutateAsync();
            setText("");
            setFiles([]);
            setPlaybook(null);
            onStarted(run.id);
          } catch {
            /* inline */
          }
        }}
      >
        <label htmlFor="agent-instruction" className="font-semibold">
          要做什么
        </label>
        {scenarios.length > 0 && (
          <div className="grid gap-2">
            <div role="radiogroup" aria-label="场景（可选）" className="flex flex-wrap gap-2">
              {scenarios.map((p) => (
                <Chip
                  key={p.code}
                  role="radio"
                  aria-checked={chosen?.code === p.code}
                  on={chosen?.code === p.code}
                  title={p.when}
                  onClick={() => {
                    const next = chosen?.code === p.code ? null : p.code;
                    setPlaybook(next);
                    if (next && !text.trim()) setText(`${p.title}：`);
                  }}
                >
                  {p.title}
                </Chip>
              ))}
            </div>
            {chosen && (
              <p className="text-sm text-ink-3">
                按场景步骤做：{chosen.when} 完成标准：{chosen.done}
              </p>
            )}
          </div>
        )}
        <Textarea
          id="agent-instruction"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="一句话说清楚，例如：把这几张充值截图导入；或：上个月各渠道的手续费一共多少"
          className="resize-y"
        />
        {files.length > 0 && (
          <ul className="flex flex-wrap gap-2" aria-label="附件">
            {files.map((f) => (
              <li key={f.id} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-well pr-1 pl-3 text-sm">
                <span className="max-w-48 truncate">{f.name}</span>
                <button type="button" aria-label={`移除 ${f.name}`} onClick={() => setFiles(files.filter((x) => x.id !== f.id))} className="grid size-6 place-items-center rounded-full hover:bg-card">
                  <X size={12} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="grid gap-2">
          <p className="text-sm font-medium text-ink-2">权限</p>
          <Segmented label="权限" value={tier} onChange={setTier} options={TIERS.map((t) => ({ value: t, label: label("token_tier", t) }))} size="sm" className="w-full max-sm:hidden" />
          <Select aria-label="权限" value={tier} onChange={(e) => setTier(e.target.value as TokenTier)} className="sm:hidden">
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {label("token_tier", t)}
              </option>
            ))}
          </Select>
          <p className="text-sm text-ink-3">{files.length ? "带了文件：这次只读取和暂存导入，不会入账、修改或删除。" : `${label("token_tier_hint", tier)}。不会超出你自己的权限。`}</p>
        </div>
        {(start.error || upload.error) && <p className="text-sm text-neg">{errorText(start.error ?? upload.error, "没能开始：请稍后重试。")}</p>}
        <div className="flex gap-2">
          <input
            ref={picker}
            type="file"
            multiple
            hidden
            accept="image/png,image/jpeg,image/webp,application/pdf,text/csv,text/plain,.csv,.txt,.json"
            onChange={async (e) => {
              const picked = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (!picked.length) return;
              try {
                setFiles([...files, ...(await upload.mutateAsync(picked))]);
              } catch (err) {
                toast({ tone: "error", text: errorText(err, "上传失败：请稍后重试。") });
              }
            }}
          />
          <Button variant="ghost" icon={<Paperclip size={16} />} loading={upload.isPending} onClick={() => picker.current?.click()}>
            附文件
          </Button>
          <Button type="submit" variant="primary" icon={<Sparkle size={16} weight="fill" />} className="flex-1" disabled={!text.trim() || upload.isPending} loading={start.isPending}>
            开始
          </Button>
        </div>
      </form>
    </Card>
  );
}

function RunView({ runId }: { runId: string }) {
  const toast = useToast();
  const undo = useUndo();
  const run = useBookQuery<AgentRunDetail>(`/agent/runs/${runId}`, undefined, { refetchInterval: (d) => (d && ["queued", "running"].includes(d.data.status) ? 1500 : false) });
  const cancel = useBookMutation(async (_: void, b) => api.post(`/books/${b}/agent/runs/${runId}:cancel`, {}));
  const [reply, setReply] = useState("");
  const answer = useBookMutation(async (_: void, b) => api.post(`/books/${b}/agent/runs/${runId}:answer`, { answer: reply.trim() }));

  if (run.error) return <ErrorNote error={run.error} onRetry={() => run.refetch()} />;
  if (!run.data) return <Skeleton className="h-72 w-full rounded-[20px]" />;
  const r = run.data.data;
  const active = ACTIVE.includes(r.status);
  // The instruction is the header and the final answer has its own card: the timeline shows what happened between.
  const steps = r.steps.filter((s) => s.kind !== "instruction" && !(s.kind === "assistant" && (!s.text || (!s.calls && s.text === r.result))));
  const working = active && r.status !== "waiting";

  return (
    <Card className="p-6 max-sm:p-5">
      <header className="grid gap-2">
        <p className="text-lg font-semibold whitespace-pre-wrap">{r.instruction}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
          <Badge>{r.tier_label}</Badge>
          {r.stage === "recognition" && <Badge tone="warn">只读取与暂存</Badge>}
          {r.change_set_status === "reverted" && <Badge>已撤销</Badge>}
        </div>
      </header>

      <ol className={clsx("grid gap-3", (steps.length > 0 || working) && "mt-5")} aria-live="polite" aria-label="步骤">
        {steps.map((s) => (
          <StepRow key={s.seq} step={s} />
        ))}
        {working && (
          <li className="flex items-center gap-2.5 text-sm text-ink-3">
            <span aria-hidden className="size-2 animate-pulse rounded-full bg-ink-3" />
            {r.status === "queued" ? "排队中…" : "正在处理…"}
          </li>
        )}
      </ol>

      {r.status === "waiting" && r.question && (
        <form
          className="mt-5 grid gap-3 rounded-field bg-warn-wash p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await answer.mutateAsync();
              setReply("");
              run.refetch();
            } catch (err) {
              toast({ tone: "error", text: errorText(err, "没能发送：请稍后重试。") });
            }
          }}
        >
          <label htmlFor="agent-reply" className="font-medium text-warn-text">
            {r.question}
          </label>
          <div className="flex gap-2">
            <Input id="agent-reply" value={reply} onChange={(e) => setReply(e.target.value)} className="flex-1" autoFocus />
            <Button type="submit" variant="primary" disabled={!reply.trim()} loading={answer.isPending}>
              回答
            </Button>
          </div>
        </form>
      )}

      {r.result && (
        <div className="mt-5 rounded-field bg-pos-wash px-4 py-3">
          <p className="whitespace-pre-wrap">{r.result}</p>
        </div>
      )}
      {r.error && <p className="mt-5 rounded-field bg-well px-4 py-3 text-sm text-ink-2">{r.error}</p>}

      <footer className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <span className="num text-sm text-ink-3">
          {r.turns} 轮 · {(r.input_tokens + r.output_tokens).toLocaleString()} token{r.cost_usd !== null && ` · ≈ $${r.cost_usd.toFixed(2)}`}
          {r.model && ` · ${r.model}`}
        </span>
        <span className="flex gap-2">
          {active && (
            <Button
              size="sm"
              variant="ghost"
              icon={<Stop size={14} />}
              loading={cancel.isPending}
              onClick={async () => {
                await cancel.mutateAsync().catch((e) => toast({ tone: "error", text: errorText(e, "没能停止。") }));
                run.refetch();
              }}
            >
              停止
            </Button>
          )}
          {!active && r.change_set_id && r.change_set_status === "applied" && (
            <Button
              size="sm"
              variant="danger"
              icon={<ArrowCounterClockwise size={14} />}
              loading={undo.isPending}
              onClick={async () => {
                try {
                  await undo.mutateAsync(r.change_set_id!);
                  toast({ tone: "ok", text: "已撤销这次的全部写入" });
                  run.refetch();
                } catch (e) {
                  toast({ tone: "error", text: errorText(e, "撤销失败：请稍后重试。") });
                }
              }}
            >
              撤销本次全部写入
            </Button>
          )}
        </span>
      </footer>
    </Card>
  );
}

function StepRow({ step: s }: { step: AgentStep }) {
  if (s.kind === "assistant") {
    return (
      <li className="flex gap-3">
        <span aria-hidden className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-lime text-lime-ink">
          <Sparkle size={14} weight="fill" />
        </span>
        <p className="min-w-0 flex-1 whitespace-pre-wrap">{s.text}</p>
      </li>
    );
  }
  if (s.kind === "note") {
    return (
      <li className="flex gap-3 text-sm text-warn-text">
        <ShieldWarning size={18} className="mt-0.5 shrink-0" />
        <span>{s.text}</span>
      </li>
    );
  }
  if (s.kind === "tool" && s.tool === "ask_user") {
    return (
      <li className="flex gap-3 text-sm">
        <ChatCircleDots size={18} className="mt-0.5 shrink-0 text-ink-3" />
        <span className="min-w-0">
          <span className="block text-ink-2">问：{String(s.arguments?.question ?? "")}</span>
          <span className="block font-medium">答：{s.message}</span>
        </span>
      </li>
    );
  }
  if (s.kind === "tool") {
    return (
      <li className="flex gap-3 text-sm">
        {s.ok ? <CheckCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-pos" /> : <XCircle size={18} weight="fill" className="mt-0.5 shrink-0 text-neg" />}
        <span className="min-w-0">
          <span className="block font-medium">{s.title}</span>
          {s.message && <span className={clsx("block break-words", s.ok ? "text-ink-3" : "text-neg")}>{s.message}</span>}
        </span>
      </li>
    );
  }
  return null;
}
