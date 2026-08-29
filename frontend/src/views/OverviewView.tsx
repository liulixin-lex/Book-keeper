import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import {
  ArrowsLeftRight,
  CalendarBlank,
  CaretLeft,
  CaretRight,
  CircleNotch,
  CurrencyCircleDollar,
  HandCoins,
  Receipt,
  Scales,
  TrendDown,
  TrendUp,
  WarningCircle,
} from "@phosphor-icons/react";
import gsap from "gsap";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { apiRequest } from "../api/client";
import { Badge, Button } from "../components/ui/core";
import { ErrorState, TableSkeleton } from "../components/ui/feedback";
import type { DashboardReportRead } from "../types/api";
import {
  CURRENCIES,
  type CurrencyCode,
  formatCurrencyAmount,
  getCurrencyOptionLabel,
  getCurrencySymbol,
  isCurrencyCode,
} from "../utils/currency";
import { formatCompact, formatMoney } from "../utils/format";

gsap.registerPlugin(useGSAP);

type ViewBasis = "operating" | "cash";
type DatePreset = "7d" | "30d" | "6m" | "all" | "custom";

interface AnimatedMoneyProps {
  amountStr: string | null | undefined;
  className?: string;
}

const AnimatedMoney: React.FC<AnimatedMoneyProps> = ({
  amountStr,
  className = "",
}) => {
  const nodeRef = useRef<HTMLSpanElement>(null);
  const prevValueRef = useRef<number | null>(null);

  const targetValue = useMemo(() => {
    if (!amountStr) return 0;
    const clean = amountStr.trim();
    const val = parseFloat(clean);
    return isNaN(val) ? 0 : val;
  }, [amountStr]);

  const targetFormatted = useMemo(() => formatMoney(amountStr), [amountStr]);

  const decLength = useMemo(() => {
    if (!amountStr) return 2;
    const parts = amountStr.trim().split(".");
    if (parts.length < 2) return 2;
    const len = parts[1].length;
    if (len < 2) return 2;
    if (len > 8) return 8;
    return len;
  }, [amountStr]);

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const node = nodeRef.current;
    if (!node) return;

    if (prefersReducedMotion) {
      node.textContent = targetFormatted;
      prevValueRef.current = targetValue;
      return;
    }

    const startVal = prevValueRef.current !== null ? prevValueRef.current : 0;
    const proxy = { val: startVal };

    const tween = gsap.to(proxy, {
      val: targetValue,
      duration: 0.65,
      ease: "power2.out",
      onUpdate: () => {
        if (!node) return;
        const currentNum = proxy.val;
        const isNegative = currentNum < 0;
        const unsigned = Math.abs(currentNum);
        const fixedStr = unsigned.toFixed(decLength);
        const parts = fixedStr.split(".");
        const intFormatted = (parts[0] || "0").replace(
          /\B(?=(\d{3})+(?!\d))/g,
          ",",
        );
        const decPart = parts[1] || "".padEnd(decLength, "0");
        node.textContent = `${isNegative ? "-" : ""}${intFormatted}.${decPart}`;
      },
      onComplete: () => {
        if (node) {
          node.textContent = targetFormatted;
        }
      },
    });

    prevValueRef.current = targetValue;

    return () => {
      tween.kill();
    };
  }, [targetValue, targetFormatted, decLength]);

  return (
    <span ref={nodeRef} className={`font-mono-amount ${className}`}>
      {targetFormatted}
    </span>
  );
};

function shanghaiDateParts() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const value = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  );
  return { year: value.year, month: value.month, day: value.day };
}

const todayParts = shanghaiDateParts();
const today = `${todayParts.year}-${todayParts.month}-${todayParts.day}`;
const dateBefore = (days: number) => {
  const value = new Date(`${today}T00:00:00+08:00`);
  value.setUTCDate(value.getUTCDate() - days);
  return value.toISOString().slice(0, 10);
};
const sevenDayStart = dateBefore(6);
const thirtyDayStart = dateBefore(29);
const halfYearStart = dateBefore(182);
const overviewCurrencyStorageKey = "ledger_overview_currency";

const initialOverviewCurrency = (): CurrencyCode => {
  if (typeof window === "undefined") return "CNY";
  const saved = window.localStorage.getItem(overviewCurrencyStorageKey);
  return saved && isCurrencyCode(saved) ? saved : "CNY";
};

const moneyTone = (amount: string, positiveClass = "text-success") =>
  amount.startsWith("-") ? "text-danger" : positiveClass;

export const OverviewView: React.FC = () => {
  const [viewBasis, setViewBasis] = useState<ViewBasis>("operating");
  const [datePreset, setDatePreset] = useState<DatePreset>("7d");
  const [startDate, setStartDate] = useState(sevenDayStart);
  const [endDate, setEndDate] = useState(today);
  const [selectedCurrency, setSelectedCurrency] = useState<CurrencyCode>(
    initialOverviewCurrency,
  );
  const [dashboard, setDashboard] = useState<DashboardReportRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [dailyPage, setDailyPage] = useState(1);
  const [dailyPageSize, setDailyPageSize] = useState(7);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const dashboardRef = useRef<DashboardReportRead | null>(null);
  const requestIdRef = useRef(0);
  const overview = dashboard?.overview || null;
  const dailyRows = dashboard?.daily || [];

  useEffect(() => {
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleChange = (event: MediaQueryListEvent) => {
      setPrefersReducedMotion(event.matches);
    };

    setPrefersReducedMotion(mediaQuery.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, []);

  const fetchData = async (currency: CurrencyCode) => {
    const requestId = ++requestIdRef.current;
    setIsLoading(true);
    setFatalError(null);
    try {
      const query = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        display_currency: currency,
      });
      const result = await apiRequest<DashboardReportRead>(
        `/reports/dashboard?${query}`,
      );
      if (requestId !== requestIdRef.current) return;
      dashboardRef.current = result;
      setDashboard(result);
      if (isCurrencyCode(result.display_currency)) {
        setSelectedCurrency(result.display_currency);
        window.localStorage.setItem(
          overviewCurrencyStorageKey,
          result.display_currency,
        );
      }
    } catch (requestError) {
      if (requestId !== requestIdRef.current) return;
      const message =
        requestError instanceof Error ? requestError.message : "加载总览失败";
      const previous = dashboardRef.current;
      if (previous && isCurrencyCode(previous.display_currency)) {
        setSwitchError(message);
        setSelectedCurrency(previous.display_currency);
      } else if (currency !== "CNY") {
        setSwitchError(message);
        setSelectedCurrency("CNY");
      } else {
        setFatalError(message);
      }
    } finally {
      if (requestId === requestIdRef.current) setIsLoading(false);
    }
  };

  useEffect(() => {
    void fetchData(selectedCurrency);
  }, [startDate, endDate, selectedCurrency]);

  const chartGradId = useId();

  useGSAP(
    () => {
      if (!overview) return;

      const prefersReducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;

      if (prefersReducedMotion) return;

      const tl = gsap.timeline({ defaults: { ease: "power2.out" } });

      tl.fromTo(
        ".gauge-track",
        { scaleX: 0, transformOrigin: "left center", opacity: 0 },
        { scaleX: 1, opacity: 1, duration: 0.3 },
      )
        .fromTo(
          ".main-readout .readout-figure",
          { autoAlpha: 0, y: 6 },
          { autoAlpha: 1, y: 0, duration: 0.22 },
          "-=0.18",
        )
        .fromTo(
          ".main-readout .icon-module",
          { scale: 0.88, autoAlpha: 0 },
          { scale: 1, autoAlpha: 1, duration: 0.24 },
          "-=0.18",
        )
        .fromTo(
          ".secondary-readout .readout-figure",
          { autoAlpha: 0, y: 5 },
          { autoAlpha: 1, y: 0, duration: 0.18, stagger: 0.03 },
          "-=0.14",
        )
        .fromTo(
          ".secondary-readout .icon-module",
          { scale: 0.88, autoAlpha: 0 },
          { scale: 1, autoAlpha: 1, duration: 0.2, stagger: 0.03 },
          "-=0.16",
        )
        .fromTo(
          ".chart-basis-stage",
          { autoAlpha: 0.4 },
          { autoAlpha: 1, duration: 0.28 },
          "-=0.15",
        );
    },
    {
      scope: containerRef,
      dependencies: [viewBasis],
      revertOnUpdate: true,
    },
  );

  const setPreset = (preset: Exclude<DatePreset, "custom">) => {
    setDatePreset(preset);
    if (preset === "all") {
      setStartDate("2000-01-01");
      setEndDate(today);
    } else if (preset === "7d") setStartDate(sevenDayStart);
    else if (preset === "30d") setStartDate(thirtyDayStart);
    else setStartDate(halfYearStart);
    setEndDate(today);
    setDailyPage(1);
  };

  const chartRows = useMemo(
    () =>
      dailyRows.map((row) => ({
        date: row.date.slice(5),
        netRevenue: Number(row.net_revenue),
        expenses: Number(row.operating_expenses),
        cashIn: Number(row.cash_in),
        cashOut: Number(row.cash_out),
      })),
    [dailyRows],
  );
  const reversedDailyRows = useMemo(
    () => [...dailyRows].reverse(),
    [dailyRows],
  );
  const dailyTotalPages = Math.max(
    1,
    Math.ceil(reversedDailyRows.length / dailyPageSize),
  );
  const paginatedDailyRows = useMemo(
    () =>
      reversedDailyRows.slice(
        (dailyPage - 1) * dailyPageSize,
        dailyPage * dailyPageSize,
      ),
    [dailyPage, dailyPageSize, reversedDailyRows],
  );

  if (isLoading && !overview) return <TableSkeleton rows={8} cols={4} />;
  if (fatalError)
    return (
      <ErrorState
        message={fatalError}
        onRetry={() => void fetchData(selectedCurrency)}
      />
    );
  if (!overview || !dashboard) return null;

  const displayCurrency = isCurrencyCode(dashboard.display_currency)
    ? dashboard.display_currency
    : "CNY";
  const currencySymbol = getCurrencySymbol(displayCurrency);
  const rateDate = dashboard.rate.effective_at.slice(0, 10);
  const rateFetchedAt = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(dashboard.rate.fetched_at));
  const rateSourceLabel =
    dashboard.rate.source === "manual" ? "手工汇率" : "Frankfurter";

  const operatingPrimary = {
    label: "经营净额",
    value: overview.operating_net,
    note: "净收入减经营支出",
    icon: Scales,
    tone: moneyTone(overview.operating_net),
  };

  const operatingSecondaries = [
    {
      label: "毛收入",
      value: overview.gross_revenue,
      note: `净收入 ${formatCurrencyAmount(
        overview.net_revenue,
        displayCurrency,
      )}`,
      icon: TrendUp,
      tone: "text-primary",
    },
    {
      label: "收入手续费",
      value: overview.channel_fees,
      note: "期间费用",
      icon: Receipt,
      tone: "text-warning",
    },
    {
      label: "经营支出",
      value: overview.operating_expenses,
      note: "主营成本与期间费用",
      icon: TrendDown,
      tone: "text-danger",
    },
  ];

  const cashPrimary = {
    label: "净现金变化",
    value: overview.net_cash,
    note: "现金流入减现金流出",
    icon: Scales,
    tone: moneyTone(overview.net_cash, "text-primary"),
  };

  const cashSecondaries = [
    {
      label: "现金流入",
      value: overview.cash_in,
      note: "实际进入资金账户",
      icon: HandCoins,
      tone: "text-success",
    },
    {
      label: "现金流出",
      value: overview.cash_out,
      note: "实际离开资金账户",
      icon: CurrencyCircleDollar,
      tone: "text-danger",
    },
  ];

  const primaryMetric =
    viewBasis === "operating" ? operatingPrimary : cashPrimary;
  const secondaryMetrics =
    viewBasis === "operating" ? operatingSecondaries : cashSecondaries;

  const primaryDisplay = formatMoney(primaryMetric.value);
  const primarySize =
    primaryDisplay.length > 13
      ? "text-xl sm:text-2xl"
      : "text-2xl sm:text-3xl lg:text-4xl";
  const PrimaryIcon = primaryMetric.icon;

  return (
    <div ref={containerRef} className="space-y-3">
      {/* 顶部筛选栏：紧凑压缩 */}
      <section className="instrument-panel flex flex-col gap-2.5 p-2.5 sm:p-3 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
          <div
            className="instrument-inset flex w-full items-center p-0.5 sm:w-auto"
            aria-label="报表口径"
          >
            {(["operating", "cash"] as const).map((basis) => (
              <button
                key={basis}
                type="button"
                aria-pressed={viewBasis === basis}
                onClick={() => setViewBasis(basis)}
                className={`min-h-7 flex-1 whitespace-nowrap rounded-md px-3 text-xs font-medium transition-colors sm:flex-none ${
                  viewBasis === basis
                    ? "bg-surface text-ink shadow-[var(--shadow-panel)]"
                    : "text-muted hover:text-ink"
                }`}
              >
                {basis === "operating" ? "经营视图" : "现金视图"}
              </button>
            ))}
          </div>

          <div className="flex min-w-0 items-center gap-2">
            <label className="instrument-inset flex h-8 shrink-0 items-center gap-1.5 px-2">
              <CurrencyCircleDollar size={14} className="text-muted" />
              <span className="sr-only">总览显示币种</span>
              <select
                aria-label="总览显示币种"
                value={selectedCurrency}
                disabled={isLoading}
                onChange={(event) => {
                  if (!isCurrencyCode(event.target.value)) return;
                  setSwitchError(null);
                  setSelectedCurrency(event.target.value);
                  setDailyPage(1);
                }}
                className="h-7 min-w-32 bg-transparent text-xs font-semibold text-ink focus:outline-none disabled:cursor-wait disabled:opacity-60"
              >
                {CURRENCIES.map(({ code }) => (
                  <option key={code} value={code}>
                    {getCurrencyOptionLabel(code)}
                  </option>
                ))}
              </select>
            </label>
            <div
              className="min-w-0 text-[10px] leading-4 text-muted"
              aria-live="polite"
              title={dashboard.rate.source}
            >
              {displayCurrency === "CNY" ? (
                <span>人民币本位币</span>
              ) : (
                <>
                  <span className="block truncate">
                    1 {displayCurrency} = ¥
                    {formatMoney(dashboard.rate.cny_per_unit)}
                  </span>
                  <span
                    className={
                      dashboard.rate.is_stale ? "text-warning" : undefined
                    }
                  >
                    {dashboard.rate.is_stale
                      ? `缓存汇率 ${rateDate}`
                      : `${rateSourceLabel} 更新 ${rateFetchedAt}`}
                  </span>
                </>
              )}
            </div>
            {isLoading && (
              <CircleNotch
                size={13}
                weight="bold"
                className="shrink-0 animate-spin text-primary"
                aria-label="正在更新总览"
              />
            )}
          </div>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="instrument-inset flex items-center p-0.5">
            {(
              [
                ["7d", "近 7 日"],
                ["30d", "近 30 日"],
                ["6m", "半年"],
                ["all", "全部"],
              ] as const
            ).map(([preset, label]) => (
              <button
                key={preset}
                type="button"
                aria-pressed={datePreset === preset}
                onClick={() => setPreset(preset)}
                className={`min-h-7 flex-1 rounded-md px-2.5 text-xs transition-colors sm:flex-none ${
                  datePreset === preset
                    ? "bg-surface font-semibold text-ink shadow-[var(--shadow-panel)]"
                    : "text-muted hover:text-ink"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-1.5 text-xs text-muted">
            <label>
              <span className="sr-only">开始日期</span>
              <input
                type="date"
                value={startDate}
                max={endDate}
                onChange={(event) => {
                  setDatePreset("custom");
                  setStartDate(event.target.value);
                  setDailyPage(1);
                }}
                className="instrument-control h-7 w-full px-2 text-xs text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </label>
            <span className="text-muted/70">至</span>
            <label>
              <span className="sr-only">结束日期</span>
              <input
                type="date"
                value={endDate}
                min={startDate}
                onChange={(event) => {
                  setDatePreset("custom");
                  setEndDate(event.target.value);
                  setDailyPage(1);
                }}
                className="instrument-control h-7 w-full px-2 text-xs text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </label>
          </div>
        </div>
      </section>

      {switchError && (
        <div
          role="alert"
          className="instrument-strip flex items-start gap-2 px-3 py-2 text-xs text-warning"
        >
          <WarningCircle size={15} weight="fill" className="mt-0.5 shrink-0" />
          <span>币种切换失败，已保留上一次成功的数据。{switchError}</span>
        </div>
      )}

      {/* 机械账本读数台：不等宽、连续、扫描轨道 */}
      <section className="instrument-panel relative overflow-hidden p-0">
        {/* 顶部扫描轨道 */}
        <div className="gauge-track h-0.5 w-full bg-gradient-to-r from-primary via-primary/60 to-border" />

        <div className="flex flex-col divide-y divide-border lg:flex-row lg:divide-x lg:divide-y-0">
          {/* 主读数台：宽区 */}
          <article className="main-readout flex flex-1 flex-col justify-between bg-surface-raised/40 p-3.5 sm:p-4 lg:p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-ink">
                  {primaryMetric.label}
                </span>
                <span className="inline-flex items-center rounded border border-border bg-surface px-1.5 py-0.5 text-[10px] font-medium text-muted">
                  主读数
                </span>
              </div>
              <div className="icon-module">
                <PrimaryIcon
                  size={20}
                  className={primaryMetric.tone}
                  aria-hidden="true"
                />
              </div>
            </div>
            <div className="my-2.5 sm:my-3">
              <div
                className={`readout-figure metric-figure whitespace-nowrap leading-tight ${primarySize} ${primaryMetric.tone}`}
              >
                {currencySymbol}
                <AnimatedMoney amountStr={primaryMetric.value} />
              </div>
            </div>
            <p className="text-xs leading-relaxed text-muted">
              {primaryMetric.note}
            </p>
          </article>

          {/* 紧凑次读数台：紧凑并排 */}
          <div
            className={`grid divide-y divide-border bg-surface sm:divide-x sm:divide-y-0 ${
              secondaryMetrics.length === 3
                ? "grid-cols-1 sm:grid-cols-3 lg:w-[58%]"
                : "grid-cols-1 sm:grid-cols-2 lg:w-[48%]"
            }`}
          >
            {secondaryMetrics.map(
              ({ label, value, note, icon: Icon, tone }) => {
                const displayVal = formatMoney(value);
                const isLong = displayVal.length > 12;
                return (
                  <article
                    key={label}
                    className="secondary-readout flex flex-col justify-between p-3 sm:p-3.5"
                  >
                    <div className="flex items-center justify-between gap-2 text-muted">
                      <span className="text-xs font-medium">{label}</span>
                      <div className="icon-module">
                        <Icon size={14} className={tone} aria-hidden="true" />
                      </div>
                    </div>
                    <div
                      className={`readout-figure my-1.5 whitespace-nowrap metric-figure font-semibold leading-tight ${
                        isLong ? "text-sm sm:text-base" : "text-base sm:text-lg"
                      } ${tone}`}
                    >
                      {currencySymbol}
                      <AnimatedMoney amountStr={value} />
                    </div>
                    <p className="truncate text-[11px] text-muted">{note}</p>
                  </article>
                );
              },
            )}
          </div>
        </div>
      </section>

      {/* 趋势图与期间摘要：压缩高度 */}
      <section className="grid grid-cols-1 gap-3 xl:grid-cols-[7fr_3fr]">
        <div className="chart-basis-stage min-w-0 p-3 sm:p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-ink">
                {viewBasis === "operating" ? "每日经营趋势" : "每日现金趋势"}
              </h2>
              <p className="text-[11px] text-muted">
                图表数值用于可视化，账务计算由后端总账完成
              </p>
            </div>
            <Badge variant="info">{dailyRows.length} 个记账日</Badge>
          </div>
          <div className="h-[210px] w-full" aria-label="每日收支趋势图">
            {chartRows.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={chartRows}
                  margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
                >
                  <defs>
                    {/* SVG Glow Filter */}
                    <filter
                      id={`chart-glow-${chartGradId}`}
                      x="-20%"
                      y="-20%"
                      width="140%"
                      height="140%"
                    >
                      <feGaussianBlur stdDeviation="2.5" result="blur" />
                      <feComposite
                        in="SourceGraphic"
                        in2="blur"
                        operator="over"
                      />
                    </filter>

                    {/* Operating Gradients */}
                    <linearGradient
                      id={`grad-operating-net-${chartGradId}`}
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor="var(--primary)"
                        stopOpacity={0.45}
                      />
                      <stop
                        offset="75%"
                        stopColor="var(--primary)"
                        stopOpacity={0.08}
                      />
                      <stop
                        offset="100%"
                        stopColor="var(--primary)"
                        stopOpacity={0.0}
                      />
                    </linearGradient>

                    {/* Cash Gradients */}
                    <linearGradient
                      id={`grad-cash-in-${chartGradId}`}
                      x1="0"
                      y1="0"
                      x2="0"
                      y2="1"
                    >
                      <stop
                        offset="0%"
                        stopColor="var(--secondary)"
                        stopOpacity={0.45}
                      />
                      <stop
                        offset="75%"
                        stopColor="var(--secondary)"
                        stopOpacity={0.08}
                      />
                      <stop
                        offset="100%"
                        stopColor="var(--secondary)"
                        stopOpacity={0.0}
                      />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    vertical={false}
                    stroke="var(--border)"
                    strokeDasharray="3 3"
                  />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: "var(--muted)" }}
                    stroke="var(--border)"
                  />
                  <YAxis
                    width={68}
                    tick={{ fontSize: 10, fill: "var(--muted)" }}
                    stroke="var(--border)"
                    tickFormatter={(value) =>
                      `${currencySymbol}${formatCompact(String(value))}`
                    }
                  />
                  <Tooltip
                    formatter={(value) =>
                      formatCurrencyAmount(String(value), displayCurrency)
                    }
                    contentStyle={{
                      backgroundColor: "var(--surface-raised)",
                      borderColor: "var(--border)",
                      borderRadius: "8px",
                      boxShadow: "var(--shadow-panel)",
                      color: "var(--ink)",
                      fontSize: "12px",
                    }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: "11px", color: "var(--ink)" }}
                  />
                  {viewBasis === "operating" ? (
                    <>
                      <Area
                        type="monotone"
                        dataKey="netRevenue"
                        name="净收入"
                        stroke="var(--primary)"
                        strokeWidth={2.2}
                        fill={`url(#grad-operating-net-${chartGradId})`}
                        isAnimationActive={!prefersReducedMotion}
                        animationDuration={650}
                        animationEasing="ease-out"
                        filter={`url(#chart-glow-${chartGradId})`}
                      />
                      <Line
                        type="monotone"
                        dataKey="expenses"
                        name="经营支出"
                        stroke="var(--chart-warm)"
                        strokeWidth={2}
                        dot={{ r: 2, fill: "var(--chart-warm)" }}
                        activeDot={{ r: 4, stroke: "var(--surface)" }}
                        isAnimationActive={!prefersReducedMotion}
                        animationDuration={650}
                        animationEasing="ease-out"
                      />
                    </>
                  ) : (
                    <>
                      <Area
                        type="monotone"
                        dataKey="cashIn"
                        name="现金流入"
                        stroke="var(--secondary)"
                        strokeWidth={2.2}
                        fill={`url(#grad-cash-in-${chartGradId})`}
                        isAnimationActive={!prefersReducedMotion}
                        animationDuration={650}
                        animationEasing="ease-out"
                        filter={`url(#chart-glow-${chartGradId})`}
                      />
                      <Line
                        type="monotone"
                        dataKey="cashOut"
                        name="现金流出"
                        stroke="var(--chart-warm)"
                        strokeWidth={2}
                        dot={{ r: 2, fill: "var(--chart-warm)" }}
                        activeDot={{ r: 4, stroke: "var(--surface)" }}
                        isAnimationActive={!prefersReducedMotion}
                        animationDuration={650}
                        animationEasing="ease-out"
                      />
                    </>
                  )}
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-muted">
                当前区间没有趋势数据
              </div>
            )}
          </div>
        </div>

        {/* 期间摘要：整合成员支出 */}
        <aside className="instrument-panel-raised flex flex-col justify-between p-3 sm:p-4">
          <div>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-ink">期间摘要</h2>
                <p className="text-[11px] text-muted">
                  {overview.start_date} 至 {overview.end_date}
                </p>
              </div>
              <CalendarBlank
                size={18}
                className="text-primary"
                aria-hidden="true"
              />
            </div>
            <dl className="mt-3 space-y-2 text-xs">
              <div className="flex items-end justify-between gap-3 border-b border-border/70 pb-2">
                <dt className="text-muted">正式记录</dt>
                <dd className="metric-figure text-sm font-semibold text-ink">
                  {overview.posted_records} 笔
                </dd>
              </div>
              <div className="flex items-end justify-between gap-3 border-b border-border/70 pb-2">
                <dt className="text-muted">净收入</dt>
                <dd className="metric-figure text-xs font-semibold text-ink">
                  {formatCurrencyAmount(overview.net_revenue, displayCurrency)}
                </dd>
              </div>
              <div className="flex items-end justify-between gap-3 border-b border-border/70 pb-2">
                <dt className="text-muted">经营净额</dt>
                <dd
                  className={`metric-figure text-xs font-semibold ${moneyTone(overview.operating_net)}`}
                >
                  {formatCurrencyAmount(
                    overview.operating_net,
                    displayCurrency,
                  )}
                </dd>
              </div>
              <div className="flex items-end justify-between gap-3">
                <dt className="text-muted">净现金变化</dt>
                <dd
                  className={`metric-figure text-xs font-semibold ${moneyTone(overview.net_cash, "text-primary")}`}
                >
                  {formatCurrencyAmount(overview.net_cash, displayCurrency)}
                </dd>
              </div>
            </dl>
          </div>

          {/* 整合的成员支出（替代原先的独立大横条） */}
          {viewBasis === "operating" &&
            overview.expense_by_user &&
            overview.expense_by_user.length > 0 && (
              <div className="mt-3 border-t border-border/70 pt-2.5">
                <div className="mb-1.5 flex items-center justify-between">
                  <span className="text-[11px] font-medium text-muted">
                    成员支出明细
                  </span>
                  <span className="text-[10px] text-muted">
                    共 {overview.expense_by_user.length} 人
                  </span>
                </div>
                <div className="max-h-20 space-y-1 overflow-y-auto pr-1">
                  {overview.expense_by_user.map((item) => (
                    <div
                      key={item.user_id || item.username}
                      className="flex items-center justify-between text-[11px]"
                    >
                      <span className="truncate text-muted">
                        {item.username}
                      </span>
                      <span className="metric-figure font-medium text-danger">
                        {formatCurrencyAmount(item.amount, displayCurrency)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
        </aside>
      </section>

      {/* 每日收支表 */}
      <section className="data-table-shell">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">每日收支</h2>
            <p className="mt-1 text-xs text-muted">
              同时呈现经营与现金口径，便于快速核对差异
            </p>
          </div>
          <ArrowsLeftRight
            size={18}
            className="text-muted"
            aria-hidden="true"
          />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-xs">
            <thead className="border-b border-border bg-surface-strong/60 text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">日期</th>
                <th className="px-4 py-3 text-right font-medium">毛收入</th>
                <th className="px-4 py-3 text-right font-medium">手续费</th>
                <th className="px-4 py-3 text-right font-medium">经营支出</th>
                <th className="px-4 py-3 text-right font-medium">经营净额</th>
                <th className="px-4 py-3 text-right font-medium">净现金变化</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {paginatedDailyRows.map((row) => (
                <tr key={row.date} className="hover:bg-surface-strong/40">
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-ink">
                    {row.date}
                  </td>
                  <td className="px-4 py-3 text-right font-mono-amount text-ink">
                    {formatCurrencyAmount(row.gross_revenue, displayCurrency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono-amount text-warning">
                    {formatCurrencyAmount(row.channel_fees, displayCurrency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono-amount text-danger">
                    {formatCurrencyAmount(
                      row.operating_expenses,
                      displayCurrency,
                    )}
                  </td>
                  <td
                    className={`px-4 py-3 text-right font-mono-amount ${moneyTone(row.operating_net)}`}
                  >
                    {formatCurrencyAmount(row.operating_net, displayCurrency)}
                  </td>
                  <td
                    className={`px-4 py-3 text-right font-mono-amount ${moneyTone(row.net_cash, "text-primary")}`}
                  >
                    {formatCurrencyAmount(row.net_cash, displayCurrency)}
                  </td>
                </tr>
              ))}
              {!dailyRows.length && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-muted">
                    当前区间没有日报数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex flex-col gap-3 border-t border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <label className="flex items-center gap-2 text-xs text-muted">
            每页
            <select
              value={dailyPageSize}
              onChange={(event) => {
                setDailyPageSize(Number(event.target.value));
                setDailyPage(1);
              }}
              className="instrument-control h-8 px-2 text-xs text-ink"
            >
              {[7, 15, 30, 60].map((size) => (
                <option key={size} value={size}>
                  {size} 条
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-1 text-xs text-muted">
              第 {dailyPage} / {dailyTotalPages} 页
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="日报上一页"
              disabled={dailyPage <= 1}
              onClick={() =>
                setDailyPage((current) => Math.max(1, current - 1))
              }
            >
              <CaretLeft size={15} />
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              aria-label="日报下一页"
              disabled={dailyPage >= dailyTotalPages}
              onClick={() =>
                setDailyPage((current) =>
                  Math.min(dailyTotalPages, current + 1),
                )
              }
            >
              <CaretRight size={15} />
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
};
