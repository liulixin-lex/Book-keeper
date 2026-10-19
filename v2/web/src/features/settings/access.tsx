/** Access and the book itself: AI connections and tokens, the log of every write (each undoable), and account & data. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { clsx } from "clsx";
import { CheckCircle, Copy, DownloadSimple, Key, Plus, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { useBook, useBookMutation, useBookQuery, useCan, useLabel, useUndo } from "@/api/queries";
import type { ChangeSet, Token, TokenTier } from "@/api/types";
import { useBookId } from "@/app/book";
import { signOut, ThemeSwitch } from "@/app/Shell";
import { Badge, Button, Card, Empty, ErrorNote, Field, Input, Row, Segmented, Sheet, Skeleton, Switch } from "@/components/ui";
import { useToast } from "@/components/toast";
import { bookDate, shortDate } from "@/lib/format";
import { rangeOf } from "@/lib/period";

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.detail : fallback;
}

function when(at: string): string {
  return `${shortDate(at.slice(0, 10))} ${new Date(at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" })}`;
}

/** A destructive button that asks once more in place instead of opening a dialog. */
function TwoStep({ label, confirm, onConfirm, loading }: { label: string; confirm: string; onConfirm: () => void; loading?: boolean }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const id = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(id);
  }, [armed]);
  return (
    <Button
      size="sm"
      variant="danger"
      loading={loading}
      onClick={() => {
        if (!armed) return setArmed(true);
        setArmed(false);
        onConfirm();
      }}
    >
      {armed ? confirm : label}
    </Button>
  );
}

/* ---------- AI 接入 ---------- */

const TIERS: TokenTier[] = ["user_read", "user_write", "admin_read", "admin_write"];

export function AiAccess() {
  const bookId = useBookId();
  const label = useLabel();
  const toast = useToast();
  const tokens = useBookQuery<Token[]>("/tokens");
  const [creating, setCreating] = useState(false);
  const [issued, setIssued] = useState<Token | null>(null);
  const revoke = useBookMutation(async (id: string, b) => api.post(`/books/${b}/tokens/${id}:revoke`, {}));
  const rotate = useBookMutation(async (id: string, b) => (await api.post<Token>(`/books/${b}/tokens/${id}:rotate`, {})).data);
  const mcpUrl = `${window.location.origin}/mcp`;
  const restUrl = `${window.location.origin}/api/v1/books/${bookId}`;
  const list = (tokens.data?.data ?? []).filter((t) => !t.revoked_at);

  async function copy(text: string, what: string) {
    await navigator.clipboard.writeText(text).catch(() => undefined);
    toast({ tone: "ok", text: `已复制${/^[A-Za-z0-9]/.test(what) ? " " : ""}${what}` }); // 已复制 MCP 地址 · 已复制令牌
  }

  return (
    <div className="grid gap-5">
      <Card className="p-6 max-sm:p-5">
        <h3 className="font-semibold">连接地址</h3>
        <p className="mt-1 text-sm text-ink-2">claude.ai、ChatGPT 等支持 OAuth 的应用直接填 MCP 地址，用本账号登录授权；脚本和命令行用下面的令牌，放在 Authorization: Bearer 中。</p>
        <div className="mt-4 grid gap-2">
          {[
            ["MCP", mcpUrl],
            ["REST", restUrl],
          ].map(([k, url]) => (
            <div key={k} className="flex items-center gap-3 rounded-field bg-well py-1.5 pr-1.5 pl-4">
              <span className="w-11 shrink-0 text-sm font-semibold text-ink-2">{k}</span>
              <code className="num min-w-0 flex-1 truncate text-sm">{url}</code>
              <Button size="sm" variant="ghost" icon={<Copy size={14} />} onClick={() => copy(url!, `${k} 地址`)}>
                复制
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <section className="grid gap-2" aria-labelledby="tokens-title">
        <header className="flex items-center justify-between pl-6 max-sm:pl-5">
          <h3 id="tokens-title" className="text-sm font-semibold text-ink-2">
            API 令牌
          </h3>
          <Button size="sm" variant="primary" icon={<Plus size={14} weight="bold" />} onClick={() => setCreating(true)}>
            新令牌
          </Button>
        </header>
        {tokens.error ? (
          <ErrorNote error={tokens.error} onRetry={() => tokens.refetch()} />
        ) : !tokens.data ? (
          <Skeleton className="h-20 w-full" />
        ) : list.length === 0 ? (
          <Card>
            <Empty icon={<Key size={22} />} title="还没有令牌">
              给每个 AI 或脚本单独建一个令牌，操作记录里能分清是谁写的，也能随时吊销。
            </Empty>
          </Card>
        ) : (
          <Card className="px-6 py-2 max-sm:px-5">
            <ul className="divide-y divide-line">
              {list.map((t) => (
                <li key={t.id} className="flex flex-wrap items-center gap-3 py-3.5">
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate font-medium">{t.name}</span>
                      <Badge>{label("token_tier", t.tier)}</Badge>
                      {t.effective_tier !== undefined && <Badge tone="warn">{t.effective_tier ? `角色已降低，现按${label("token_tier", t.effective_tier)}` : "已失效"}</Badge>}
                      {t.mcp_enabled && <Badge tone="pos">MCP</Badge>}
                    </span>
                    <span className="num mt-0.5 block truncate text-sm text-ink-3">
                      {t.token_prefix}… · {t.last_used_at ? `最近使用 ${when(t.last_used_at)}` : "还没用过"}
                      {t.expires_at && ` · ${t.expires_at.slice(0, 10)} 到期`}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={rotate.isPending && rotate.variables === t.id}
                    onClick={async () => {
                      try {
                        setIssued(await rotate.mutateAsync(t.id));
                      } catch (e) {
                        toast({ tone: "error", text: errorText(e, "轮换失败：请稍后重试。") });
                      }
                    }}
                  >
                    轮换
                  </Button>
                  <TwoStep
                    label="吊销"
                    confirm="再点一次吊销"
                    loading={revoke.isPending && revoke.variables === t.id}
                    onConfirm={async () => {
                      try {
                        await revoke.mutateAsync(t.id);
                        toast({ tone: "ok", text: `已吊销 ${t.name}，用它的连接会立即失效` });
                      } catch (e) {
                        toast({ tone: "error", text: errorText(e, "吊销失败：请稍后重试。") });
                      }
                    }}
                  />
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>

      <Sheet open={creating} onClose={() => setCreating(false)} title="新建 API 令牌" width={480}>
        {creating && (
          <CreateToken
            onIssued={(t) => {
              setCreating(false);
              setIssued(t);
            }}
          />
        )}
      </Sheet>
      <Sheet open={!!issued} onClose={() => setIssued(null)} title="令牌只显示这一次" width={480}>
        {issued?.token && (
          <div className="grid gap-4">
            <p className="text-sm text-ink-2">复制后存进 AI 应用或脚本的配置。关掉之后就看不到了，丢了可以轮换。</p>
            <code className="num block rounded-field bg-well px-4 py-3.5 text-sm break-all">{issued.token}</code>
            <Button variant="primary" size="lg" icon={<Copy size={16} />} onClick={() => copy(issued.token!, "令牌")}>
              复制令牌
            </Button>
          </div>
        )}
      </Sheet>
    </div>
  );
}

function CreateToken({ onIssued }: { onIssued: (t: Token) => void }) {
  const label = useLabel();
  const allowed = useBook().data?.token_tiers ?? [];
  const [name, setName] = useState("");
  const [tier, setTier] = useState<TokenTier>(allowed.includes("user_write") ? "user_write" : "user_read");
  const [mcp, setMcp] = useState(true);
  const [days, setDays] = useState<"30" | "90" | "365" | "never">("90");
  const create = useBookMutation(
    async (_: void, b) =>
      (await api.post<Token>(`/books/${b}/tokens`, { name: name.trim(), tier, mcp_enabled: mcp, ...(days === "never" ? { never_expires: true } : { expires_in_days: Number(days) }) })).data,
  );
  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          onIssued(await create.mutateAsync());
        } catch {
          /* inline */
        }
      }}
    >
      <Field label="名称" hint="写清是哪个 AI 或脚本，如 Claude 桌面版" required>
        {(id, note) => <Input id={id} aria-describedby={note} value={name} onChange={(e) => setName(e.target.value)} autoFocus />}
      </Field>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium text-ink-2">权限档位</legend>
        <div role="radiogroup" aria-label="权限档位" className="grid gap-2">
          {TIERS.map((t) => {
            const may = allowed.includes(t);
            return (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={tier === t}
                disabled={!may}
                onClick={() => setTier(t)}
                className={clsx(
                  "grid gap-0.5 rounded-field border px-4 py-3 text-left transition-colors duration-150",
                  tier === t ? "border-ink bg-card shadow-lift" : "border-line enabled:hover:bg-well",
                  !may && "opacity-55",
                )}
              >
                <span className="font-medium">{label("token_tier", t)}</span>
                <span className="text-sm text-ink-2">{may ? label("token_tier_hint", t) : "需要管理员角色"}</span>
              </button>
            );
          })}
        </div>
      </fieldset>
      <div className="grid gap-2">
        <p className="text-sm font-medium text-ink-2">有效期</p>
        <Segmented
          label="有效期"
          value={days}
          onChange={setDays}
          className="w-full"
          options={[
            { value: "30", label: "30 天" },
            { value: "90", label: "90 天" },
            { value: "365", label: "1 年" },
            { value: "never", label: "永不过期" },
          ]}
        />
      </div>
      <div className="flex items-center justify-between gap-4 rounded-field bg-well px-4 py-3">
        <span>
          <span className="block font-medium">允许通过 MCP 使用</span>
          <span className="block text-sm text-ink-2">关掉后只能用 REST 接口</span>
        </span>
        <Switch label="允许通过 MCP 使用" checked={mcp} onChange={setMcp} />
      </div>
      {create.error && <p className="text-sm text-neg">{errorText(create.error, "生成失败：请稍后重试。")}</p>}
      <Button type="submit" variant="primary" size="lg" disabled={!name.trim()} loading={create.isPending}>
        生成令牌
      </Button>
    </form>
  );
}

/* ---------- 操作记录 ---------- */

const OPS: Record<string, string> = {
  "transaction.create": "记一笔",
  "transactions.create": "记一笔",
  "transactions.batch": "批量记账",
  "transaction.update": "修改交易",
  "transactions.edit": "修改交易",
  "transaction.delete": "删除交易",
  "transactions.delete": "删除交易",
  "transaction.restore": "恢复交易",
  "transactions.restore": "恢复交易",
  "transactions.repost": "按新规则重算",
  "transaction.repost": "按新规则重算",
  "imports.commit": "完成导入",
  "import_batches.upload": "上传账单",
  "import_batches.create": "导入记录",
  "imports.revert": "撤销导入",
  "source_records.classify": "补全导入记录",
  "rules.apply": "应用分类规则",
  "change_sets.undo": "撤销",
  "fee_rules.create": "保存手续费规则",
  "fee_rules.retire": "停用手续费规则",
  "checks.run": "数据检查",
};

const ENTITY: Record<string, string> = {
  transaction: "交易",
  source_record: "导入记录",
  import_batch: "导入",
  fee_rule: "手续费规则",
  counterparty: "往来方",
  rule: "分类规则",
  token: "令牌",
  file: "文件",
};

function opName(op: string): string {
  if (OPS[op]) return OPS[op];
  const [entity = "", verb = ""] = op.split(".");
  const e = ENTITY[entity.replace(/s$/, "")] ?? entity;
  const v = { create: "新建", update: "修改", delete: "删除", post: "过账", reverse: "冲正", revoke: "吊销", rotate: "轮换", enable: "启用", disable: "停用", save: "保存" }[verb] ?? verb;
  return `${v}${e}`;
}

export function Activity() {
  const label = useLabel();
  const toast = useToast();
  const undo = useUndo();
  const sets = useBookQuery<ChangeSet[]>("/change-sets", { limit: 60 });
  const audits = useCan("admin:read");
  const verify = useBookQuery<{ ok: boolean }>("/audit-events/verify", undefined, { staleTime: 5 * 60_000, enabled: audits });
  const list = (sets.data?.data ?? []).filter((s) => s.operation !== "checks.run");

  return (
    <div className="grid gap-4">
      {audits && (
        <p className="flex items-center gap-2 text-sm text-ink-2">
          {verify.data?.data.ok ? <ShieldCheck size={18} weight="fill" className="shrink-0 text-pos" /> : <ShieldCheck size={18} className="shrink-0 text-ink-3" />}
          {verify.data ? (verify.data.data.ok ? "所有写入都留有记录，审计链完整，没有被改动过" : "审计链校验没通过，请在「账户与数据」里运行数据检查") : "正在校验审计记录…"}
        </p>
      )}
      {sets.error ? (
        <ErrorNote error={sets.error} onRetry={() => sets.refetch()} />
      ) : !sets.data ? (
        <Skeleton className="h-64 w-full" />
      ) : list.length === 0 ? (
        <Card>
          <Empty title="还没有写入">记账、导入和 AI 的每次写入都会记在这里，可以整次撤销。</Empty>
        </Card>
      ) : (
        <Card className="px-6 py-2 max-sm:px-5">
          <ul className="divide-y divide-line">
            {list.map((s) => {
              const counts = Object.entries(s.entity_counts)
                .map(([k, v]) => `${ENTITY[k] ?? k} ${v}`)
                .join("、");
              const undone = s.status !== "applied";
              return (
                <li key={s.id} className="flex items-center gap-3 py-3">
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className={clsx("font-medium", undone && "text-ink-3")}>{opName(s.operation)}</span>
                      {s.channel !== "ui" && <Badge>{label("created_channel", s.channel)}</Badge>}
                      {undone && <Badge>{s.status === "undone" ? "已撤销" : s.status}</Badge>}
                    </span>
                    <span className="num mt-0.5 block truncate text-sm text-ink-3">
                      {when(s.created_at)}
                      {s.mcp_client && ` · ${s.mcp_client}`}
                      {counts && ` · ${counts}`}
                    </span>
                  </span>
                  {!undone && s.operation !== "change_sets.undo" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={undo.isPending && undo.variables === s.id}
                      onClick={async () => {
                        try {
                          await undo.mutateAsync(s.id);
                          toast({ tone: "ok", text: `已撤销「${opName(s.operation)}」` });
                        } catch (e) {
                          toast({ tone: "error", text: errorText(e, "撤销失败：请稍后重试。") });
                        }
                      }}
                    >
                      撤销
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}

/* ---------- 账户与数据 ---------- */

interface CheckRun {
  id: string;
  status: string;
  started_at: string;
  summary: { checks?: number; errors?: string[]; warnings?: string[] };
  results?: { code: string; severity: string; status: string; count: number; message: string }[];
}

const EXPORTS = [
  { fmt: "xlsx", label: "Excel" },
  { fmt: "csv", label: "CSV" },
  { fmt: "beancount", label: "Beancount" },
  { fmt: "json", label: "JSON" },
];

export function Account() {
  const bookId = useBookId();
  const book = useBook().data;
  const navigate = useNavigate();
  const toast = useToast();
  const today = bookDate();
  const [span, setSpan] = useState<"month" | "last-month" | "year" | "all">("month");
  const runs = useBookQuery<CheckRun[]>("/check-runs", { limit: 1 });
  const run = useBookMutation(async (_: void, b) => (await api.post<CheckRun>(`/books/${b}/checks:run`, {})).data);
  const [result, setResult] = useState<CheckRun | null>(null);
  const [pw, setPw] = useState({ current: "", next: "" });
  const change = useBookMutation(async () => api.post("/auth/password", { current_password: pw.current, new_password: pw.next }));
  const last = result ?? runs.data?.data[0] ?? null;
  const r = span === "all" ? null : rangeOf(span, today);
  const query = r ? `?date_from=${r.from}&date_to=${r.to}` : "";
  const problems = (result?.results ?? []).filter((x) => x.status !== "passed");

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card className="p-6 max-sm:p-5">
        <h3 className="font-semibold">外观</h3>
        <div className="mt-3 flex items-center justify-between gap-4">
          <span className="text-sm text-ink-2">跟随系统，或固定浅色、深色</span>
          <ThemeSwitch />
        </div>
        <div className="mt-5 divide-y divide-line border-t border-line">
          <Row label="账套">{book?.name ?? "—"}</Row>
          <Row label="本位币">
            <span className="num">{book?.base_commodity ?? "—"}</span>
          </Row>
          <Row label="时区">{book?.timezone ?? "—"}</Row>
        </div>
      </Card>

      <Card className="p-6 max-sm:p-5">
        <h3 className="font-semibold">导出</h3>
        <p className="mt-1 text-sm text-ink-2">导出分录明细；Beancount 文件可以直接用 bean-check 校验。</p>
        <Segmented
          label="导出范围"
          value={span}
          onChange={setSpan}
          className="mt-4"
          options={[
            { value: "month", label: "本月" },
            { value: "last-month", label: "上月" },
            { value: "year", label: "今年" },
            { value: "all", label: "全部" },
          ]}
        />
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {EXPORTS.map((x) => (
            <a
              key={x.fmt}
              href={`/api/v1/books/${bookId}/exports/${x.fmt}${query}`}
              download
              className="inline-flex h-10 items-center justify-center gap-2 rounded-full bg-well px-4 font-medium transition-colors duration-150 hover:bg-well-2"
            >
              <DownloadSimple size={16} />
              {x.label}
            </a>
          ))}
        </div>
      </Card>

      <Card className="p-6 max-sm:p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold">数据检查</h3>
            <p className="mt-1 text-sm text-ink-2">核对借贷平衡、哈希链、余额和重复交易。</p>
          </div>
          <Button
            size="sm"
            loading={run.isPending}
            onClick={async () => {
              try {
                setResult(await run.mutateAsync());
              } catch (e) {
                toast({ tone: "error", text: errorText(e, "检查失败：请稍后重试。") });
              }
            }}
          >
            立即检查
          </Button>
        </div>
        {last && (
          <div className="mt-4 rounded-field bg-well px-4 py-3">
            <p className="flex items-center gap-2 font-medium">
              {last.status === "passed" ? <CheckCircle size={18} weight="fill" className="text-pos" /> : <WarningCircle size={18} weight="fill" className="text-warn" />}
              {last.status === "passed" ? `${last.summary.checks ?? ""} 项检查通过` : "有检查没通过"}
              <span className="ml-auto text-sm font-normal text-ink-3">{when(last.started_at)}</span>
            </p>
            {(last.summary.warnings?.length ?? 0) > 0 && <p className="mt-1 text-sm text-ink-2">提示：{last.summary.warnings!.join("、")}</p>}
            {problems.map((p) => (
              <p key={p.code} className={clsx("mt-1 text-sm", p.severity === "error" ? "text-neg" : "text-warn-text")}>
                {p.message}
              </p>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-6 max-sm:p-5">
        <h3 className="font-semibold">修改密码</h3>
        <form
          className="mt-4 grid gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await change.mutateAsync();
              toast({ tone: "ok", text: "密码已修改" });
              setPw({ current: "", next: "" });
            } catch {
              /* inline */
            }
          }}
        >
          <Field label="当前密码">{(id) => <Input id={id} type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />}</Field>
          <Field label="新密码" hint="至少 12 位" error={change.error ? errorText(change.error, "修改失败：请稍后重试。") : undefined}>
            {(id, note) => <Input id={id} type="password" autoComplete="new-password" aria-describedby={note} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />}
          </Field>
          <div className="flex items-center justify-between gap-3">
            <Button type="submit" disabled={!pw.current || pw.next.length < 12} loading={change.isPending}>
              修改密码
            </Button>
            <Button variant="danger" onClick={() => signOut(navigate)}>
              退出登录
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
