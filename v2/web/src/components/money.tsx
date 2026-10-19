/** How money and business types look everywhere: true minus signs, tabular figures, money in reads green. */
import { clsx } from "clsx";
import { ArrowDownLeft, ArrowUUpLeft, ArrowUUpRight, ArrowsLeftRight, Coins, Flag, NotePencil, Receipt, type Icon } from "@phosphor-icons/react";
import { currencySymbol, flowOf, formatMoney, type Money as MoneyValue } from "@/lib/format";
import { RollingText } from "./Figure";

export function Money({ value, className, signed = false }: { value: MoneyValue | null | undefined; className?: string; signed?: boolean }) {
  if (!value) return <span className={clsx("num text-ink-3", className)}>—</span>;
  const text = formatMoney(value);
  return <span className={clsx("num whitespace-nowrap", className)}>{signed && value.minor > 0 ? `+${text}` : text}</span>;
}

/** A transaction's amount as a flow: +¥357.25 in green for money in, −$12.00 in ink for money out. */
export function Flow({ type, value, className, rolling = false, muted = false }: { type: string; value: MoneyValue | null; className?: string; rolling?: boolean; muted?: boolean }) {
  if (!value) return <span className={clsx("num text-ink-3", className)}>—</span>;
  const dir = flowOf(type);
  const abs = formatMoney({ ...value, minor: Math.abs(value.minor), display: value.display?.replace(/^-/, "") });
  const text = dir === 1 ? `+${abs}` : dir === -1 ? `−${abs}` : abs;
  const tone = muted ? "text-ink-3 line-through decoration-1" : dir === 1 ? "text-pos" : "text-ink";
  return rolling ? <RollingText text={text} className={clsx(tone, className)} /> : <span className={clsx("num whitespace-nowrap", tone, className)}>{text}</span>;
}

const GLYPHS: Record<string, Icon> = {
  sale: ArrowDownLeft,
  credit_purchase: Coins,
  expense: Receipt,
  sale_refund: ArrowUUpLeft,
  purchase_refund: ArrowUUpRight,
  transfer: ArrowsLeftRight,
  opening_balance: Flag,
  manual_journal: NotePencil,
};

/** The round icon chip that leads every transaction row. Money in sits on a green wash. */
export function TypeGlyph({ type, size = "md", className }: { type: string; size?: "sm" | "md" | "lg"; className?: string }) {
  const G = GLYPHS[type] ?? NotePencil;
  const income = flowOf(type) === 1;
  return (
    <span
      aria-hidden
      className={clsx(
        "grid shrink-0 place-items-center rounded-full",
        size === "lg" ? "size-12" : size === "md" ? "size-10" : "size-8",
        income ? "bg-pos-wash text-pos" : "bg-well text-ink-2",
        className,
      )}
    >
      <G size={size === "lg" ? 22 : size === "md" ? 19 : 16} weight={income ? "bold" : "regular"} />
    </span>
  );
}

/** Currency mark for balance rows: the symbol in a soft circle, or the code for units without one (UCR). */
export function CurrencyMark({ commodity }: { commodity: string }) {
  const symbol = currencySymbol(commodity);
  return (
    <span aria-hidden className={clsx("grid size-10 shrink-0 place-items-center rounded-full bg-well font-semibold text-ink-2", symbol.length > 1 || !symbol ? "text-xs" : "text-md")}>
      {symbol || commodity.slice(0, 3)}
    </span>
  );
}
