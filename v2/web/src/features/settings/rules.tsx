/** Rules that fill things in for you: fee rules (what a channel keeps), classification rules (how a statement line is booked) and import sources. */
import { useState } from "react";
import { clsx } from "clsx";
import { Plus, Trash } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { changeSetOf, useBookMutation, useBookQuery, useCategories, useChannels, useNames, useTransactionTypes } from "@/api/queries";
import type { FeeRule, ImportSource, Rule, RuleAction, RuleCondition } from "@/api/types";
import { Badge, Button, Card, Chip, DateInput, Empty, ErrorNote, Field, Input, Select, Sheet, Skeleton, Switch, Textarea } from "@/components/ui";
import { useToast, useUndoToast } from "@/components/toast";
import { KIND_NAMES } from "@/features/imports/Imports";
import { SourceMapping } from "./SourceMapping";
import { bookDate, formatMoney, percent } from "@/lib/format";

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.detail : fallback;
}

function Loading() {
  return (
    <Card className="grid gap-5 p-5">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </Card>
  );
}

/* ---------- 手续费规则 ---------- */

const FEE_TYPES = ["sale", "credit_purchase", "expense", "transfer", "sale_refund"];

function rateText(r: FeeRule): string {
  const parts = [r.rate ? percent(Number(r.rate), 2).replace(/\.00%$/, "%") : null, r.fixed_minor !== null ? formatMoney({ minor: r.fixed_minor, commodity: r.commodity ?? "CNY" }) : null].filter(
    Boolean,
  );
  return parts.join(" + ") || "—";
}

export function FeeRules() {
  const toast = useToast();
  const types = useTransactionTypes().data ?? [];
  const names = useNames();
  const rules = useBookQuery<FeeRule[]>("/fee-rules");
  const [open, setOpen] = useState<FeeRule | "new" | null>(null);
  const retire = useBookMutation(async (code: string, b) => api.post(`/books/${b}/fee-rules/${code}:retire`, {}));
  const list = rules.data?.data ?? [];
  const typeNames = (codes: string[]) => (codes.length ? codes.map((c) => types.find((t) => t.code === c)?.name ?? c).join("、") : "销售收入、额度采购");
  const channelNames = (ids: string[]) => (ids.length ? ids.map((id) => names.channel.get(id)?.name ?? id).join("、") : "所有渠道");

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-ink-2">记账时没填手续费，就按这里算；同一代码再保存一次就是新版本，从生效日起适用。</p>
        <Button variant="primary" icon={<Plus size={16} weight="bold" />} onClick={() => setOpen("new")} className="shrink-0">
          新增规则
        </Button>
      </div>
      {rules.error ? (
        <ErrorNote error={rules.error} onRetry={() => rules.refetch()} />
      ) : !rules.data ? (
        <Loading />
      ) : list.length === 0 ? (
        <Card>
          <Empty title="还没有手续费规则">比如链动销售扣 3%：建一条，以后记链动的销售就自动算出到账金额。</Empty>
        </Card>
      ) : (
        <Card className="px-6 py-2 max-sm:px-5">
          <ul className="divide-y divide-line">
            {list.map((r) => (
              <li key={`${r.code}-${r.valid_from}`} className="flex items-center gap-4 py-3.5">
                <button type="button" onClick={() => setOpen(r)} className="-mx-2 min-w-0 flex-1 rounded-field px-2 py-1 text-left transition-colors duration-150 hover:bg-well">
                  <span className="flex items-center gap-2">
                    <span className={clsx("truncate font-medium", r.valid_to && "text-ink-3")}>{r.name ?? r.code}</span>
                    {r.is_estimate && <Badge tone="warn">估算</Badge>}
                    {r.valid_to && <Badge>止于 {r.valid_to}</Badge>}
                  </span>
                  <span className="mt-0.5 block truncate text-sm text-ink-3">
                    {typeNames(r.transaction_types)} · {channelNames(r.channel_ids)}
                    {r.counterparty_ids.length > 0 && ` · ${r.counterparty_ids.map((id) => names.counterparty.get(id) ?? id).join("、")}`} · 自 {r.valid_from}
                  </span>
                </button>
                <span className="figure shrink-0 text-lg">{rateText(r)}</span>
                {!r.valid_to && (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={retire.isPending && retire.variables === r.code}
                    onClick={async () => {
                      try {
                        await retire.mutateAsync(r.code);
                        toast({ tone: "ok", text: `已停用 ${r.name ?? r.code}` });
                      } catch (e) {
                        toast({ tone: "error", text: errorText(e, "停用失败：请稍后重试。") });
                      }
                    }}
                  >
                    停用
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Sheet
        open={open !== null}
        onClose={() => setOpen(null)}
        title={open === "new" ? "新增手续费规则" : open ? `新版本 · ${open.name ?? open.code}` : ""}
        subtitle={open && open !== "new" ? "新费率从生效日期起适用" : undefined}
        width={500}
      >
        {open !== null && <FeeRuleForm key={open === "new" ? "new" : open.id} rule={open === "new" ? null : open} onDone={() => setOpen(null)} />}
      </Sheet>
    </div>
  );
}

function FeeRuleForm({ rule, onDone }: { rule: FeeRule | null; onDone: () => void }) {
  const toast = useToast();
  const undoToast = useUndoToast();
  const types = useTransactionTypes().data ?? [];
  const channels = useChannels();
  const names = useNames();
  const [f, setF] = useState({
    code: rule?.code ?? "",
    name: rule?.name ?? "",
    rate: rule?.rate ? String(Number((Number(rule.rate) * 100).toFixed(4))) : "",
    fixed: rule?.fixed_minor != null ? String(rule.fixed_minor / 100) : "",
    channels: (rule?.channel_ids ?? []).map((id) => names.channel.get(id)?.code ?? id),
    transaction_types: rule?.transaction_types ?? [],
    counterparties: (rule?.counterparty_ids ?? []).map((id) => names.counterparty.get(id) ?? id).join(", "),
    valid_from: bookDate(),
    is_estimate: rule?.is_estimate ?? false,
  });
  const body = () => ({
    code: f.code.trim(),
    name: f.name.trim() || null,
    rate: f.rate ? String(Number(f.rate) / 100) : null,
    fixed: f.fixed.trim() || null,
    channels: f.channels,
    transaction_types: f.transaction_types,
    counterparties: f.counterparties
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean),
    valid_from: f.valid_from,
    is_estimate: f.is_estimate,
  });
  const save = useBookMutation(async (_: void, b) => api.post(`/books/${b}/fee-rules`, body()));
  const repost = useBookMutation(async (rb: Record<string, unknown>, b) => api.post<{ reposted: number; fee_delta: number }>(`/books/${b}/transactions:repost`, rb));
  const toggle = (key: "channels" | "transaction_types", v: string) => setF((s) => ({ ...s, [key]: s[key].includes(v) ? s[key].filter((x) => x !== v) : [...s[key], v] }));

  async function recompute(saved: ReturnType<typeof body>) {
    try {
      const res = await repost.mutateAsync({
        reason: `手续费规则 ${saved.name ?? saved.code} 调整`,
        types: saved.transaction_types.length ? saved.transaction_types : ["sale", "credit_purchase"],
        channels: saved.channels,
        date_from: saved.valid_from,
      });
      if (res.data.reposted === 0) toast({ tone: "ok", text: "已有交易的手续费都不用变" });
      else undoToast(`已按新规则重算 ${res.data.reposted} 笔`, changeSetOf(res), "已改回重算前的手续费");
    } catch (e) {
      toast({ tone: "error", text: errorText(e, "重算失败：请稍后重试。") });
    }
  }

  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        const saved = body();
        try {
          await save.mutateAsync();
          onDone();
          toast({ tone: "ok", text: `已保存 ${saved.name ?? saved.code}，${saved.valid_from} 起的新交易按它算`, action: { label: "重算已有交易", run: () => recompute(saved) } });
        } catch {
          /* inline */
        }
      }}
    >
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        <Field label="名称">{(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="链动销售扣费" autoFocus={!rule} />}</Field>
        <Field label="代码" hint={rule ? "同代码保存即新版本" : "如 liandong_sale"} required>
          {(id, note) => <Input id={id} aria-describedby={note} value={f.code} disabled={!!rule} onChange={(e) => setF({ ...f, code: e.target.value })} className="num" />}
        </Field>
        <Field label="费率 %" hint="3 表示 3%">
          {(id, note) => <Input id={id} aria-describedby={note} inputMode="decimal" className="num" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} autoFocus={!!rule} />}
        </Field>
        <Field label="每笔固定额" hint="可选，如 0.30">
          {(id, note) => <Input id={id} aria-describedby={note} inputMode="decimal" className="num" value={f.fixed} onChange={(e) => setF({ ...f, fixed: e.target.value })} />}
        </Field>
        <Field label="生效日期" required className="col-span-full">
          {(id) => <DateInput id={id} value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} />}
        </Field>
      </div>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium text-ink-2">适用的交易（不选 = 销售收入与额度采购）</legend>
        <div className="flex flex-wrap gap-2">
          {FEE_TYPES.map((code) => (
            <Chip key={code} on={f.transaction_types.includes(code)} onClick={() => toggle("transaction_types", code)}>
              {types.find((t) => t.code === code)?.name ?? code}
            </Chip>
          ))}
        </div>
      </fieldset>
      <fieldset className="grid gap-2">
        <legend className="mb-2 text-sm font-medium text-ink-2">渠道（不选 = 所有渠道）</legend>
        <div className="flex flex-wrap gap-2">
          {channels.map((c) => (
            <Chip key={c.code} on={f.channels.includes(c.code)} onClick={() => toggle("channels", c.code)}>
              {c.name}
            </Chip>
          ))}
        </div>
      </fieldset>
      <Field label="往来方" hint="逗号分隔；留空 = 所有往来方">
        {(id, note) => <Input id={id} aria-describedby={note} value={f.counterparties} onChange={(e) => setF({ ...f, counterparties: e.target.value })} />}
      </Field>
      <div className="flex items-center justify-between gap-4 rounded-field bg-well px-4 py-3">
        <span>
          <span className="block font-medium">标为估算</span>
          <span className="block text-sm text-ink-2">算出的手续费先算估算，等实际到账再核对</span>
        </span>
        <Switch label="标为估算" checked={f.is_estimate} onChange={(is_estimate) => setF({ ...f, is_estimate })} />
      </div>
      {save.error && <p className="text-sm text-neg">{errorText(save.error, "保存失败：请稍后重试。")}</p>}
      <Button type="submit" variant="primary" size="lg" disabled={!f.code.trim() || (!f.rate.trim() && !f.fixed.trim())} loading={save.isPending}>
        保存规则
      </Button>
    </form>
  );
}

/* ---------- 分类规则 ---------- */

const FIELDS: [string, string][] = [
  ["counterparty_text", "对方名称"],
  ["description", "摘要 / 商品"],
  ["direction", "收支方向"],
  ["amount", "金额"],
  ["order_no", "订单号"],
  ["status_text", "状态文字"],
];
const OPS: [string, string][] = [
  ["contains", "包含"],
  ["eq", "等于"],
  ["starts_with", "开头是"],
  ["regex", "匹配正则"],
  ["gte", "大于等于"],
  ["lte", "小于等于"],
  ["not_contains", "不包含"],
];
const ACTIONS: [string, string][] = [
  ["set_transaction_type", "记为"],
  ["set_category", "收支分类"],
  ["set_counterparty", "往来方"],
  ["set_channel", "渠道"],
  ["ignore", "忽略"],
];

export function Rules() {
  const toast = useToast();
  const rules = useBookQuery<Rule[]>("/rules");
  const types = useTransactionTypes().data ?? [];
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const toggle = useBookMutation(async (r: Rule, b) => api.post(`/books/${b}/rules/${r.code}:${r.is_active ? "disable" : "enable"}`, {}));
  const list = rules.data?.data ?? [];
  const fieldName = (f: string) => FIELDS.find((x) => x[0] === f)?.[1] ?? f;
  const opName = (o: string) => OPS.find((x) => x[0] === o)?.[1] ?? o;
  const actText = (a: RuleAction) =>
    a.type === "ignore"
      ? "忽略"
      : a.type === "set_transaction_type"
        ? `记为${types.find((t) => t.code === a.value)?.name ?? a.value}`
        : `${ACTIONS.find((x) => x[0] === a.type)?.[1] ?? a.type} ${a.value ?? ""}`;

  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-ink-2">导入账单时按顺序匹配，命中就自动填好类型、往来方、分类和渠道。</p>
        <Button variant="primary" icon={<Plus size={16} weight="bold" />} onClick={() => setEditing("new")} className="shrink-0">
          新增规则
        </Button>
      </div>
      {rules.error ? (
        <ErrorNote error={rules.error} onRetry={() => rules.refetch()} />
      ) : !rules.data ? (
        <Loading />
      ) : list.length === 0 ? (
        <Card>
          <Empty title="还没有分类规则">常见的对方建一条，比如“对方名称包含 Vultr → 费用支出 · 服务器与网络”，以后导入就不用手动分类。</Empty>
        </Card>
      ) : (
        <Card className="px-6 py-2 max-sm:px-5">
          <ul className="divide-y divide-line">
            {list.map((r) => {
              const conds = (r.condition.all ?? r.condition.any ?? []) as RuleCondition[];
              return (
                <li key={r.id} className="flex items-center gap-4 py-3.5">
                  <button type="button" onClick={() => setEditing(r)} className="-mx-2 min-w-0 flex-1 rounded-field px-2 py-1 text-left transition-colors duration-150 hover:bg-well">
                    <span className={clsx("block truncate font-medium", !r.is_active && "text-ink-3")}>{r.name ?? r.code}</span>
                    <span className="mt-0.5 block truncate text-sm text-ink-3">
                      当 {conds.map((c) => `${fieldName(c.field)}${opName(c.op)}「${c.value}」`).join("且") || "自定义条件"} → {r.actions.map(actText).join("，")}
                    </span>
                  </button>
                  <Switch
                    label={`启用规则 ${r.name ?? r.code}`}
                    checked={r.is_active}
                    onChange={async () => {
                      try {
                        await toggle.mutateAsync(r);
                      } catch (e) {
                        toast({ tone: "error", text: errorText(e, "修改失败：请稍后重试。") });
                      }
                    }}
                  />
                </li>
              );
            })}
          </ul>
        </Card>
      )}
      <Sheet open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "新增分类规则" : editing ? (editing.name ?? editing.code) : ""} width={560}>
        {editing !== null && <RuleForm key={editing === "new" ? "new" : editing.id} rule={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Sheet>
    </div>
  );
}

interface TestResult {
  checked: number;
  hits: number;
  samples: { counterparty_text?: string; description?: string; amount?: { display?: string } }[];
}

function RuleForm({ rule, onDone }: { rule: Rule | null; onDone: () => void }) {
  const toast = useToast();
  const types = useTransactionTypes().data ?? [];
  const categories = useCategories();
  const channels = useChannels();
  const [name, setName] = useState(rule?.name ?? "");
  const [conds, setConds] = useState<RuleCondition[]>(((rule?.condition.all ?? rule?.condition.any) as RuleCondition[] | undefined) ?? [{ field: "counterparty_text", op: "contains", value: "" }]);
  const [acts, setActs] = useState<{ type: string; value: string }[]>(
    rule?.actions.map((a) => ({ type: a.type, value: String(a.type === "ignore" ? (a.reason ?? "") : (a.value ?? "")) })) ?? [{ type: "set_transaction_type", value: "expense" }],
  );
  const [test, setTest] = useState<TestResult | null>(null);

  const body = () => ({
    code: rule?.code ?? `rule_${Date.now().toString(36)}`,
    name: name.trim() || null,
    stage: "classify",
    condition: { all: conds.filter((c) => c.value.trim()).map((c) => ({ ...c, value: c.value.trim() })) },
    actions: acts.map((a) => (a.type === "ignore" ? { type: "ignore", reason: a.value.trim() || "规则忽略" } : { type: a.type, value: a.value })),
  });
  const runTest = useBookMutation(async (_: void, b) => (await api.post<TestResult>(`/books/${b}/rules:test`, { rule: body(), limit: 500 })).data);
  const save = useBookMutation(async (_: void, b) => api.post(`/books/${b}/rules`, body()));
  const setCond = (i: number, patch: Partial<RuleCondition>) => setConds(conds.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const setAct = (i: number, patch: Partial<{ type: string; value: string }>) => setActs(acts.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const valueInput = (a: { type: string; value: string }, i: number) => {
    const set = (value: string) => setAct(i, { value });
    if (a.type === "set_transaction_type")
      return (
        <Select aria-label="交易类型" value={a.value} onChange={(e) => set(e.target.value)}>
          {types
            .filter((t) => t.input_mode === "inputs" && t.is_active)
            .map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
        </Select>
      );
    if (a.type === "set_category")
      return (
        <Select aria-label="收支分类" value={a.value} onChange={(e) => set(e.target.value)}>
          <option value="">选择分类</option>
          {categories.map((x) => (
            <option key={x.id} value={x.code}>
              {x.name}
            </option>
          ))}
        </Select>
      );
    if (a.type === "set_channel")
      return (
        <Select aria-label="渠道" value={a.value} onChange={(e) => set(e.target.value)}>
          <option value="">选择渠道</option>
          {channels.map((c) => (
            <option key={c.id} value={c.code}>
              {c.name}
            </option>
          ))}
        </Select>
      );
    if (a.type === "ignore") return <Input aria-label="忽略原因" placeholder="原因，如 个人转账" value={a.value} onChange={(e) => set(e.target.value)} />;
    return <Input aria-label="往来方" placeholder="如 Vultr" value={a.value} onChange={(e) => set(e.target.value)} />;
  };

  const ready = conds.some((c) => c.value.trim()) && acts.every((a) => a.type === "ignore" || a.value);
  const error = [save.error, runTest.error].find((e) => e instanceof ApiError) as ApiError | undefined;

  return (
    <div className="grid gap-6">
      <Field label="名称">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="Vultr 记服务器费用" autoFocus={!rule} />}</Field>
      <fieldset className="grid gap-2">
        <legend className="mb-2 font-semibold">当记录满足全部条件</legend>
        {conds.map((c, i) => (
          <div key={i} className="grid grid-cols-[132px_112px_minmax(0,1fr)_36px] gap-2 max-sm:grid-cols-2">
            <Select aria-label="字段" value={c.field} onChange={(e) => setCond(i, { field: e.target.value })}>
              {FIELDS.map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
            <Select aria-label="比较" value={c.op} onChange={(e) => setCond(i, { op: e.target.value })}>
              {OPS.map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
            {c.field === "direction" ? (
              <Select aria-label="方向" value={c.value} onChange={(e) => setCond(i, { op: "eq", value: e.target.value })}>
                <option value="">选择</option>
                <option value="in">收入</option>
                <option value="out">支出</option>
              </Select>
            ) : (
              <Input aria-label="值" value={c.value} onChange={(e) => setCond(i, { value: e.target.value })} placeholder={c.field === "amount" ? "如 50.00" : "如 Vultr"} />
            )}
            <button
              type="button"
              aria-label="删除条件"
              disabled={conds.length <= 1}
              onClick={() => setConds(conds.filter((_, j) => j !== i))}
              className="grid size-10 place-items-center rounded-full text-ink-3 hover:bg-well hover:text-neg disabled:opacity-30"
            >
              <Trash size={16} />
            </button>
          </div>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus size={14} />} className="justify-self-start" onClick={() => setConds([...conds, { field: "description", op: "contains", value: "" }])}>
          加条件
        </Button>
      </fieldset>
      <fieldset className="grid gap-2">
        <legend className="mb-2 font-semibold">就这样处理</legend>
        {acts.map((a, i) => (
          <div key={i} className="grid grid-cols-[132px_minmax(0,1fr)_36px] gap-2">
            <Select aria-label="动作" value={a.type} onChange={(e) => setAct(i, { type: e.target.value, value: "" })}>
              {ACTIONS.map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
            {valueInput(a, i)}
            <button
              type="button"
              aria-label="删除动作"
              disabled={acts.length <= 1}
              onClick={() => setActs(acts.filter((_, j) => j !== i))}
              className="grid size-10 place-items-center rounded-full text-ink-3 hover:bg-well hover:text-neg disabled:opacity-30"
            >
              <Trash size={16} />
            </button>
          </div>
        ))}
        <Button size="sm" variant="ghost" icon={<Plus size={14} />} className="justify-self-start" onClick={() => setActs([...acts, { type: "set_category", value: "" }])}>
          加动作
        </Button>
      </fieldset>
      {test && (
        <div className="rounded-field bg-well px-4 py-3 text-sm">
          <p>
            在最近 <span className="num">{test.checked}</span> 条记录里命中 <span className="num font-semibold">{test.hits}</span> 条
          </p>
          {test.samples.slice(0, 5).map((s, i) => (
            <p key={i} className="num mt-1 truncate text-ink-2">
              {[s.counterparty_text, s.description, s.amount?.display].filter(Boolean).join(" · ")}
            </p>
          ))}
        </div>
      )}
      {error && <p className="text-sm text-neg">{error.detail}</p>}
      <div className="flex gap-2">
        <Button className="flex-1" disabled={!ready} loading={runTest.isPending} onClick={async () => setTest(await runTest.mutateAsync().catch(() => null))}>
          用历史记录试一下
        </Button>
        <Button
          variant="primary"
          className="flex-1"
          disabled={!ready}
          loading={save.isPending}
          onClick={async () => {
            try {
              await save.mutateAsync();
              toast({ tone: "ok", text: "已保存分类规则，新导入的记录会自动套用" });
              onDone();
            } catch {
              /* inline */
            }
          }}
        >
          保存规则
        </Button>
      </div>
    </div>
  );
}

/* ---------- 导入来源 ---------- */

interface DirectionDefault {
  type?: string;
  channel?: string;
  category?: string;
  ignore?: string;
}

export function Sources() {
  const sources = useBookQuery<ImportSource[]>("/import-sources");
  const types = useTransactionTypes().data ?? [];
  const [editing, setEditing] = useState<ImportSource | "new" | null>(null);
  const list = sources.data?.data ?? [];
  const typeName = (code?: string) => types.find((t) => t.code === code)?.name ?? code ?? "未设";
  return (
    <div className="grid gap-4">
      <div className="flex justify-end">
        <Button variant="primary" icon={<Plus size={16} weight="bold" />} onClick={() => setEditing("new")}>
          新增来源
        </Button>
      </div>
      {sources.error ? (
        <ErrorNote error={sources.error} onRetry={() => sources.refetch()} />
      ) : !sources.data ? (
        <Loading />
      ) : (
        <Card className="px-6 py-2 max-sm:px-5">
          <ul className="divide-y divide-line">
            {list.map((s) => {
              const d = (s.config.defaults ?? {}) as Record<string, DirectionDefault>;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setEditing(s)}
                    className="-mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-field px-2 py-3 text-left transition-colors duration-150 hover:bg-well"
                  >
                    <span className="min-w-0 flex-1">
                      <span className={clsx("block font-medium", !s.is_active && "text-ink-3")}>{s.name}</span>
                      <span className="block truncate text-sm text-ink-3">
                        {KIND_NAMES[s.kind] ?? s.kind}
                        {d.in && ` · 收入${d.in.ignore ? "默认忽略" : `记为${typeName(d.in.type)}`}`}
                        {d.out && ` · 支出${d.out.ignore ? "默认忽略" : `记为${typeName(d.out.type)}`}`}
                      </span>
                    </span>
                    {!s.is_active && <Badge>已停用</Badge>}
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
      <Sheet open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "新增导入来源" : editing ? editing.name : ""} width={600}>
        {editing !== null && <SourceForm key={editing === "new" ? "new" : editing.id} source={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Sheet>
    </div>
  );
}

function SourceForm({ source, onDone }: { source: ImportSource | null; onDone: () => void }) {
  const toast = useToast();
  const types = useTransactionTypes().data ?? [];
  const categories = useCategories();
  const channels = useChannels();
  const defaults = (source?.config.defaults ?? {}) as Record<string, DirectionDefault>;
  const [code, setCode] = useState(source?.code ?? "");
  const [name, setName] = useState(source?.name ?? "");
  const [kind, setKind] = useState(source?.kind ?? "wechat_bill");
  const [active, setActive] = useState(source?.is_active ?? true);
  const [dirs, setDirs] = useState<Record<"in" | "out", DirectionDefault>>({ in: defaults.in ?? {}, out: defaults.out ?? {} });
  // Everything in the config besides the per-direction defaults: column mapping, AI hint, credit rate…
  const [extra, setExtra] = useState<Record<string, unknown>>(() => {
    const { defaults: _defaults, ...rest } = source?.config ?? {};
    return rest;
  });
  const aiStatus = useBookQuery<{ extract: boolean; agent: boolean }>("/ai/status");
  const config = () => {
    const clean = (d: DirectionDefault) => Object.fromEntries(Object.entries(d).filter(([, v]) => v));
    return { ...extra, defaults: { ...defaults, in: clean(dirs.in), out: clean(dirs.out) } };
  };
  const setOption = (key: string, value: unknown) => setExtra((e) => Object.fromEntries(Object.entries({ ...e, [key]: value }).filter(([, v]) => v !== undefined && v !== "")));
  const save = useBookMutation(async (_: void, b) =>
    source
      ? api.patch(`/books/${b}/import-sources/${source.code}`, { expected_version: source.version, name: name.trim(), config: config(), is_active: active })
      : api.post(`/books/${b}/import-sources`, { code: code.trim(), name: name.trim(), kind, config: config() }),
  );

  const direction = (dir: "in" | "out", title: string) => {
    const d = dirs[dir];
    const set = (patch: DirectionDefault) => setDirs({ ...dirs, [dir]: { ...d, ...patch } });
    return (
      <fieldset className="grid gap-3 rounded-field border border-line p-4">
        <legend className="px-1 text-sm font-semibold">{title}</legend>
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-ink-2">默认忽略（如个人转账）</span>
          <Switch label={`${title}默认忽略`} checked={!!d.ignore} onChange={(on) => set({ ignore: on ? "默认忽略" : undefined })} />
        </div>
        {!d.ignore && (
          <div className="grid grid-cols-3 gap-2 max-sm:grid-cols-1">
            <Select aria-label={`${title}默认类型`} value={d.type ?? ""} onChange={(e) => set({ type: e.target.value || undefined })}>
              <option value="">类型不设</option>
              {types
                .filter((t) => t.input_mode === "inputs" && t.is_active)
                .map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.name}
                  </option>
                ))}
            </Select>
            <Select aria-label={`${title}默认渠道`} value={d.channel ?? ""} onChange={(e) => set({ channel: e.target.value || undefined })}>
              <option value="">渠道不设</option>
              {channels.map((c) => (
                <option key={c.id} value={c.code}>
                  {c.name}
                </option>
              ))}
            </Select>
            <Select aria-label={`${title}默认分类`} value={d.category ?? ""} onChange={(e) => set({ category: e.target.value || undefined })}>
              <option value="">分类不设</option>
              {categories.map((a) => (
                <option key={a.id} value={a.code}>
                  {a.name}
                </option>
              ))}
            </Select>
          </div>
        )}
      </fieldset>
    );
  };

  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await save.mutateAsync();
          toast({ tone: "ok", text: `已保存来源 ${name.trim()}` });
          onDone();
        } catch {
          /* inline */
        }
      }}
    >
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        <Field label="名称" required>
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="微信账单" autoFocus={!source} />}
        </Field>
        <Field label="代码" hint={source ? "创建后不能改" : "小写字母、数字、下划线"} required>
          {(id, note) => <Input id={id} aria-describedby={note} value={code} onChange={(e) => setCode(e.target.value)} disabled={!!source} placeholder="wechat" className="num" />}
        </Field>
      </div>
      <Field label="文件格式">
        {(id) => (
          <Select
            id={id}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setExtra({});
              if (e.target.value === "redeem_page") setDirs((d) => ({ ...d, in: { type: "credit_purchase", ...d.in } }));
            }}
            disabled={!!source}
          >
            {Object.entries(KIND_NAMES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
                {k === "ai_extract" && aiStatus.data?.data.extract === false ? "（还没配置 AI 模型）" : ""}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {["generic_tabular", "card_shop_orders", "upstream_usage_log"].includes(kind) && <SourceMapping kind={kind} config={extra} onChange={setExtra} />}
      {kind === "upstream_usage_log" && (
        <Field label="站点" hint="记录属于哪个往来方，如 relay-b.example">
          {(id, note) => <Input id={id} aria-describedby={note} value={String(extra.counterparty ?? "")} onChange={(e) => setOption("counterparty", e.target.value)} />}
        </Field>
      )}
      {kind === "ai_extract" && (
        <>
          <Field label="告诉 AI 这是什么" hint="会和截图一起发给 AI，如：链动发卡网的买家订单列表，金额是实付">
            {(id, note) => <Textarea id={id} aria-describedby={note} rows={3} value={String(extra.hint ?? "")} onChange={(e) => setOption("hint", e.target.value)} />}
          </Field>
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-ink-2">金额是站内额度（如中转站的兑换记录），记为 UCR</span>
            <Switch label="金额是站内额度" checked={extra.commodity === "UCR"} onChange={(on) => setOption("commodity", on ? "UCR" : undefined)} />
          </div>
        </>
      )}
      {(kind === "redeem_page" || extra.commodity === "UCR") && (
        <Field label="额度换算" hint="1 额度折合多少元，用来算面值；你的口径是 $1 额度 = ¥1">
          {(id, note) => (
            <Input
              id={id}
              aria-describedby={note}
              inputMode="decimal"
              className="num"
              value={String(extra.credit_rate ?? "1")}
              onChange={(e) => setOption("credit_rate", e.target.value === "1" ? undefined : e.target.value)}
            />
          )}
        </Field>
      )}
      {direction("in", "收款")}
      {direction("out", "付款")}
      {source && (
        <div className="flex items-center justify-between gap-4 rounded-field bg-well px-4 py-3">
          <span className="font-medium">启用</span>
          <Switch label="启用来源" checked={active} onChange={setActive} />
        </div>
      )}
      {save.error && <p className="text-sm text-neg">{errorText(save.error, "保存失败：请稍后重试。")}</p>}
      <Button type="submit" variant="primary" size="lg" disabled={!name.trim() || (!source && !code.trim())} loading={save.isPending}>
        保存
      </Button>
    </form>
  );
}
