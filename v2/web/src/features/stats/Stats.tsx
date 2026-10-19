/**
 * 统计: one question per tab — how profit moved (趋势), which channels sell (渠道), what upstream credit costs (上游),
 * where the money goes (支出) and what the channels keep (手续费). Every row opens its transactions.
 */
import { useNavigate, useSearchParams } from "react-router";
import { clsx } from "clsx";
import { CaretRight } from "@phosphor-icons/react";
import { useBook, useBookQuery } from "@/api/queries";
import type { CreditRow, Drilldown, FeeRow, IncomeLine, Operations, SalesRow } from "@/api/types";
import { BarList, FlowChart, Legend } from "@/components/charts";
import { RollingText } from "@/components/Figure";
import { Money } from "@/components/money";
import { Card, ErrorNote, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { PeriodPicker, spanOf, toPoints, txnLink, usePeriod } from "@/features/overview/Overview";
import { bookDate, formatMoney, percent, shortDate, type Money as MoneyValue } from "@/lib/format";
import { granularity, PERIODS, rangeOf, type Range } from "@/lib/period";

type Tab = "trend" | "channels" | "sites" | "spend" | "fees";

const TABS: { value: Tab; label: string }[] = [
  { value: "trend", label: "趋势" },
  { value: "channels", label: "渠道" },
  { value: "sites", label: "上游" },
  { value: "spend", label: "支出" },
  { value: "fees", label: "手续费" },
];

/** A report row's drilldown → the 交易 URL. */
function drill(d: Drilldown | undefined): string | null {
  const t = d?.transactions;
  if (!t) return null;
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(t)) {
    if (k === "date_from") q.set("from", v);
    else if (k === "date_to") q.set("to", v);
    else if (k === "status") continue;
    else q.set(k, v);
  }
  return `/transactions?${q}`;
}

export default function Stats() {
  const today = bookDate();
  const [period, setPeriod] = usePeriod();
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.value === params.get("tab"))?.value ?? "trend") as Tab;
  const range = rangeOf(period, today);
  const label = PERIODS.find((p) => p.value === period)!.label;

  return (
    <>
      <PageHeader title="统计">
        <PeriodPicker value={period} onChange={setPeriod} />
      </PageHeader>
      <div className="-mx-4 mb-5 overflow-x-auto px-4 sm:mx-0 sm:px-0">
        <Segmented
          label="统计内容"
          value={tab}
          onChange={(t) =>
            setParams(
              (prev) => {
                const next = new URLSearchParams(prev);
                if (t === "trend") next.delete("tab");
                else next.set("tab", t);
                return next;
              },
              { replace: true },
            )
          }
          options={TABS}
        />
      </div>
      {tab === "trend" && <Trend range={range} label={label} />}
      {tab === "channels" && <Channels range={range} />}
      {tab === "sites" && <Sites range={range} />}
      {tab === "spend" && <Spend range={range} />}
      {tab === "fees" && <Fees range={range} />}
    </>
  );
}

function Headline({ items }: { items: { label: string; value: MoneyValue | string; strong?: boolean }[] }) {
  return (
    <dl className="flex flex-wrap gap-x-10 gap-y-4">
      {items.map((i, n) => (
        <div key={i.label}>
          <dt className="text-sm text-ink-2">{i.label}</dt>
          <dd className="mt-0.5">
            {typeof i.value === "string" ? (
              <span className={clsx("figure", n === 0 ? "text-2xl" : "text-lg")}>{i.value}</span>
            ) : (
              <RollingText text={formatMoney(i.value)} className={n === 0 ? "text-2xl" : "text-lg"} />
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Loading() {
  return (
    <Card className="grid gap-5 p-6">
      <div className="flex gap-10">
        <Skeleton className="h-12 w-40" />
        <Skeleton className="h-12 w-32" />
      </div>
      <Skeleton className="h-56 w-full" />
    </Card>
  );
}

/* ---------- 趋势 ---------- */

function Trend({ range, label }: { range: Range; label: string }) {
  const navigate = useNavigate();
  const g = granularity(range);
  const ops = useBookQuery<Operations>("/reports/operations", { date_from: range.from, date_to: range.to, period: g }, { keep: true });
  const o = ops.data?.data;
  if (ops.error) return <ErrorNote error={ops.error} onRetry={() => ops.refetch()} />;
  if (!o) return <Loading />;
  const t = o.totals;
  const revenue = { minor: t.sales.minor + t.other_income.minor, commodity: t.sales.commodity };
  const margin = revenue.minor ? t.profit.minor / revenue.minor : null;
  const rows = [...o.rows].reverse();
  return (
    <div className="grid gap-5">
      <Card className="p-6 max-sm:p-5">
        <Headline
          items={[
            { label: `${label}利润`, value: t.profit },
            { label: "收入", value: revenue },
            { label: "利润率", value: margin === null ? "—" : percent(margin) },
          ]}
        />
        <div className="mt-7">
          <FlowChart
            points={toPoints(o)}
            commodity={t.profit.commodity}
            granularity={g}
            height={240}
            label={`${label}收入、成本与利润`}
            onPick={(p) => navigate(txnLink(spanOf(p.period, g, range)))}
          />
          <div className="mt-3">
            <Legend
              items={[
                { color: "var(--series-in)", label: "收入" },
                { color: "var(--series-cost)", label: "成本与费用" },
                { color: "var(--series-profit)", label: "利润", line: true },
              ]}
            />
          </div>
        </div>
      </Card>
      <Card className="px-6 py-3 max-sm:px-5">
        <Table
          caption={`${label}${g === "day" ? "每日" : g === "week" ? "每周" : "每月"}经营明细`}
          head={[g === "day" ? "日期" : g === "week" ? "周" : "月份", "收入", "额度成本", "其他成本", "手续费", "费用", "利润"]}
          rows={rows.map((r) => ({
            key: r.period,
            to: txnLink(spanOf(r.period, g, range)),
            cells: [
              g === "month" ? `${Number(r.period.slice(5, 7))}月` : g === "week" ? `${shortDate(r.period)}起` : shortDate(r.period),
              <Money key="s" value={{ ...r.values.sales, minor: r.values.sales.minor + r.values.other_income.minor, display: undefined }} />,
              <Money key="c" value={r.values.credit_cost} className="text-ink-2" />,
              <Money key="o" value={r.values.other_cost} className="text-ink-2" />,
              <Money key="f" value={r.values.fees} className="text-ink-2" />,
              <Money key="e" value={r.values.expenses} className="text-ink-2" />,
              <Money key="p" value={r.values.profit} className={clsx("font-semibold", r.values.profit.minor < 0 && "text-neg")} />,
            ],
          }))}
        />
      </Card>
    </div>
  );
}

/* ---------- 渠道 ---------- */

/** The row's name with a thin bar for its share of the column total. */
function Share({ name, part, total, tone = "in" }: { name: string; part: number; total: number; tone?: "in" | "cost" }) {
  const share = total ? Math.max(0, Math.min(1, part / total)) : 0;
  return (
    <span className="block min-w-0">
      <span className="block truncate">{name}</span>
      <span aria-hidden className="mt-1.5 block h-1 w-28 overflow-hidden rounded-full bg-well">
        <span className="block h-full rounded-full" style={{ width: `${share * 100}%`, background: tone === "in" ? "var(--series-in)" : "var(--series-cost)" }} />
      </span>
    </span>
  );
}

function Channels({ range }: { range: Range }) {
  const report = useBookQuery<{ rows: SalesRow[]; totals: Record<string, MoneyValue | number | string> }>("/reports/sales", { date_from: range.from, date_to: range.to }, { keep: true });
  const d = report.data?.data;
  if (report.error) return <ErrorNote error={report.error} onRetry={() => report.refetch()} />;
  if (!d) return <Loading />;
  const rows = [...d.rows].sort((a, b) => b.net_sales.minor - a.net_sales.minor);
  const totals = d.totals as { net_sales: MoneyValue; fees: MoneyValue; net_received: MoneyValue; orders: number; fee_rate: string | null };
  return (
    <Card className="px-6 pt-6 pb-3 max-sm:px-5 max-sm:pt-5">
      <Headline
        items={[
          { label: "销售额", value: totals.net_sales },
          { label: "到账", value: totals.net_received },
          { label: "平均扣费率", value: totals.fee_rate ? percent(Number(totals.fee_rate), 2) : "—" },
        ]}
      />
      <div className="mt-6">
        <Table
          caption="各渠道销售"
          head={["渠道", "订单", "销售额", "销售手续费", "费率", "到账", "客单价"]}
          rows={rows.map((r) => ({
            key: r.channel.code,
            to: drill(r.drilldown),
            cells: [
              <Share key="n" name={r.channel.name} part={r.net_sales.minor} total={totals.net_sales.minor} />,
              <span key="o" className="num">
                {r.orders}
              </span>,
              <Money key="s" value={r.net_sales} className="font-semibold" />,
              <Money key="f" value={r.fees} className="text-ink-2" />,
              <span key="r" className="num text-ink-2">
                {r.fee_rate ? percent(Number(r.fee_rate), 2) : "—"}
              </span>,
              <Money key="n2" value={r.net_received} />,
              <Money key="a" value={r.average_order} className="text-ink-2" />,
            ],
          }))}
          foot={[
            "合计",
            <span key="o" className="num">
              {totals.orders}
            </span>,
            <Money key="s" value={totals.net_sales} className="font-semibold" />,
            <Money key="f" value={totals.fees} />,
            <span key="r" className="num">
              {totals.fee_rate ? percent(Number(totals.fee_rate), 2) : "—"}
            </span>,
            <Money key="n" value={totals.net_received} />,
            "",
          ]}
        />
      </div>
      <p className="pt-3 pb-2 text-sm text-ink-3">销售手续费只含渠道对销售的扣费；采购和费用上的手续费在「手续费」页一起看。</p>
    </Card>
  );
}

/* ---------- 上游 ---------- */

function Sites({ range }: { range: Range }) {
  const base = useBook().data?.base_commodity ?? "CNY";
  const report = useBookQuery<{ rows: CreditRow[]; totals: Record<string, MoneyValue | number> }>("/reports/credit-purchases", { date_from: range.from, date_to: range.to }, { keep: true });
  const d = report.data?.data;
  if (report.error) return <ErrorNote error={report.error} onRetry={() => report.refetch()} />;
  if (!d) return <Loading />;
  const rows = [...d.rows].sort((a, b) => b.total_paid.minor - a.total_paid.minor);
  const totals = d.totals as { total_paid: MoneyValue; face: MoneyValue; fees: MoneyValue; purchases: number };
  return (
    <Card className="px-6 pt-6 pb-3 max-sm:px-5 max-sm:pt-5">
      <Headline
        items={[
          { label: "采购实付", value: totals.total_paid },
          { label: "面值", value: totals.face },
          { label: "次数", value: String(totals.purchases) },
        ]}
      />
      <div className="mt-6">
        <Table
          caption="各上游站点采购"
          head={["站点", "次数", "面值", "实付", "额度", "每额度成本", "费率"]}
          rows={rows.map((r) => ({
            key: r.site.id,
            to: drill(r.drilldown),
            cells: [
              <Share key="n" name={r.site.name} part={r.total_paid.minor} total={totals.total_paid.minor} tone="cost" />,
              <span key="p" className="num">
                {r.purchases}
              </span>,
              <Money key="f" value={r.face} className="text-ink-2" />,
              <Money key="t" value={r.total_paid} className="font-semibold" />,
              <span key="q" className="num text-ink-2">
                {r.credit_quantity ? Number(r.credit_quantity).toLocaleString("en-US") : "—"}
              </span>,
              <span key="c" className="num text-ink-2">
                {r.cost_per_credit ? formatMoney({ minor: Math.round(Number(r.cost_per_credit) * 100), commodity: base }) : "—"}
              </span>,
              <span key="r" className="num text-ink-2">
                {r.fee_rate ? percent(Number(r.fee_rate), 2) : "—"}
              </span>,
            ],
          }))}
        />
      </div>
    </Card>
  );
}

/* ---------- 支出 ---------- */

function Spend({ range }: { range: Range }) {
  const report = useBookQuery<{ lines: IncomeLine[] }>("/reports/income-statement", { date_from: range.from, date_to: range.to }, { keep: true });
  const d = report.data?.data;
  if (report.error) return <ErrorNote error={report.error} onRetry={() => report.refetch()} />;
  if (!d) return <Loading />;
  // Leaf lines under every cost and expense heading (营业成本, 销售费用, 管理费用, 财务费用…), largest first.
  const costs: IncomeLine[] = [];
  let section = "";
  for (const l of d.lines) {
    if (l.level === 1) section = l.code;
    else if (l.level === 2 && section !== "revenue" && section !== "non_operating_income" && l.amount.minor !== 0) costs.push(l);
  }
  costs.sort((a, b) => b.amount.minor - a.amount.minor);
  const total = costs.reduce((s, l) => s + l.amount.minor, 0);
  const commodity = costs[0]?.amount.commodity ?? "CNY";
  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <Card className="p-6 lg:col-span-7 max-sm:p-5">
        <Headline items={[{ label: "成本与费用合计", value: { minor: total, commodity } }]} />
        <BarList
          className="mt-6"
          tone="cost"
          items={costs.map((l) => ({ key: l.code, label: l.name, value: l.amount, note: total ? percent(l.amount.minor / total, 0) : undefined, to: drill(l.drilldown) ?? undefined }))}
        />
        {costs.length === 0 && <p className="py-10 text-center text-sm text-ink-3">这段时间没有成本或费用</p>}
      </Card>
      <Card className="p-6 lg:col-span-5 max-sm:p-5">
        <h2 className="font-semibold">怎么算的</h2>
        <p className="mt-2 text-sm text-ink-2">
          按利润表的成本与费用科目汇总：上游额度是采购额度的成本，账号、AI
          服务订阅、服务器与网络是其他营业成本；广告推广、注册与办公、手续费记在期间费用里。点任一行看对应的交易，手续费按渠道的拆分在「手续费」页。
        </p>
      </Card>
    </div>
  );
}

/* ---------- 手续费 ---------- */

function Fees({ range }: { range: Range }) {
  const report = useBookQuery<{ rows: FeeRow[]; totals: { fee: MoneyValue; estimated_fee: MoneyValue } }>("/reports/fees", { date_from: range.from, date_to: range.to }, { keep: true });
  const d = report.data?.data;
  if (report.error) return <ErrorNote error={report.error} onRetry={() => report.refetch()} />;
  if (!d) return <Loading />;
  const rows = [...d.rows].sort((a, b) => b.fee.minor - a.fee.minor);
  return (
    <div className="grid gap-5">
      <Card className="p-6 max-sm:p-5">
        <Headline items={[{ label: "手续费合计", value: d.totals.fee }, ...(d.totals.estimated_fee.minor ? [{ label: "其中估算", value: d.totals.estimated_fee }] : [])]} />
      </Card>
      <Card className="px-6 py-3 max-sm:px-5">
        <Table
          caption="各渠道手续费"
          head={["渠道", "交易类型", "笔数", "手续费", "计费基数", "实际费率"]}
          rows={rows.map((r, i) => ({
            key: `${r.channel?.code ?? "none"}-${r.transaction_type.code}-${i}`,
            to: drill(r.drilldown),
            cells: [
              r.channel?.name ?? "未指定",
              r.transaction_type.name,
              <span key="n" className="num">
                {r.count}
              </span>,
              <span key="f" className="flex items-center justify-end gap-1.5">
                <Money value={r.fee} className="font-semibold" />
                {r.estimated_fee.minor !== 0 && <span className="text-xs text-warn-text">含估算</span>}
              </span>,
              <Money key="b" value={r.base} className="text-ink-2" />,
              <span key="r" className="num text-ink-2">
                {r.effective_rate ? percent(Number(r.effective_rate), 2) : "—"}
              </span>,
            ],
          }))}
        />
      </Card>
    </div>
  );
}

/* ---------- table ---------- */

interface TableRow {
  key: string;
  to: string | null;
  cells: React.ReactNode[];
}

/** Compact report table: first column names the row, numbers align right, rows open their transactions. */
function Table({ caption, head, rows, foot }: { caption: string; head: string[]; rows: TableRow[]; foot?: React.ReactNode[] }) {
  const navigate = useNavigate();
  if (rows.length === 0) return <p className="py-10 text-center text-sm text-ink-3">这段时间没有数据</p>;
  return (
    <div className="-mx-6 overflow-x-auto px-6 max-sm:-mx-5 max-sm:px-5">
      <table className="w-full min-w-[560px] text-base">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line text-sm text-ink-3">
            {head.map((h, i) => (
              <th key={h} scope="col" className={clsx("py-3 font-medium whitespace-nowrap", i === 0 ? "text-left" : "pl-4 text-right")}>
                {h}
              </th>
            ))}
            <th aria-hidden className="w-6" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.key}
              tabIndex={r.to ? 0 : undefined}
              onClick={() => r.to && navigate(r.to)}
              onKeyDown={(e) => r.to && e.key === "Enter" && navigate(r.to)}
              className={clsx("border-b border-line last:border-0", r.to && "cursor-pointer transition-colors duration-150 hover:bg-well focus-visible:bg-well")}
            >
              {r.cells.map((c, i) => (
                <td key={i} className={clsx("py-3 whitespace-nowrap", i === 0 ? "max-w-[220px] truncate font-medium" : "pl-4 text-right")}>
                  {c}
                </td>
              ))}
              <td className="text-right text-ink-3">{r.to && <CaretRight size={13} className="ml-auto" />}</td>
            </tr>
          ))}
        </tbody>
        {foot && (
          <tfoot>
            <tr className="border-t border-line-strong text-ink-2">
              {foot.map((c, i) => (
                <td key={i} className={clsx("py-3 font-medium whitespace-nowrap", i === 0 ? "text-left" : "pl-4 text-right")}>
                  {c}
                </td>
              ))}
              <td />
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
