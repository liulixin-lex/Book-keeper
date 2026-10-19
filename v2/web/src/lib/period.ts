/** Reporting periods shared by 概览, 统计 and 交易: a preset key in the URL, resolved against the book's today. */
import { addDays, monthEnd, monthStart } from "./format";

export type PeriodKey = "month" | "last-month" | "30d" | "year";

export const PERIODS: { value: PeriodKey; label: string }[] = [
  { value: "month", label: "本月" },
  { value: "last-month", label: "上月" },
  { value: "30d", label: "近 30 天" },
  { value: "year", label: "今年" },
];

export interface Range {
  from: string;
  to: string;
}

export function isPeriod(v: string | null): v is PeriodKey {
  return PERIODS.some((p) => p.value === v);
}

export function rangeOf(key: PeriodKey, today: string): Range {
  if (key === "month") return { from: monthStart(today), to: today };
  if (key === "last-month") {
    const end = addDays(monthStart(today), -1);
    return { from: monthStart(end), to: end };
  }
  if (key === "30d") return { from: addDays(today, -29), to: today };
  return { from: `${today.slice(0, 4)}-01-01`, to: today };
}

/** The span a period is compared with: the same days of the previous month / year, or the 30 days before. */
export function previousRange(key: PeriodKey, today: string): Range {
  const r = rangeOf(key, today);
  if (key === "30d") return { from: addDays(r.from, -30), to: addDays(r.from, -1) };
  if (key === "year") {
    const y = Number(today.slice(0, 4)) - 1;
    return { from: `${y}-01-01`, to: `${y}${today.slice(4)}` };
  }
  const prevEnd = addDays(r.from, -1);
  const from = monthStart(prevEnd);
  const day = Math.min(Number(r.to.slice(8, 10)), Number(monthEnd(prevEnd).slice(8, 10)));
  return { from, to: key === "last-month" ? prevEnd : `${prevEnd.slice(0, 7)}-${String(day).padStart(2, "0")}` };
}

export function comparedWith(key: PeriodKey): string {
  return key === "year" ? "去年同期" : key === "30d" ? "前 30 天" : key === "last-month" ? "前一个月" : "上月同期";
}

/** Day bars up to about six weeks, then weeks, then months. */
export function granularity(r: Range): "day" | "week" | "month" {
  const days = (Date.parse(r.to) - Date.parse(r.from)) / 86_400_000 + 1;
  return days <= 45 ? "day" : days <= 200 ? "week" : "month";
}
