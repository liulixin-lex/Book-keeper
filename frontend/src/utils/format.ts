// Financial decimal string representation and formatting without precision loss

export function formatMoney(
  amountStr: string | null | undefined,
  currency: string = "CNY",
  options?: { showSign?: boolean; showCurrency?: boolean },
): string {
  if (amountStr === null || amountStr === undefined || amountStr === "") {
    return "0.00";
  }

  const clean = amountStr.trim();
  const isNegative = clean.startsWith("-");
  const unsigned = isNegative ? clean.slice(1) : clean;

  const parts = unsigned.split(".");
  const intPart = parts[0] || "0";
  let decPart = parts[1] || "";

  // Format integer part with thousands separators
  const formattedInt = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  // Preserve the backend's exact eight-decimal money representation for display.
  if (decPart.length < 2) {
    decPart = decPart.padEnd(2, "0");
  } else if (decPart.length > 8) {
    decPart = decPart.slice(0, 8);
  }

  const sign = isNegative ? "-" : options?.showSign ? "+" : "";
  const curr = options?.showCurrency ? `${currency} ` : "";

  return `${sign}${curr}${formattedInt}.${decPart}`;
}

export function formatCompact(amountStr: string | null | undefined): string {
  if (!amountStr) return "0.00";
  const num = parseFloat(amountStr);
  if (isNaN(num)) return "0.00";
  if (Math.abs(num) >= 1000000) {
    return (num / 1000000).toFixed(2) + "M";
  }
  if (Math.abs(num) >= 1000) {
    return (num / 1000).toFixed(2) + "k";
  }
  return formatMoney(amountStr);
}

export function isValidDecimalString(val: string): boolean {
  if (!val || val.trim() === "") return false;
  return /^-?\d+(\.\d+)?$/.test(val.trim());
}
