/**
 * Two charts carry the statistics:
 * - FlowChart: money in above the line (green), costs below it (sand), profit as a deep green line; hover or arrow keys
 *   read a day, click or Enter opens its transactions.
 * - BarList: ranked horizontal bars (channels, upstream sites, cost categories), each row a link to its transactions.
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";
import { clsx } from "clsx";
import gsap from "gsap";
import { formatMoney, roundMoney, shortDate, weekday, type Money } from "@/lib/format";
import { RollingText } from "./Figure";
import { reducedMotion } from "./ui";

export interface FlowPoint {
  period: string;
  revenue: number;
  cost: number;
  profit: number;
}

interface FlowChartProps {
  points: FlowPoint[];
  commodity: string;
  granularity: "day" | "week" | "month";
  height?: number;
  label: string;
  onPick?: (p: FlowPoint) => void;
}

function niceCeil(v: number): number {
  if (v <= 0) return 0;
  const exp = 10 ** Math.floor(Math.log10(v));
  const f = v / exp;
  const step = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return step * exp;
}

function periodLabel(period: string, g: FlowChartProps["granularity"]): string {
  if (g === "month") return `${Number(period.slice(5, 7))}月`;
  if (g === "week") return `${shortDate(period)}起`;
  return shortDate(period);
}

function tickLabel(period: string, g: FlowChartProps["granularity"]): string {
  if (g === "month") return `${Number(period.slice(5, 7))}月`;
  if (g === "week") return `${Number(period.slice(5, 7))}/${Number(period.slice(8, 10))}`;
  return `${Number(period.slice(8, 10))}日`;
}

/** Bar with only its outer end rounded, growing up (dir 1) or down (dir -1) from y0. */
function barPath(x: number, w: number, y0: number, y1: number, dir: 1 | -1): string {
  const h = Math.abs(y1 - y0);
  if (h < 0.5) return "";
  const r = Math.min(w / 2, 4, h);
  if (dir === 1) return `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + r}V${y0}Z`;
  return `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 - r}V${y0}Z`;
}

export function FlowChart({ points, commodity, granularity, height = 200, label, onPick }: FlowChartProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState<number | null>(null);
  const tableId = useId();

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e!.contentRect.width)));
    ro.observe(el);
    setWidth(Math.round(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);

  const axisW = 56;
  const plotW = Math.max(0, width - axisW);
  const top = 8;
  const bottom = height - 22;
  const n = points.length;
  const maxIn = niceCeil(Math.max(0, ...points.map((p) => Math.max(p.revenue, p.profit))));
  const maxOut = niceCeil(Math.max(0, ...points.map((p) => Math.max(p.cost, -p.profit))));
  const span = maxIn + maxOut || 1;
  const zero = top + ((bottom - top) * maxIn) / span;
  const y = (v: number) => zero - ((bottom - top) * v) / span;
  const slot = n ? plotW / n : 0;
  const barW = Math.max(2, Math.min(22, slot * 0.56));
  const cx = (i: number) => i * slot + slot / 2;

  const line = useMemo(() => points.map((p, i) => `${i ? "L" : "M"}${cx(i).toFixed(1)},${y(p.profit).toFixed(1)}`).join(""), [points, slot, zero, span]); // eslint-disable-line react-hooks/exhaustive-deps
  const ticks = useMemo(() => {
    if (!n) return [];
    const every = granularity === "day" ? (n > 20 ? 7 : n > 10 ? 3 : 1) : n > 12 ? 2 : 1;
    return points.map((p, i) => ({ i, text: tickLabel(p.period, granularity) })).filter(({ i }) => i % every === 0);
  }, [points, n, granularity]);

  // Draw-in when the data set changes (period switch or a write): bars grow out of the zero line, the profit line draws.
  const shape = `${points[0]?.period}-${n}-${granularity}-${width > 0}`;
  useLayoutEffect(() => {
    const s = svg.current;
    if (!s || !width || reducedMotion()) return;
    const bars = s.querySelectorAll(".bar");
    const path = s.querySelector<SVGPathElement>(".profit");
    gsap.fromTo(
      bars,
      { scaleY: 0, svgOrigin: `0 ${zero}` },
      { scaleY: 1, svgOrigin: `0 ${zero}`, duration: 0.6, ease: "expo.out", stagger: Math.min(0.012, 0.36 / Math.max(1, n)), clearProps: "transform" },
    );
    if (path) {
      const len = path.getTotalLength();
      gsap.fromTo(path, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 0.9, ease: "power2.out", delay: 0.12, clearProps: "strokeDasharray,strokeDashoffset" });
    }
  }, [shape]); // eslint-disable-line react-hooks/exhaustive-deps

  function pick(clientX: number) {
    const rect = svg.current?.getBoundingClientRect();
    if (!rect || !n) return;
    const i = Math.floor((clientX - rect.left) / slot);
    setActive(i >= 0 && i < n ? i : null);
  }

  function onKey(e: KeyboardEvent) {
    if (!n) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      setActive((a) => Math.min(n - 1, Math.max(0, (a ?? (e.key === "ArrowRight" ? -1 : n)) + (e.key === "ArrowRight" ? 1 : -1))));
    } else if (e.key === "Enter" && active !== null) onPick?.(points[active]!);
    else if (e.key === "Escape") setActive(null);
  }

  const a = active !== null ? points[active] : null;
  // The read-out stays inside the plot, beside the highlighted column (right of it when it fits, else left).
  const tipW = 184; // w-46
  const tipLeft = active === null ? 0 : (active + 1) * slot + 8 + tipW <= plotW ? (active + 1) * slot + 8 : Math.max(0, active * slot - 8 - tipW);
  const money = (minor: number) => formatMoney({ minor, commodity });

  return (
    <div ref={wrap} className="relative" style={{ height }}>
      <div
        role="group"
        tabIndex={0}
        aria-label={`${label}。左右方向键逐${granularity === "day" ? "日" : granularity === "week" ? "周" : "月"}查看，回车打开明细`}
        aria-describedby={tableId}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
        className="rounded-field outline-offset-4"
      >
        {width > 0 && (
          <svg
            ref={svg}
            width={width}
            height={height}
            className="block overflow-visible"
            onPointerMove={(e) => pick(e.clientX)}
            onPointerLeave={() => setActive(null)}
            onClick={() => a && onPick?.(a)}
            style={{ cursor: onPick && a ? "pointer" : undefined }}
          >
            {[maxIn, -maxOut].filter(Boolean).map((v) => (
              <g key={v}>
                <line x1={0} x2={plotW} y1={y(v)} y2={y(v)} stroke="var(--line)" strokeDasharray="2 4" />
                <text x={width} y={y(v) + 4} textAnchor="end" className="num fill-ink-3 text-xs">
                  {roundMoney(v, commodity)}
                </text>
              </g>
            ))}
            {active !== null && <rect x={active * slot + 1} y={top - 6} width={Math.max(0, slot - 2)} height={bottom - top + 12} rx={Math.min(10, slot / 2)} fill="var(--well)" />}
            {points.map((p, i) => (
              <g key={p.period}>
                <path className="bar" d={barPath(cx(i) - barW / 2, barW, zero, y(p.revenue), 1)} fill="var(--series-in)" />
                <path className="bar" d={barPath(cx(i) - barW / 2, barW, zero, y(-p.cost), -1)} fill="var(--series-cost)" />
              </g>
            ))}
            <line x1={0} x2={plotW} y1={zero} y2={zero} stroke="var(--line-strong)" />
            <text x={width} y={zero + 4} textAnchor="end" className="num fill-ink-3 text-xs">
              0
            </text>
            {n > 1 && <path className="profit" d={line} fill="none" stroke="var(--series-profit)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />}
            {a && <circle cx={cx(active!)} cy={y(a.profit)} r={4.5} fill="var(--card)" stroke="var(--series-profit)" strokeWidth={2} />}
            {ticks.map((t) => (
              <text key={t.i} x={cx(t.i)} y={height - 4} textAnchor="middle" className="num fill-ink-3 text-xs">
                {t.text}
              </text>
            ))}
          </svg>
        )}
      </div>
      {a && (
        <div aria-hidden className="frost pointer-events-none absolute z-10 w-46 rounded-field px-3.5 py-3 text-sm" style={{ left: tipLeft, top }}>
          <p className="mb-1.5 font-semibold">
            {periodLabel(a.period, granularity)}
            {granularity === "day" && <span className="ml-1.5 font-normal text-ink-3">{weekday(a.period)}</span>}
          </p>
          <TipRow dot="var(--series-in)" label="收入" value={money(a.revenue)} />
          <TipRow dot="var(--series-cost)" label="成本" value={money(-a.cost)} />
          <TipRow dot="var(--series-profit)" label="利润" value={money(a.profit)} strong />
        </div>
      )}
      <table id={tableId} className="sr-only">
        <caption>{label}</caption>
        <thead>
          <tr>
            <th>日期</th>
            <th>收入</th>
            <th>成本</th>
            <th>利润</th>
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.period}>
              <td>{periodLabel(p.period, granularity)}</td>
              <td>{money(p.revenue)}</td>
              <td>{money(p.cost)}</td>
              <td>{money(p.profit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TipRow({ dot, label, value, strong }: { dot: string; label: string; value: string; strong?: boolean }) {
  return (
    <p className="flex items-center gap-2 py-0.5">
      <span className="size-2 shrink-0 rounded-full" style={{ background: dot }} />
      <span className="text-ink-2">{label}</span>
      <span className={clsx("num ml-auto", strong && "font-semibold")}>{value}</span>
    </p>
  );
}

export function Legend({ items }: { items: { color: string; label: string; line?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span className={clsx("shrink-0", i.line ? "h-0.5 w-3.5 rounded-full" : "size-2.5 rounded-[3px]")} style={{ background: i.color }} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

export interface BarItem {
  key: string;
  label: string;
  value: Money;
  note?: string;
  to?: string;
}

/** Ranked bars; the longest is the period's largest. Fills grow in from the left. */
export function BarList({ items, tone = "in", className }: { items: BarItem[]; tone?: "in" | "cost"; className?: string }) {
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);
  const max = Math.max(1, ...items.map((i) => Math.abs(i.value.minor)));
  return (
    <ul className={clsx("grid gap-1", className)}>
      {items.map((item) => {
        const body = (
          <>
            <span className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate font-medium">{item.label}</span>
              <RollingText text={formatMoney(item.value)} className="shrink-0" />
            </span>
            <span className="mt-2 flex items-center gap-3">
              <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-well">
                <span
                  className="block h-full origin-left rounded-full transition-transform duration-700 ease-[var(--ease-out-expo)]"
                  style={{ transform: `scaleX(${grown ? Math.abs(item.value.minor) / max : 0})`, background: tone === "in" ? "var(--series-in)" : "var(--series-cost)" }}
                />
              </span>
              {item.note && <span className="num w-14 shrink-0 text-right text-sm text-ink-3">{item.note}</span>}
            </span>
          </>
        );
        return (
          <li key={item.key}>
            {item.to ? (
              <Link to={item.to} className="-mx-3 block rounded-field px-3 py-2.5 transition-colors duration-150 hover:bg-well">
                {body}
              </Link>
            ) : (
              <div className="py-2.5">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
