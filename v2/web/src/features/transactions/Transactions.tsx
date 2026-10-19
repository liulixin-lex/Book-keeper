/**
 * 交易: search, a few capsule filters and the list grouped by day. Rows open the detail sheet (?tx=number),
 * where a transaction is edited or deleted directly; deleted ones live behind the 已删除 filter and can be restored.
 */
import { useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router";
import { useInfiniteQuery } from "@tanstack/react-query";
import { MagnifyingGlass, Receipt, X } from "@phosphor-icons/react";
import { api } from "@/api/client";
import { keys, useAccounts, useNames } from "@/api/queries";
import type { Transaction } from "@/api/types";
import { useBookId } from "@/app/book";
import { Button, Card, Chip, Empty, ErrorNote, PageHeader, Skeleton } from "@/components/ui";
import { useEntry } from "@/features/entry/EntryProvider";
import { bookDate, flowOf, formatMoney, shortDate, weekday, addDays } from "@/lib/format";
import { rangeOf, type PeriodKey } from "@/lib/period";
import { TxnRow } from "./TxnRow";
import { TxnSheet } from "./TxnSheet";

const PAGE = 50;

/** Filter toggles: nothing on means everything; a lime capsule always means a filter is narrowing the list. */
const TYPES: { value: string; label: string }[] = [
  { value: "sale", label: "销售" },
  { value: "credit_purchase", label: "采购" },
  { value: "expense", label: "费用" },
  { value: "sale_refund,purchase_refund", label: "退款" },
  { value: "transfer", label: "划转" },
];

const SPANS: { value: PeriodKey; label: string }[] = [
  { value: "month", label: "本月" },
  { value: "last-month", label: "上月" },
  { value: "30d", label: "近 30 天" },
];

/** Filters that arrive from a figure elsewhere (a channel bar, a balance row) and show as removable capsules. */
const LINKED = ["channel", "counterparty", "account", "commodity", "tag", "estimate"] as const;

export default function Transactions() {
  const bookId = useBookId();
  const [params, setParams] = useSearchParams();
  const names = useNames();
  const accounts = useAccounts().data;
  const entry = useEntry();
  const today = bookDate();

  const q = params.get("q") ?? "";
  const type = params.get("type") ?? "";
  const deleted = params.get("deleted") === "1";
  const from = params.get("from");
  const to = params.get("to");
  const tx = params.get("tx");
  const typing = useRef<number | undefined>(undefined);

  const update = (patch: Record<string, string | null>, replace = true) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v) next.set(k, v);
          else next.delete(k);
        }
        return next;
      },
      { replace },
    );

  const span = SPANS.find((s) => from && to && rangeOf(s.value, today).from === from && rangeOf(s.value, today).to === to)?.value ?? (from || to ? "custom" : "");

  const filters = useMemo(() => {
    const f: Record<string, string> = { status: deleted ? "reversed" : "posted" };
    if (q) f.q = q;
    if (type) f.type = type;
    if (from) f.date_from = from;
    if (to) f.date_to = to;
    for (const k of LINKED) {
      const v = params.get(k);
      if (!v) continue;
      if (k === "estimate") f.is_estimate = "true";
      else f[k] = v;
    }
    return f;
  }, [q, type, deleted, from, to, params]);

  const list = useInfiniteQuery({
    queryKey: keys.scope(bookId, "transactions", filters),
    queryFn: async ({ pageParam, signal }) => api.get<Transaction[]>(`/books/${bookId}/transactions`, { ...filters, limit: PAGE, cursor: pageParam }, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => (last.meta.has_more ? (last.meta.next_cursor ?? undefined) : undefined),
  });

  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.data) ?? [], [list.data]);
  const days = useMemo(() => {
    const groups: { date: string; items: Transaction[]; net: Map<string, number> }[] = [];
    for (const t of rows) {
      let g = groups[groups.length - 1];
      if (!g || g.date !== t.effective_date) groups.push((g = { date: t.effective_date, items: [], net: new Map() }));
      g.items.push(t);
      if (t.amount && !deleted) g.net.set(t.amount.commodity, (g.net.get(t.amount.commodity) ?? 0) + flowOf(t.type) * Math.abs(t.amount.minor));
    }
    return groups;
  }, [rows, deleted]);

  // Load the next page as the end of the list scrolls into view.
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => e?.isIntersecting && list.hasNextPage && !list.isFetchingNextPage && list.fetchNextPage(), { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  }, [list]);

  const linked = LINKED.map((k) => [k, params.get(k)] as const).filter(([, v]) => v);
  const linkedLabel = (k: string, v: string) => {
    if (k === "channel") return `渠道：${[...names.channel.values()].find((c) => c.code === v)?.name ?? v}`;
    if (k === "counterparty") return `往来方：${v}`;
    if (k === "account") return `科目：${accounts?.find((a) => a.code === v)?.name ?? v}`;
    if (k === "commodity") return `币种：${v}`;
    if (k === "estimate") return "手续费为估算";
    return `标签：${v}`;
  };

  return (
    <>
      <PageHeader title="交易">
        <label className="relative block w-72 max-sm:w-full">
          <span className="sr-only">搜索交易</span>
          <MagnifyingGlass size={17} className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            defaultValue={q}
            placeholder="搜索摘要、往来方、订单号"
            onChange={(e) => {
              const v = e.target.value;
              window.clearTimeout(typing.current);
              typing.current = window.setTimeout(() => update({ q: v.trim() || null }), 250);
            }}
            className="h-10 w-full rounded-full bg-card pr-4 pl-10 text-base shadow-card placeholder:text-ink-3 focus:shadow-[0_0_0_3px_var(--lime-wash)] focus:outline-none"
          />
        </label>
      </PageHeader>

      <div className="mb-5 grid gap-3">
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0">
          {TYPES.map((t) => (
            <Chip key={t.value} on={type === t.value} onClick={() => update({ type: type === t.value ? null : t.value })}>
              {t.label}
            </Chip>
          ))}
          <span aria-hidden className="mx-1 w-px shrink-0 self-stretch bg-line-strong" />
          {SPANS.map((s) => (
            <Chip
              key={s.value}
              on={span === s.value}
              onClick={() => {
                const r = span === s.value ? null : rangeOf(s.value, today);
                update({ from: r?.from ?? null, to: r?.to ?? null });
              }}
            >
              {s.label}
            </Chip>
          ))}
          {span === "custom" && (
            <Chip on onClick={() => update({ from: null, to: null })} aria-label="清除日期筛选">
              {from === to ? shortDate(from!) : `${from ? shortDate(from) : "…"} – ${to ? shortDate(to) : "…"}`}
              <X size={12} weight="bold" />
            </Chip>
          )}
          <span aria-hidden className="mx-1 w-px shrink-0 self-stretch bg-line-strong" />
          <Chip on={deleted} onClick={() => update({ deleted: deleted ? null : "1" })}>
            已删除
          </Chip>
        </div>
        {linked.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {linked.map(([k, v]) => (
              <button
                key={k}
                type="button"
                onClick={() => update({ [k]: null })}
                className="inline-flex h-8 items-center gap-1.5 rounded-full bg-card px-3.5 text-sm font-medium shadow-card hover:bg-well"
                aria-label={`移除筛选 ${linkedLabel(k, v!)}`}
              >
                {linkedLabel(k, v!)}
                <X size={12} weight="bold" className="text-ink-3" />
              </button>
            ))}
          </div>
        )}
      </div>

      {list.error ? (
        <ErrorNote error={list.error} onRetry={() => list.refetch()} />
      ) : !list.data ? (
        <ListSkeleton />
      ) : rows.length === 0 ? (
        <Card className="py-4">
          {deleted ? (
            <Empty icon={<Receipt size={22} />} title="没有已删除的交易">
              删除的交易会出现在这里，随时可以恢复。
            </Empty>
          ) : q || type || from || linked.length ? (
            <Empty icon={<MagnifyingGlass size={22} />} title="没有符合条件的交易" action={<Button onClick={() => setParams({}, { replace: true })}>清除筛选</Button>}>
              换个关键词，或去掉一些筛选条件。
            </Empty>
          ) : (
            <Empty
              icon={<Receipt size={22} />}
              title="还没有交易"
              action={
                <Button variant="primary" onClick={() => entry.open()}>
                  记一笔
                </Button>
              }
            >
              记下的销售、采购和费用会按日期列在这里。
            </Empty>
          )}
        </Card>
      ) : (
        <div className="grid gap-5">
          {days.map((d) => (
            <section key={d.date} aria-label={`${d.date} 的交易`}>
              <header className="mb-2 flex items-baseline justify-between px-6 max-sm:px-5">
                <h2 className="text-sm font-semibold text-ink-2">
                  {d.date === today ? "今天" : d.date === addDays(today, -1) ? "昨天" : shortDate(d.date)}
                  <span className="ml-2 font-normal text-ink-3">
                    {d.date.slice(0, 4) !== today.slice(0, 4) && `${d.date.slice(0, 4)} · `}
                    {weekday(d.date)}
                  </span>
                </h2>
                {!deleted && (
                  <span className="num text-sm text-ink-3">
                    {[...d.net.entries()]
                      .filter(([, v]) => v !== 0)
                      .map(([c, v]) => `${v > 0 ? "+" : ""}${formatMoney({ minor: v, commodity: c })}`)
                      .join("  ")}
                  </span>
                )}
              </header>
              <Card className="px-6 py-2 max-sm:px-5">
                <ul>
                  {d.items.map((t) => (
                    <TxnRow key={t.id} t={t} active={tx === t.number} onOpen={() => update({ tx: t.number }, false)} />
                  ))}
                </ul>
              </Card>
            </section>
          ))}
          <div ref={sentinel} className="grid place-items-center py-2">
            {list.hasNextPage ? (
              <Button variant="ghost" loading={list.isFetchingNextPage} onClick={() => list.fetchNextPage()}>
                加载更多
              </Button>
            ) : (
              <p className="text-sm text-ink-3">共 {rows.length} 笔</p>
            )}
          </div>
        </div>
      )}

      <TxnSheet number={tx} onClose={() => update({ tx: null })} />
    </>
  );
}

function ListSkeleton() {
  return (
    <div className="grid gap-5" role="status" aria-label="加载中">
      {[4, 3].map((n, g) => (
        <div key={g} className="grid gap-2">
          <Skeleton className="ml-1 h-4 w-24" />
          <Card className="grid gap-5 px-5 py-4">
            {Array.from({ length: n }, (_, i) => (
              <div key={i} className="flex items-center gap-3.5">
                <Skeleton className="size-10 rounded-full" />
                <div className="grid flex-1 gap-1.5">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-1/4" />
                </div>
                <Skeleton className="h-4 w-20" />
              </div>
            ))}
          </Card>
        </div>
      ))}
    </div>
  );
}
