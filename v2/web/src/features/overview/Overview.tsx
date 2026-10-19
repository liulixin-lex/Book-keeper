/**
 * 概览: this period's profit with its daily shape, the balance per currency, where the money came from (channels)
 * and went (upstream sites), the latest records and anything waiting. Every figure links to its transactions.
 */
import { Link, useNavigate, useSearchParams } from "react-router";
import { clsx } from "clsx";
import { ArrowDownRight, ArrowUpRight, CaretRight, CheckCircle } from "@phosphor-icons/react";
import { useAccounts, useBook, useBookQuery, useImportBacklog, useWorkSummary } from "@/api/queries";
import type { Operations, Summary, Transaction, WorkSummary } from "@/api/types";
import { BarList, FlowChart, Legend, type FlowPoint } from "@/components/charts";
import { RollingText } from "@/components/Figure";
import { CurrencyMark } from "@/components/money";
import { Card, CardHeader, Empty, ErrorNote, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { TxnRow } from "@/features/transactions/TxnRow";
import { bookDate, formatMoney, shortDate } from "@/lib/format";
import { comparedWith, granularity, isPeriod, PERIODS, previousRange, rangeOf, type PeriodKey, type Range } from "@/lib/period";

export function usePeriod(): [PeriodKey, (p: PeriodKey) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get("p");
  const period: PeriodKey = isPeriod(raw) ? raw : "month";
  return [
    period,
    (p) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (p === "month") next.delete("p");
          else next.set("p", p);
          return next;
        },
        { replace: true },
      ),
  ];
}

export function PeriodPicker({ value, onChange }: { value: PeriodKey; onChange: (p: PeriodKey) => void }) {
  return <Segmented label="统计期间" value={value} onChange={onChange} options={PERIODS} />;
}

/** Transactions behind a span (and optional filters), as a link into 交易. */
export function txnLink(r: Range, extra: Record<string, string | undefined> = {}): string {
  const q = new URLSearchParams({ from: r.from, to: r.to });
  for (const [k, v] of Object.entries(extra)) if (v) q.set(k, v);
  return `/transactions?${q}`;
}

export function toPoints(ops: Operations | undefined): FlowPoint[] {
  return (ops?.rows ?? []).map((r) => ({
    period: r.period,
    revenue: r.values.sales.minor + r.values.other_income.minor,
    cost: r.values.fees.minor + r.values.credit_cost.minor + r.values.other_cost.minor + r.values.expenses.minor,
    profit: r.values.profit.minor,
  }));
}

/** Where a chart bar leads: that day, week or month. */
export function spanOf(period: string, g: "day" | "week" | "month", within: Range): Range {
  if (g === "day") return { from: period, to: period };
  const start = new Date(`${period}T00:00:00Z`);
  const end = new Date(start);
  if (g === "week") end.setUTCDate(end.getUTCDate() + 6);
  else end.setUTCMonth(end.getUTCMonth() + 1, 0);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(start) < within.from ? within.from : iso(start), to: iso(end) > within.to ? within.to : iso(end) };
}

export default function Overview() {
  const today = bookDate();
  const [period, setPeriod] = usePeriod();
  const range = rangeOf(period, today);
  const prev = previousRange(period, today);
  const g = granularity(range);

  const summary = useBookQuery<Summary>("/reports/summary", { date_from: range.from, date_to: range.to }, { keep: true });
  const before = useBookQuery<Summary>("/reports/summary", { date_from: prev.from, date_to: prev.to }, { keep: true });
  const ops = useBookQuery<Operations>("/reports/operations", { date_from: range.from, date_to: range.to, period: g }, { keep: true });

  return (
    <>
      <PageHeader title="概览" badge={<WaitingPill />}>
        <PeriodPicker value={period} onChange={setPeriod} />
      </PageHeader>
      <div className="grid gap-5 lg:grid-cols-12">
        <ProfitCard
          period={period}
          range={range}
          summary={summary.data?.data}
          before={before.data?.data}
          ops={ops.data?.data}
          g={g}
          error={summary.error ?? ops.error}
          retry={() => (summary.refetch(), ops.refetch())}
        />
        <BalancesCard summary={summary.data?.data} asOf={range.to} />
        <ChannelsCard summary={summary.data?.data} range={range} period={period} />
        <SitesCard summary={summary.data?.data} range={range} period={period} />
        <RecentCard />
        <WaitingCard />
      </div>
    </>
  );
}

function ProfitCard({
  period,
  range,
  summary,
  before,
  ops,
  g,
  error,
  retry,
}: {
  period: PeriodKey;
  range: Range;
  summary?: Summary;
  before?: Summary;
  ops?: Operations;
  g: "day" | "week" | "month";
  error: unknown;
  retry: () => void;
}) {
  const navigate = useNavigate();
  const label = PERIODS.find((p) => p.value === period)!.label;
  const profit = summary?.profit.net_profit;
  const t = ops?.totals;
  return (
    <Card className="p-6 lg:col-span-7 max-sm:p-5" aria-labelledby="profit-title">
      <CardHeader id="profit-title" title={`${label}利润`} />
      {error ? (
        <ErrorNote error={error} onRetry={retry} className="mt-4" />
      ) : !profit || !t ? (
        <div className="mt-2 grid gap-3">
          <Skeleton className="h-12 w-56" />
          <Skeleton className="h-4 w-40" />
          <Skeleton className="mt-6 h-[200px] w-full" />
        </div>
      ) : (
        <>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
            <div>
              <RollingText text={formatMoney(profit)} arrive className={clsx("text-3xl", profit.minor < 0 && "text-neg")} />
              <Delta now={profit.minor} then={before?.profit.net_profit.minor} label={comparedWith(period)} />
            </div>
            <dl className="flex gap-6 max-sm:w-full max-sm:justify-between">
              <Stat label="收入" value={t.sales.minor + t.other_income.minor} commodity={profit.commodity} />
              <Stat label="成本" value={t.credit_cost.minor + t.other_cost.minor} commodity={profit.commodity} />
              <Stat label="手续费" value={t.fees.minor} commodity={profit.commodity} />
              {t.expenses.minor !== 0 && <Stat label="费用" value={t.expenses.minor} commodity={profit.commodity} />}
            </dl>
          </div>
          <div className="mt-7">
            <FlowChart
              points={toPoints(ops)}
              commodity={profit.commodity}
              granularity={g}
              label={`${label}${g === "day" ? "每日" : g === "week" ? "每周" : "每月"}收入、成本与利润`}
              onPick={(p) => navigate(txnLink(spanOf(p.period, g, range)))}
            />
            <div className="mt-3 flex items-center justify-between gap-3">
              <Legend
                items={[
                  { color: "var(--series-in)", label: "收入" },
                  { color: "var(--series-cost)", label: "成本与费用" },
                  { color: "var(--series-profit)", label: "利润", line: true },
                ]}
              />
              <Link to={`/stats${period === "month" ? "" : `?p=${period}`}`} className="flex shrink-0 items-center gap-0.5 text-sm font-medium text-ink-2 hover:text-ink">
                统计
                <CaretRight size={13} />
              </Link>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

function Delta({ now, then, label }: { now: number; then: number | undefined; label: string }) {
  if (then === undefined) return <p className="mt-1 h-5" />;
  if (then === 0) return <p className="mt-1 text-sm text-ink-3">{label}没有利润记录</p>;
  const change = (now - then) / Math.abs(then);
  const up = change >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <p className="mt-1 flex items-center gap-1 text-sm">
      <span className={clsx("num flex items-center gap-0.5 font-semibold", up ? "text-pos" : "text-neg")}>
        <Icon size={14} weight="bold" />
        {Math.abs(change * 100).toFixed(1)}%
      </span>
      <span className="text-ink-2">较{label}</span>
    </p>
  );
}

function Stat({ label, value, commodity }: { label: string; value: number; commodity: string }) {
  return (
    <div>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="mt-0.5">
        <RollingText text={formatMoney({ minor: value, commodity })} className="text-md" />
      </dd>
    </div>
  );
}

function BalancesCard({ summary, asOf }: { summary?: Summary; asOf: string }) {
  const base = useBook().data?.base_commodity ?? "CNY";
  const funds = summary?.funds ?? [];
  const total = funds.reduce((s, f) => s + f.base.minor, 0);
  return (
    <Card className="p-6 lg:col-span-5 max-sm:p-5" aria-labelledby="funds-title">
      <CardHeader id="funds-title" title="余额" action={<span className="text-sm text-ink-3">截至 {shortDate(asOf)}</span>} />
      {!summary ? (
        <div className="mt-3 grid gap-4">
          <Skeleton className="h-10 w-44" />
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      ) : (
        <>
          <div className="mt-2">
            <RollingText text={formatMoney({ minor: total, commodity: base })} className="text-2xl" />
            <p className="mt-0.5 text-sm text-ink-3">各币种按账面汇率折合 {base}</p>
          </div>
          <ul className="mt-4 grid gap-0.5">
            {funds.map((f) => (
              <li key={f.commodity}>
                <Link to={`/transactions?commodity=${f.commodity}`} className="-mx-3 flex items-center gap-3.5 rounded-field px-3 py-2 transition-colors duration-150 hover:bg-well">
                  <CurrencyMark commodity={f.commodity} />
                  <span className="flex-1 font-medium">{f.commodity}</span>
                  <span className="flex flex-col items-end gap-0.5">
                    <RollingText text={formatMoney(f.amount)} className="text-base" />
                    {f.commodity !== base && <RollingText quiet text={formatMoney(f.base)} className="text-sm text-ink-3" />}
                  </span>
                </Link>
              </li>
            ))}
            {funds.length === 0 && <li className="py-6 text-center text-sm text-ink-3">还没有资金记录</li>}
          </ul>
        </>
      )}
    </Card>
  );
}

function ChannelsCard({ summary, range, period }: { summary?: Summary; range: Range; period: PeriodKey }) {
  const items = (summary?.top_channels ?? []).map((c) => ({
    key: c.channel.code,
    label: c.channel.name,
    value: c.net_sales,
    note: `${c.orders} 笔`,
    to: txnLink(range, { type: "sale", channel: c.channel.code }),
  }));
  return (
    <Card className="p-6 lg:col-span-7 max-sm:p-5" aria-labelledby="ch-title">
      <CardHeader id="ch-title" title="渠道销售" action={<MoreLink to={`/stats?tab=channels${period === "month" ? "" : `&p=${period}`}`} />} />
      <div className="mt-3">{!summary ? <ListSkeleton /> : items.length ? <BarList items={items} /> : <p className="py-8 text-center text-sm text-ink-3">这段时间没有销售</p>}</div>
    </Card>
  );
}

function SitesCard({ summary, range, period }: { summary?: Summary; range: Range; period: PeriodKey }) {
  const items = (summary?.top_sites ?? []).map((s) => ({
    key: s.site.id,
    label: s.site.name,
    value: s.total_paid,
    note: `${s.purchases} 次`,
    to: txnLink(range, { type: "credit_purchase", counterparty: s.site.name }),
  }));
  return (
    <Card className="p-6 lg:col-span-5 max-sm:p-5" aria-labelledby="site-title">
      <CardHeader id="site-title" title="上游采购" action={<MoreLink to={`/stats?tab=sites${period === "month" ? "" : `&p=${period}`}`} />} />
      <div className="mt-3">{!summary ? <ListSkeleton /> : items.length ? <BarList items={items} tone="cost" /> : <p className="py-8 text-center text-sm text-ink-3">这段时间没有采购额度</p>}</div>
    </Card>
  );
}

function RecentCard() {
  const navigate = useNavigate();
  const recent = useBookQuery<Transaction[]>("/transactions", { limit: 6 });
  const list = recent.data?.data ?? [];
  return (
    <Card className="p-6 lg:col-span-7 max-sm:p-5" aria-labelledby="recent-title">
      <CardHeader id="recent-title" title="最近记录" action={<MoreLink to="/transactions" label="全部交易" />} />
      <div className="mt-2">
        {recent.error ? (
          <ErrorNote error={recent.error} onRetry={() => recent.refetch()} />
        ) : !recent.data ? (
          <ListSkeleton rows={5} />
        ) : list.length === 0 ? (
          <Empty title="还没有记录">按 N 或点“记一笔”，记下第一笔销售或采购。</Empty>
        ) : (
          <ul>
            {list.map((t) => (
              <TxnRow key={t.id} t={t} showDate onOpen={() => navigate(`/transactions?tx=${t.number}`)} />
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

const WAITING: { key: string; to: string; text: (w: WorkSummary["summary"][string]) => string }[] = [
  { key: "pending_matches", to: "/imports", text: (w) => `${w.count} 个匹配待确认` },
  { key: "estimated", to: "/transactions?estimate=1", text: (w) => `${w.count} 笔手续费是估算` },
  { key: "suspense", to: "/transactions?account=suspense", text: (w) => `待核对款项 ${w.balance ? formatMoney(w.balance) : ""}` },
  { key: "failed_checks", to: "/settings/data", text: (w) => `${w.count} 项数据检查未通过` },
];

/** What is waiting for the owner, in the order it should be handled; each item knows where it is fixed. */
function useWaiting() {
  const work = useWorkSummary();
  const accounts = useAccounts().data;
  const backlog = useImportBacklog();
  const suspense = accounts?.find((a) => a.role === "suspense")?.code;
  const fromWork = WAITING.filter(({ key }) => {
    const w = work.data?.summary[key];
    if (!w) return false;
    return key === "suspense" ? (w.balance?.minor ?? 0) !== 0 : w.count > 0;
  }).map((i) => ({
    key: i.key,
    to: i.key === "suspense" && suspense ? `/transactions?account=${suspense}` : i.to,
    text: i.text(work.data!.summary[i.key]!),
    count: i.key === "suspense" ? 1 : (work.data?.summary[i.key]?.count ?? 0),
  }));
  const items = [
    ...(backlog.count ? [{ key: "imports", to: backlog.first ? `/imports/${backlog.first}` : "/imports", text: `${backlog.count} 条导入记录待入账`, count: backlog.count }] : []),
    ...fromWork,
  ];
  return { work, items, count: items.reduce((n, i) => n + i.count, 0) };
}

/** Beside the page title: how much is waiting, one click from where it is handled. */
function WaitingPill() {
  const { items, count } = useWaiting();
  if (!items.length) return null;
  return (
    <Link to={items[0]!.to} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-warn-wash px-3.5 text-sm font-semibold text-warn-text transition-colors duration-150 hover:bg-warn/25">
      <span aria-hidden className="size-1.5 rounded-full bg-warn" />
      <span className="num">{count}</span> 项待处理
      <CaretRight size={12} weight="bold" />
    </Link>
  );
}

function WaitingCard() {
  const { work, items } = useWaiting();
  return (
    <Card className="p-6 lg:col-span-5 max-sm:p-5" aria-labelledby="wait-title">
      <CardHeader id="wait-title" title="待处理" />
      <div className="mt-2">
        {!work.data ? (
          <ListSkeleton rows={3} />
        ) : items.length === 0 ? (
          <Empty icon={<CheckCircle size={24} weight="fill" className="text-pos" />} title="都处理好了" className="py-8">
            导入的记录都已入账，手续费没有估算。
          </Empty>
        ) : (
          <ul className="grid gap-0.5">
            {items.map(({ key, to, text }) => (
              <li key={key}>
                <Link to={to} className="-mx-3 flex items-center gap-3 rounded-field px-3 py-3 transition-colors duration-150 hover:bg-well">
                  <span aria-hidden className="size-2 shrink-0 rounded-full bg-warn" />
                  <span className="flex-1">{text}</span>
                  <CaretRight size={14} className="text-ink-3" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function MoreLink({ to, label = "查看全部" }: { to: string; label?: string }) {
  return (
    <Link to={to} className="flex shrink-0 items-center gap-0.5 text-sm font-medium text-ink-2 hover:text-ink">
      {label}
      <CaretRight size={13} />
    </Link>
  );
}

function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="grid gap-4 py-2" role="status" aria-label="加载中">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-10 rounded-full" />
          <div className="grid flex-1 gap-1.5">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
  );
}
