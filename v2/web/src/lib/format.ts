/** Formatting helpers. Amounts arrive from the API as integer minor units plus a server-rendered display string. */

export interface Money {
  minor: number;
  commodity: string;
  display?: string;
}

export const BOOK_TZ = "Asia/Shanghai";

/** YYYY-MM-DD of an instant in the book timezone. */
export function bookDate(at: Date = new Date(), tz: string = BOOK_TZ): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function monthStart(iso: string): string {
  return `${iso.slice(0, 7)}-01`;
}

export function monthEnd(iso: string): string {
  const d = new Date(`${iso.slice(0, 7)}-01T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() + 1);
  d.setUTCDate(0);
  return d.toISOString().slice(0, 10);
}

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

export function weekday(iso: string): string {
  return WEEKDAYS[new Date(`${iso}T00:00:00Z`).getUTCDay()] ?? "";
}

/** "HH:mm" of an instant in the book timezone; null when the record only has a day. */
export function clock(at: string | null | undefined, tz: string = BOOK_TZ): string | null {
  if (!at) return null;
  return new Intl.DateTimeFormat("zh-CN", { timeZone: tz, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(at));
}

/** Short relative day label against today: 今天 / 昨天 / MM-DD / YYYY-MM-DD. */
export function dayLabel(iso: string, today: string): string {
  if (iso === today) return "今天";
  if (iso === addDays(today, -1)) return "昨天";
  if (iso.slice(0, 4) === today.slice(0, 4)) return iso.slice(5);
  return iso;
}

const SYMBOLS: Record<string, string> = { CNY: "¥", USD: "$", GBP: "£", EUR: "€", HKD: "HK$", JPY: "¥" };

/** Split a money value into sign, symbol and digits so the digits can be set in tabular figures. */
export function moneyParts(m: Money, decimals = 2): { sign: "" | "-"; symbol: string; digits: string; unit: string } {
  const sign = m.minor < 0 ? "-" : "";
  const abs = Math.abs(m.minor);
  const symbol = SYMBOLS[m.commodity] ?? "";
  const unit = symbol ? "" : m.commodity;
  const scale = 10 ** decimals;
  const whole = Math.floor(abs / scale).toLocaleString("en-US");
  const frac = decimals > 0 ? `.${String(abs % scale).padStart(decimals, "0")}` : "";
  return { sign, symbol, digits: `${whole}${frac}`, unit };
}

export function formatMoney(m: Money, decimals = 2): string {
  if (m.display && decimals === 2) return m.display.replace(/^-/, "−");
  const p = moneyParts(m, decimals);
  return `${p.sign ? "−" : ""}${p.symbol}${p.digits}${p.unit ? ` ${p.unit}` : ""}`;
}

/** Parse a user-typed amount ("1,234.5", "¥ 12") into the API's string decimal, or null when invalid. */
export function parseAmount(input: string): string | null {
  const cleaned = input.replace(/[,\s¥$£€]/g, "").replace(/^＋/, "");
  if (!/^-?\d+(\.\d{0,8})?$/.test(cleaned)) return null;
  return cleaned;
}

export function percent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** Integer minor units → plain decimal string for an input field ("1234.50"). */
export function fromMinor(minor: number, scale = 2): string {
  const sign = minor < 0 ? "-" : "";
  const abs = Math.abs(minor);
  if (scale === 0) return `${sign}${abs}`;
  const unit = 10 ** scale;
  return `${sign}${Math.floor(abs / unit)}.${String(abs % unit).padStart(scale, "0")}`;
}

/** "10月19日" for lists and chart tooltips. */
export function shortDate(iso: string): string {
  return `${Number(iso.slice(5, 7))}月${Number(iso.slice(8, 10))}日`;
}

/** Axis and badge figures: whole units with grouping, ¥12,000. */
export function roundMoney(minor: number, commodity: string, scale = 2): string {
  const symbol = SYMBOLS[commodity] ?? "";
  const whole = Math.round(Math.abs(minor) / 10 ** scale).toLocaleString("en-US");
  return `${minor < 0 ? "−" : ""}${symbol}${whole}`;
}

export function currencySymbol(commodity: string): string {
  return SYMBOLS[commodity] ?? "";
}

/** Direction of a business type for display: money in (+), money out (−) or moved between own accounts (0). */
const INFLOW = new Set(["sale", "purchase_refund"]);
const OUTFLOW = new Set(["credit_purchase", "expense", "sale_refund"]);
export function flowOf(type: string): 1 | -1 | 0 {
  return INFLOW.has(type) ? 1 : OUTFLOW.has(type) ? -1 : 0;
}
