import { formatMoney } from "./format";

export const CURRENCIES = [
  { code: "CNY", name: "人民币", symbol: "¥" },
  { code: "USD", name: "美元", symbol: "$" },
  { code: "GBP", name: "英镑", symbol: "£" },
  { code: "EUR", name: "欧元", symbol: "€" },
  { code: "HKD", name: "港币", symbol: "HK$" },
  { code: "JPY", name: "日元", symbol: "JP¥" },
  { code: "KRW", name: "韩元", symbol: "₩" },
  { code: "SGD", name: "新加坡元", symbol: "S$" },
  { code: "PHP", name: "菲律宾比索", symbol: "₱" },
] as const;

export type CurrencyCode = (typeof CURRENCIES)[number]["code"];

const currencyByCode = new Map<string, (typeof CURRENCIES)[number]>(
  CURRENCIES.map((currency) => [currency.code, currency]),
);

export const isCurrencyCode = (value: string): value is CurrencyCode =>
  currencyByCode.has(value);

export const getCurrencySymbol = (currency: string) =>
  currencyByCode.get(currency)?.symbol || `${currency} `;

export const getCurrencyOptionLabel = (currency: CurrencyCode) => {
  const item = currencyByCode.get(currency)!;
  return `${item.symbol} ${item.code} ${item.name}`;
};

export const formatCurrencyAmount = (
  amount: string | null | undefined,
  currency: string,
  options?: { showCode?: boolean },
) => {
  const prefix = options?.showCode ? `${currency} ` : "";
  const formatted = formatMoney(amount);
  if (formatted.startsWith("-")) {
    return `-${prefix}${getCurrencySymbol(currency)}${formatted.slice(1)}`;
  }
  return `${prefix}${getCurrencySymbol(currency)}${formatted}`;
};
