/**
 * 待确认: records that may already be in the books, grouped by the booking they may belong to (a day's top-ups
 * against that day's total). One question per booking — the same, or not — never one click per record.
 */
import { Link } from "react-router";
import { api, ApiError } from "@/api/client";
import { useBookMutation } from "@/api/queries";
import type { SourceRecord } from "@/api/types";
import { Button } from "@/components/ui";
import { useToast } from "@/components/toast";
import { clock, formatMoney, shortDate } from "@/lib/format";

export function ReviewGroups({ batchId, records, editable }: { batchId: string; records: SourceRecord[]; editable: boolean }) {
  const groups = new Map<string, SourceRecord[]>();
  for (const r of records) {
    const key = r.match?.transaction.id ?? r.id;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  return (
    <ul className="grid gap-3 py-2">
      {[...groups.values()].map((group) => (
        <Group key={group[0]!.id} batchId={batchId} records={group} editable={editable} />
      ))}
    </ul>
  );
}

function amountOf(r: SourceRecord): string {
  return (r.amount.display ?? formatMoney({ ...r.amount, display: undefined })).replace(/^[-−]/, "").replace(/(\.\d\d)0+(?=\D|$)/, "$1");
}

function Group({ batchId, records, editable }: { batchId: string; records: SourceRecord[]; editable: boolean }) {
  const toast = useToast();
  const t = records[0]!.match!.transaction;
  const ids = records.map((r) => r.id);
  const decide = useBookMutation(async (same: boolean, b) => api.post<{ decided: number }>(`/books/${b}/import-batches/${batchId}:decide-matches`, { same, record_ids: ids }));
  async function run(same: boolean) {
    try {
      await decide.mutateAsync(same);
      toast({ tone: "ok", text: same ? `已把 ${ids.length} 条关联到 ${t.number}` : `已把 ${ids.length} 条标为另一笔` });
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.detail : "操作失败：请稍后重试。" });
    }
  }
  return (
    <li className="grid gap-3 rounded-field border border-line px-4 py-3.5">
      <p className="text-sm">
        <span className="font-semibold text-warn-text">可能已记过</span>
        <span className="text-ink-2">
          {" · "}
          <Link to={`/transactions?tx=${t.number}`} className="num font-medium text-ink hover:underline">
            {t.number}
          </Link>
          {" · "}
          <span className="num">{shortDate(t.effective_date)}</span>
          {t.amount && <span className="num"> · {formatMoney(t.amount)}</span>} · {t.description}
        </span>
      </p>
      <ul className="grid gap-1 text-sm">
        {records.map((r) => (
          <li key={r.id} className="flex items-baseline gap-3">
            <span className="num w-24 shrink-0 text-ink-3">
              {shortDate(r.effective_date)} {clock(r.occurred_at)}
            </span>
            <span className="min-w-0 flex-1 truncate text-ink-2">{r.description || r.counterparty_text}</span>
            <span className="num shrink-0 font-medium">{amountOf(r)}</span>
          </li>
        ))}
      </ul>
      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="primary" loading={decide.isPending && decide.variables === true} onClick={() => run(true)}>
            是同一笔{records.length > 1 ? `（${records.length} 条）` : ""}
          </Button>
          <Button size="sm" loading={decide.isPending && decide.variables === false} onClick={() => run(false)}>
            不是，单独入账
          </Button>
        </div>
      )}
    </li>
  );
}
