/** Business reference data: counterparties, channels, expense categories, currencies and rates. */
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { clsx } from "clsx";
import { MagnifyingGlass, Plus } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { useAccounts, useBook, useBookMutation, useBookQuery, useCommodities, useCounterparties, useDimensions } from "@/api/queries";
import type { Account, Counterparty, DimensionValue, FxRate } from "@/api/types";
import { Badge, Button, Card, Chip, DateInput, Empty, ErrorNote, Field, Input, Select, Sheet, Skeleton, Switch } from "@/components/ui";
import { useToast } from "@/components/toast";
import { bookDate } from "@/lib/format";

export const CATEGORIES: Record<string, string> = {
  upstream_site: "上游站点",
  ai_vendor: "AI 服务商",
  cloud_vendor: "云与网络",
  marketplace: "交易平台",
  payment_provider: "支付机构",
  marketing_vendor: "广告服务商",
  business_service: "企业服务",
  customer: "客户",
  other: "其他",
};

const DEFAULT_TYPES: Record<string, string> = { sale: "销售收入", credit_purchase: "额度采购", expense: "费用支出", purchase_refund: "采购退款", sale_refund: "销售退款" };

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.detail : fallback;
}

/** List card with the section's add button on top. */
function ListCard({ children, className }: { children: React.ReactNode; className?: string }) {
  return <Card className={clsx("px-6 py-2 max-sm:px-5", className)}>{children}</Card>;
}

function ListSkeleton() {
  return (
    <Card className="grid gap-5 p-5">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-8 w-full" />
      ))}
    </Card>
  );
}

/* ---------- 往来方 ---------- */

export function Counterparties() {
  const cps = useCounterparties();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState<Counterparty | "new" | null>(null);
  const all = cps.data ?? [];
  const counts = useMemo(() => all.reduce<Record<string, number>>((m, c) => ((m[c.category] = (m[c.category] ?? 0) + 1), m), {}), [all]);
  const needle = q.trim().toLowerCase();
  const list = all.filter((c) => (!category || c.category === category) && (!needle || c.name.toLowerCase().includes(needle) || c.domains.some((d) => d.includes(needle))));

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative block w-64 max-sm:w-full">
          <span className="sr-only">搜索往来方</span>
          <MagnifyingGlass size={16} className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索名称或域名"
            className="h-10 w-full rounded-full bg-card pr-4 pl-10 shadow-card placeholder:text-ink-3 focus:shadow-[0_0_0_3px_var(--lime-wash)] focus:outline-none"
          />
        </label>
        <Button variant="primary" icon={<Plus size={16} weight="bold" />} onClick={() => setEditing("new")} className="ml-auto max-sm:ml-0">
          新增往来方
        </Button>
      </div>
      <div className="-mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0">
        {Object.entries(CATEGORIES)
          .filter(([k]) => counts[k])
          .map(([k, v]) => (
            <Chip key={k} on={category === k} onClick={() => setCategory(category === k ? "" : k)}>
              {v} <span className="num font-normal">{counts[k]}</span>
            </Chip>
          ))}
      </div>
      {cps.error ? (
        <ErrorNote error={cps.error} onRetry={() => cps.refetch()} />
      ) : !cps.data ? (
        <ListSkeleton />
      ) : list.length === 0 ? (
        <Card>
          <Empty title={all.length ? "没有符合条件的往来方" : "还没有往来方"}>记账或导入时写到的站点、服务商会自动出现在这里。</Empty>
        </Card>
      ) : (
        <ListCard>
          <ul className="divide-y divide-line">
            {list.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setEditing(c)}
                  className="-mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-field px-2 py-3 text-left transition-colors duration-150 hover:bg-well"
                >
                  <span aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-well text-sm font-semibold text-ink-2">
                    {c.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={clsx("block truncate font-medium", !c.is_active && "text-ink-3 line-through")}>{c.name}</span>
                    <span className="block truncate text-sm text-ink-3">
                      {CATEGORIES[c.category] ?? c.category}
                      {c.defaults.type && ` · 默认${c.defaults.type.name}`}
                      {c.defaults.channel && ` · ${c.defaults.channel.name}`}
                    </span>
                  </span>
                  {!c.is_active && <Badge>已停用</Badge>}
                </button>
              </li>
            ))}
          </ul>
        </ListCard>
      )}
      <Sheet open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "新增往来方" : editing ? editing.name : ""} width={500}>
        {editing !== null && <CounterpartyForm key={editing === "new" ? "new" : editing.id} cp={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Sheet>
    </div>
  );
}

function aliasText(a: Counterparty["aliases"][number]): string {
  return typeof a === "string" ? a : (a.pattern ?? a.alias ?? "");
}

function CounterpartyForm({ cp, onDone }: { cp: Counterparty | null; onDone: () => void }) {
  const toast = useToast();
  const channels =
    useDimensions()
      .data?.find((d) => d.code === "channel")
      ?.values.filter((v) => v.is_active) ?? [];
  const [f, setF] = useState({
    name: cp?.name ?? "",
    category: cp?.category ?? "upstream_site",
    type: cp?.defaults.type?.code ?? "",
    channel: cp?.defaults.channel?.code ?? "",
    notes: cp?.notes ?? "",
    active: cp?.is_active ?? true,
  });
  const [alias, setAlias] = useState("");
  const save = useBookMutation(async (_: void, b) =>
    cp
      ? api.patch(`/books/${b}/counterparties/${cp.id}`, {
          expected_version: cp.version,
          name: f.name.trim(),
          category: f.category,
          default_type: f.type || null,
          default_channel: f.channel || null,
          notes: f.notes.trim() || null,
          is_active: f.active,
        })
      : api.post(`/books/${b}/counterparties`, {
          name: f.name.trim(),
          category: f.category,
          default_type: f.type || null,
          default_channel: f.channel || null,
          notes: f.notes.trim() || null,
          roles: f.category === "customer" ? ["customer"] : ["supplier"],
        }),
  );
  const addAlias = useBookMutation(async (_: void, b) => api.post(`/books/${b}/counterparties/${cp!.id}/aliases`, { pattern: alias.trim(), match_type: "exact" }));

  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await save.mutateAsync();
          toast({ tone: "ok", text: cp ? `已保存 ${f.name.trim()}` : `已新增往来方 ${f.name.trim()}` });
          onDone();
        } catch {
          /* inline */
        }
      }}
    >
      <Field label="名称" required>
        {(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="如 relay-b.example、OpenAI" autoFocus={!cp} />}
      </Field>
      <Field label="类别">
        {(id) => (
          <Select id={id} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>
            {Object.entries(CATEGORIES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
        <Field label="默认交易类型" hint="记账或导入没写类型时用">
          {(id, note) => (
            <Select id={id} aria-describedby={note} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>
              <option value="">不设</option>
              {Object.entries(DEFAULT_TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="默认渠道">
          {(id) => (
            <Select id={id} value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>
              <option value="">不设</option>
              {channels.map((c) => (
                <option key={c.id} value={c.code}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <Field label="备注">{(id) => <Input id={id} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />}</Field>
      {cp && (
        <>
          <div className="grid gap-2">
            <p className="text-sm font-medium text-ink-2">别名</p>
            <div className="flex flex-wrap gap-2">
              {cp.aliases.map((a, i) => (
                <Badge key={i} className="h-7 px-3 text-sm">
                  {aliasText(a)}
                </Badge>
              ))}
              {cp.aliases.length === 0 && <span className="text-sm text-ink-3">没有别名；账单里的其他写法可以加在这里</span>}
            </div>
            <div className="flex gap-2">
              <Input aria-label="新别名" value={alias} onChange={(e) => setAlias(e.target.value)} placeholder="账单上的其他写法" className="flex-1" />
              <Button
                disabled={!alias.trim()}
                loading={addAlias.isPending}
                onClick={async () => {
                  try {
                    await addAlias.mutateAsync();
                    toast({ tone: "ok", text: `已添加别名 ${alias.trim()}` });
                    setAlias("");
                  } catch (e) {
                    toast({ tone: "error", text: errorText(e, "添加别名失败：请稍后重试。") });
                  }
                }}
              >
                添加
              </Button>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4 rounded-field bg-well px-4 py-3">
            <span>
              <span className="block font-medium">启用</span>
              <span className="block text-sm text-ink-2">停用后不再出现在记账建议里，已有交易不受影响</span>
            </span>
            <Switch label="启用往来方" checked={f.active} onChange={(active) => setF({ ...f, active })} />
          </div>
          <Link to={`/transactions?counterparty=${encodeURIComponent(cp.name)}`} className="text-sm font-semibold text-pos hover:underline">
            查看与 {cp.name} 的交易
          </Link>
        </>
      )}
      {save.error && <p className="text-sm text-neg">{errorText(save.error, "保存失败：请稍后重试。")}</p>}
      <Button type="submit" variant="primary" size="lg" disabled={!f.name.trim()} loading={save.isPending}>
        保存
      </Button>
    </form>
  );
}

/* ---------- 渠道 ---------- */

export function Channels() {
  const dims = useDimensions();
  const toast = useToast();
  const channel = dims.data?.find((d) => d.code === "channel");
  const [editing, setEditing] = useState<DimensionValue | "new" | null>(null);
  const toggle = useBookMutation(async (v: DimensionValue, b) => api.patch(`/books/${b}/dimension-values/${v.id}`, { expected_version: v.version, is_active: !v.is_active }));

  return (
    <div className="grid gap-4">
      <div className="flex justify-end">
        <Button variant="primary" icon={<Plus size={16} weight="bold" />} onClick={() => setEditing("new")}>
          新增渠道
        </Button>
      </div>
      {dims.error ? (
        <ErrorNote error={dims.error} onRetry={() => dims.refetch()} />
      ) : !channel ? (
        <ListSkeleton />
      ) : (
        <ListCard>
          <ul className="divide-y divide-line">
            {channel.values.map((v) => (
              <li key={v.id} className="flex items-center gap-3 py-3">
                <button type="button" onClick={() => setEditing(v)} className="-mx-2 min-w-0 flex-1 rounded-field px-2 py-1 text-left transition-colors duration-150 hover:bg-well">
                  <span className={clsx("block font-medium", !v.is_active && "text-ink-3")}>{v.name}</span>
                  <span className="block truncate text-sm text-ink-3">
                    <span className="num">{v.code}</span>
                    {(v.aliases?.length ?? 0) > 0 && ` · 别名 ${v.aliases!.join("、")}`}
                  </span>
                </button>
                <Switch
                  label={`启用渠道 ${v.name}`}
                  checked={v.is_active}
                  onChange={async () => {
                    try {
                      await toggle.mutateAsync(v);
                    } catch (e) {
                      toast({ tone: "error", text: errorText(e, "修改失败：请稍后重试。") });
                    }
                  }}
                />
              </li>
            ))}
          </ul>
        </ListCard>
      )}
      <Sheet open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "新增渠道" : editing ? editing.name : ""} width={460}>
        {editing !== null && <ChannelForm key={editing === "new" ? "new" : editing.id} value={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Sheet>
    </div>
  );
}

function ChannelForm({ value, onDone }: { value: DimensionValue | null; onDone: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ code: value?.code ?? "", name: value?.name ?? "", aliases: (value?.aliases ?? []).join(", ") });
  const list = () =>
    f.aliases
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
  const save = useBookMutation(async (_: void, b) =>
    value
      ? api.patch(`/books/${b}/dimension-values/${value.id}`, { expected_version: value.version, name: f.name.trim(), aliases: list() })
      : api.post(`/books/${b}/dimension-types/channel/values`, { code: f.code.trim(), name: f.name.trim(), aliases: list() }),
  );
  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await save.mutateAsync();
          toast({ tone: "ok", text: `已保存渠道 ${f.name.trim()}` });
          onDone();
        } catch {
          /* inline */
        }
      }}
    >
      <Field label="名称" required>
        {(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="如 闲鱼" autoFocus />}
      </Field>
      <Field label="代码" hint={value ? "代码创建后不能改" : "小写字母、数字或下划线，如 xianyu"} required>
        {(id, note) => <Input id={id} aria-describedby={note} value={f.code} disabled={!!value} onChange={(e) => setF({ ...f, code: e.target.value })} className="num" />}
      </Field>
      <Field label="别名" hint="用逗号分隔；录入和导入时与名称同样能识别">
        {(id, note) => <Input id={id} aria-describedby={note} value={f.aliases} onChange={(e) => setF({ ...f, aliases: e.target.value })} />}
      </Field>
      {save.error && <p className="text-sm text-neg">{errorText(save.error, "保存失败：请稍后重试。")}</p>}
      <Button type="submit" variant="primary" size="lg" disabled={!f.name.trim() || !f.code.trim()} loading={save.isPending}>
        保存
      </Button>
    </form>
  );
}

/* ---------- 收支分类 ---------- */

const SYSTEM_ROLES = new Set(["fx_gain_loss", "rounding", "interest", "current_year_profit", "trading"]);

export function Categories() {
  const accounts = useAccounts();
  const toast = useToast();
  const [adding, setAdding] = useState<Account | null>(null);
  const list = (accounts.data ?? []).filter((a) => a.classification === "expense");
  const groups = list.filter((a) => a.is_group);
  const toggle = useBookMutation(async (a: Account, b) => api.patch(`/books/${b}/accounts/${a.code}`, { expected_version: a.version, is_active: !a.is_active }));

  if (accounts.error) return <ErrorNote error={accounts.error} onRetry={() => accounts.refetch()} />;
  if (!accounts.data) return <ListSkeleton />;
  return (
    <div className="grid gap-5">
      {groups.map((g) => {
        const children = list.filter((a) => a.parent_code === g.code);
        return (
          <section key={g.id} aria-labelledby={`grp-${g.code}`}>
            <header className="mb-2 flex items-center justify-between pl-6 max-sm:pl-5">
              <h3 id={`grp-${g.code}`} className="text-sm font-semibold text-ink-2">
                {g.name}
              </h3>
              <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={() => setAdding(g)}>
                新增
              </Button>
            </header>
            <ListCard>
              <ul className="divide-y divide-line">
                {children.map((a) => (
                  <li key={a.id} className="flex items-center gap-3 py-3">
                    <span className="min-w-0 flex-1">
                      <span className={clsx("block font-medium", !a.is_active && "text-ink-3")}>{a.name}</span>
                      <span className="block truncate text-sm text-ink-3">
                        <span className="num">{a.code}</span>
                        {a.description && ` · ${a.description}`}
                        {SYSTEM_ROLES.has(a.role ?? "") && " · 系统使用"}
                      </span>
                    </span>
                    {!a.is_system && !SYSTEM_ROLES.has(a.role ?? "") && (
                      <Switch
                        label={`启用分类 ${a.name}`}
                        checked={a.is_active}
                        onChange={async () => {
                          try {
                            await toggle.mutateAsync(a);
                          } catch (e) {
                            toast({ tone: "error", text: errorText(e, "修改失败：请稍后重试。") });
                          }
                        }}
                      />
                    )}
                  </li>
                ))}
              </ul>
            </ListCard>
          </section>
        );
      })}
      <Sheet open={!!adding} onClose={() => setAdding(null)} title={adding ? `在「${adding.name}」下新增` : ""} width={440}>
        {adding && <CategoryForm parent={adding} siblings={list.filter((a) => a.parent_code === adding.code)} onDone={() => setAdding(null)} />}
      </Sheet>
    </div>
  );
}

function CategoryForm({ parent, siblings, onDone }: { parent: Account; siblings: Account[]; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const create = useBookMutation(async (_: void, b) => {
    const used = siblings.map((a) => Number(a.code.split(".")[1] ?? 0)).filter((n) => n < 90);
    const next = String((used.length ? Math.max(...used) : 0) + 1).padStart(2, "0");
    return api.post(`/books/${b}/accounts`, { code: `${parent.code}.${next}`, name: name.trim() });
  });
  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await create.mutateAsync();
          toast({ tone: "ok", text: `已新增分类 ${name.trim()}` });
          onDone();
        } catch {
          /* inline */
        }
      }}
    >
      <Field label="名称" hint="名词短语，不超过 8 个字，不写品牌或渠道" error={create.error ? errorText(create.error, "新增失败：请稍后重试。") : undefined}>
        {(id, note) => <Input id={id} aria-describedby={note} value={name} onChange={(e) => setName(e.target.value)} placeholder="如 域名与证书" autoFocus />}
      </Field>
      <Button type="submit" variant="primary" size="lg" disabled={!name.trim()} loading={create.isPending}>
        新增
      </Button>
    </form>
  );
}

/* ---------- 币种与汇率 ---------- */

const KIND: Record<string, string> = { fiat: "法币", credit: "额度", other: "其他" };

export function Currencies() {
  const toast = useToast();
  const commodities = useCommodities();
  const base = useBook().data?.base_commodity ?? "CNY";
  const rates = useBookQuery<FxRate[]>("/fx-rates", { limit: 20 });
  const [r, setR] = useState({ base: "USD", rate: "", rate_date: bookDate() });
  const [adding, setAdding] = useState(false);
  const addR = useBookMutation(async (_: void, b) => api.post(`/books/${b}/fx-rates`, { base: r.base, quote: base, rate: r.rate.trim(), rate_date: r.rate_date }));
  const list = commodities.data ?? [];

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <section aria-labelledby="cur-title" className="grid content-start gap-2">
        <header className="flex items-center justify-between pl-6 max-sm:pl-5">
          <h3 id="cur-title" className="text-sm font-semibold text-ink-2">
            币种
          </h3>
          <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={() => setAdding(true)}>
            新增
          </Button>
        </header>
        {!commodities.data ? (
          <ListSkeleton />
        ) : (
          <ListCard>
            <ul className="divide-y divide-line">
              {list.map((x) => (
                <li key={x.code} className="flex items-center gap-3 py-3">
                  <span className="num w-12 font-semibold">{x.code}</span>
                  <span className="flex-1">{x.name}</span>
                  {x.code === base && <Badge tone="pos">本位币</Badge>}
                  <span className="text-sm text-ink-3">
                    {KIND[x.kind] ?? x.kind} · {x.scale} 位小数
                  </span>
                </li>
              ))}
            </ul>
          </ListCard>
        )}
      </section>
      <section aria-labelledby="rate-title" className="grid content-start gap-2">
        <h3 id="rate-title" className="flex min-h-8 items-center px-6 text-sm font-semibold text-ink-2 max-sm:px-5">
          汇率（对 {base}）
        </h3>
        <Card className="p-5 max-sm:p-4">
          <form
            className="grid grid-cols-[96px_minmax(0,1fr)] gap-3 sm:grid-cols-[96px_minmax(0,1fr)_160px_auto]"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await addR.mutateAsync();
                toast({ tone: "ok", text: `已录入 ${r.rate_date} 的 ${r.base} 汇率` });
                setR({ ...r, rate: "" });
              } catch (err) {
                toast({ tone: "error", text: errorText(err, "录入失败：请检查汇率后重试。") });
              }
            }}
          >
            <Select aria-label="币种" value={r.base} onChange={(e) => setR({ ...r, base: e.target.value })}>
              {list
                .filter((x) => x.code !== base && x.kind === "fiat")
                .map((x) => (
                  <option key={x.code} value={x.code}>
                    {x.code}
                  </option>
                ))}
            </Select>
            <Input aria-label="汇率" inputMode="decimal" placeholder={`1 ${r.base} = ? ${base}`} value={r.rate} onChange={(e) => setR({ ...r, rate: e.target.value })} className="num" />
            <DateInput aria-label="日期" value={r.rate_date} onChange={(e) => setR({ ...r, rate_date: e.target.value })} className="max-sm:col-span-2" />
            <Button type="submit" disabled={!r.rate.trim()} loading={addR.isPending} className="max-sm:col-span-2">
              录入
            </Button>
          </form>
          <ul className="mt-4 divide-y divide-line">
            {(rates.data?.data ?? []).map((x) => (
              <li key={x.id} className="num flex items-center justify-between gap-3 py-2.5 text-sm">
                <span>
                  {x.rate_date} · 1 {x.base} = {Number(x.rate).toFixed(4)} {x.quote}
                </span>
                <span className="text-ink-3">{x.rate_type === "actual" ? "实际" : "参考"}</span>
              </li>
            ))}
            {rates.data && rates.data.data.length === 0 && <li className="py-4 text-center text-sm text-ink-3">还没有汇率；法币会自动取参考汇率</li>}
          </ul>
        </Card>
      </section>
      <Sheet open={adding} onClose={() => setAdding(false)} title="新增币种" width={440}>
        {adding && <CommodityForm onDone={() => setAdding(false)} />}
      </Sheet>
    </div>
  );
}

function CommodityForm({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const [c, setC] = useState({ code: "", name: "", kind: "fiat", scale: "2", symbol: "" });
  const add = useBookMutation(async (_: void, b) =>
    api.post(`/books/${b}/commodities`, { code: c.code.trim().toUpperCase(), name: c.name.trim(), kind: c.kind, scale: Number(c.scale), symbol: c.symbol.trim() || null }),
  );
  return (
    <form
      className="grid gap-5"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await add.mutateAsync();
          toast({ tone: "ok", text: `已新增币种 ${c.code.toUpperCase()}` });
          onDone();
        } catch {
          /* inline */
        }
      }}
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="代码" required>
          {(id) => <Input id={id} value={c.code} onChange={(e) => setC({ ...c, code: e.target.value })} placeholder="JPY" className="num uppercase" autoFocus />}
        </Field>
        <Field label="名称" required>
          {(id) => <Input id={id} value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} placeholder="日元" />}
        </Field>
        <Field label="类别">
          {(id) => (
            <Select id={id} value={c.kind} onChange={(e) => setC({ ...c, kind: e.target.value })}>
              <option value="fiat">法币（自动取参考汇率）</option>
              <option value="credit">额度</option>
              <option value="other">其他</option>
            </Select>
          )}
        </Field>
        <Field label="小数位">{(id) => <Input id={id} inputMode="numeric" value={c.scale} onChange={(e) => setC({ ...c, scale: e.target.value })} className="num" />}</Field>
        <Field label="符号" hint="可选，如 ¥">
          {(id, note) => <Input id={id} aria-describedby={note} value={c.symbol} onChange={(e) => setC({ ...c, symbol: e.target.value })} />}
        </Field>
      </div>
      {add.error && <p className="text-sm text-neg">{errorText(add.error, "新增失败：请稍后重试。")}</p>}
      <Button type="submit" variant="primary" size="lg" disabled={!c.code.trim() || !c.name.trim()} loading={add.isPending}>
        新增
      </Button>
    </form>
  );
}
