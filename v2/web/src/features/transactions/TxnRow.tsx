/** One transaction as an activity row: type chip, what it was, when, and the signed amount. Used by 概览 and 交易. */
import { clsx } from "clsx";
import { useNames, useTransactionTypes } from "@/api/queries";
import type { Transaction } from "@/api/types";
import { Badge } from "@/components/ui";
import { Flow, TypeGlyph } from "@/components/money";
import { clock, dayLabel, bookDate } from "@/lib/format";

export const TYPE_SHORT: Record<string, string> = {
  sale: "销售",
  credit_purchase: "额度采购",
  expense: "费用",
  transfer: "划转",
  sale_refund: "销售退款",
  purchase_refund: "采购退款",
  opening_balance: "期初余额",
  manual_journal: "手工凭证",
};

export function TxnRow({ t, onOpen, showDate = false, active = false }: { t: Transaction; onOpen: (t: Transaction) => void; showDate?: boolean; active?: boolean }) {
  const names = useNames();
  const types = useTransactionTypes().data;
  const deleted = t.status === "reversed";
  const channel = t.channel_id ? names.channel.get(t.channel_id)?.name : null;
  const when = [showDate ? dayLabel(t.effective_date, bookDate()) : null, clock(t.occurred_at)].filter(Boolean).join(" ");
  const meta = [TYPE_SHORT[t.type] ?? types?.find((x) => x.code === t.type)?.name ?? t.type, channel, when].filter(Boolean).join(" · ");
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(t)}
        aria-current={active || undefined}
        className={clsx("-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3.5 rounded-field px-3 py-2.5 text-left transition-colors duration-150", active ? "bg-well" : "hover:bg-well")}
      >
        <TypeGlyph type={t.type} className={clsx(deleted && "opacity-50")} />
        <span className="min-w-0 flex-1">
          <span className={clsx("block truncate font-medium", deleted && "text-ink-3")}>{t.description}</span>
          <span className="mt-0.5 flex items-center gap-2 text-sm text-ink-3">
            <span className="truncate">{meta}</span>
            {deleted && <Badge>已删除</Badge>}
            {t.is_estimate && !deleted && <Badge tone="warn">估算</Badge>}
          </span>
        </span>
        <Flow type={t.type} value={t.amount} muted={deleted} className="shrink-0 text-base font-semibold" />
      </button>
    </li>
  );
}
