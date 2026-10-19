/**
 * Transaction detail sheet. Everything is direct: 摘要 and 备注 edit in place, 修改 opens the same form as 记一笔,
 * 删除 takes effect at once with an undo toast, and a deleted transaction offers 恢复. The ledger history below
 * shows every entry the transaction has had, so nothing an edit or delete did is hidden.
 */
import { useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { clsx } from "clsx";
import { ArrowCounterClockwise, PencilSimple, Trash } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { changeSetOf, useAccounts, useBookMutation, useLabel, useTransaction } from "@/api/queries";
import type { JournalEntry, TransactionDetail } from "@/api/types";
import { Flow, Money, TypeGlyph } from "@/components/money";
import { Badge, Button, ErrorNote, Row, Sheet, SheetFooter, Skeleton } from "@/components/ui";
import { useToast, useUndoToast } from "@/components/toast";
import { EntryForm } from "@/features/entry/EntryForm";
import { bookDate, clock, formatMoney, shortDate, weekday, type Money as MoneyValue } from "@/lib/format";
import { TYPE_SHORT } from "./TxnRow";

export function TxnSheet({ number, onClose }: { number: string | null; onClose: () => void }) {
  const [editing, setEditing] = useState(false);
  const detail = useTransaction(number);
  const last = useRef<TransactionDetail | null>(null);
  if (detail.data) last.current = detail.data;
  const t = number ? (detail.data ?? null) : last.current;
  const undoToast = useUndoToast();

  const close = () => {
    setEditing(false);
    onClose();
  };

  return (
    <Sheet
      open={!!number}
      onClose={close}
      label={t ? `${TYPE_SHORT[t.type] ?? t.type} ${t.number}` : "交易"}
      icon={t ? <TypeGlyph type={t.type} /> : undefined}
      title={editing ? "修改交易" : t ? (TYPE_SHORT[t.type] ?? t.type) : "交易"}
      subtitle={t && <span className="num">{t.number}</span>}
      width={500}
    >
      {detail.error && number ? (
        <ErrorNote error={detail.error} onRetry={() => detail.refetch()} />
      ) : !t ? (
        <DetailSkeleton />
      ) : editing ? (
        <EntryForm
          key={`${t.id}-${t.version}`}
          editing={t}
          onDone={({ txn, changeSet }) => {
            setEditing(false);
            undoToast(`已修改 ${txn.number}`, changeSet, `已改回 ${txn.number}`);
          }}
        />
      ) : (
        <Detail t={t} onEdit={() => setEditing(true)} onDeleted={close} />
      )}
    </Sheet>
  );
}

function Detail({ t, onEdit, onDeleted }: { t: TransactionDetail; onEdit: () => void; onDeleted: () => void }) {
  const label = useLabel();
  const toast = useToast();
  const undoToast = useUndoToast();
  const deleted = t.status === "reversed";
  const accounts = useAccounts().data;

  const remove = useBookMutation(async (_: void, b) => api.del<TransactionDetail>(`/books/${b}/transactions/${t.number}`, { expected_version: t.version }));
  const restore = useBookMutation(async (_: void, b) => api.post<TransactionDetail>(`/books/${b}/transactions/${t.number}:restore`, { expected_version: t.version }));
  const patch = useBookMutation(async (body: Record<string, unknown>, b) => api.patch<TransactionDetail>(`/books/${b}/transactions/${t.number}`, { expected_version: t.version, ...body }));

  async function run(fn: () => Promise<{ meta: Record<string, unknown> }>, text: string, undone: string, after?: () => void) {
    try {
      const res = await fn();
      undoToast(text, changeSetOf(res as never), undone);
      after?.();
    } catch (e) {
      toast({ tone: "error", text: e instanceof ApiError ? e.detail : "操作失败：网络或服务暂时不可用。请稍后重试。" });
    }
  }

  const time = clock(t.occurred_at);
  const category = typeof t.inputs.category === "string" ? (accounts?.find((a) => a.id === t.inputs.category || a.code === t.inputs.category)?.name ?? null) : null;
  return (
    <div className="grid gap-6">
      <div>
        <Flow type={t.type} value={t.amount} rolling muted={deleted} className="text-2xl" />
        <InlineText
          value={t.description}
          label="摘要"
          placeholder="留空恢复自动摘要"
          className="mt-1 text-md font-medium"
          disabled={deleted}
          onSave={(v) => run(() => patch.mutateAsync({ description: v }), "已更新摘要", "已改回摘要")}
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {deleted && <Badge>已删除</Badge>}
          {t.is_estimate && <Badge tone="warn">手续费为估算</Badge>}
          {t.created_channel !== "ui" && <Badge>{label("created_channel", t.created_channel)}写入</Badge>}
        </div>
      </div>

      {deleted && (
        <div className="flex items-center justify-between gap-4 rounded-field bg-well px-4 py-3">
          <p className="text-sm text-ink-2">已从列表和统计中移除{t.reverse_reason ? `：${t.reverse_reason}` : ""}。恢复后按删除前的分录重新入账。</p>
          <Button
            variant="primary"
            size="sm"
            icon={<ArrowCounterClockwise size={14} weight="bold" />}
            loading={restore.isPending}
            onClick={() => run(() => restore.mutateAsync(), `已恢复 ${t.number}`, `已重新删除 ${t.number}`)}
          >
            恢复
          </Button>
        </div>
      )}

      <Breakdown t={t} />

      <div className="divide-y divide-line">
        <Row label="日期">
          <span className="num">
            {t.effective_date.slice(0, 4)}年{shortDate(t.effective_date)} {weekday(t.effective_date)}
            {time && ` ${time}`}
          </span>
        </Row>
        {t.counterparty && <Row label="往来方">{t.counterparty.name}</Row>}
        {category && <Row label="收支分类">{category}</Row>}
        {t.channel && <Row label="渠道">{t.channel.name}</Row>}
        {typeof t.inputs.credit_quantity === "string" && (
          <Row label="额度数量">
            <span className="num">{Number(t.inputs.credit_quantity).toLocaleString("en-US")}</span>
          </Row>
        )}
        {t.order_no && (
          <Row label="订单号">
            <span className="num">{t.order_no}</span>
          </Row>
        )}
        {t.tags.length > 0 && <Row label="标签">{t.tags.join("、")}</Row>}
        <div className="flex min-h-12 items-start gap-4 py-3">
          <span className="shrink-0 pt-0.5 text-ink-2">备注</span>
          <InlineText
            value={t.notes ?? ""}
            label="备注"
            placeholder="添加备注"
            className="flex-1 text-right"
            disabled={deleted}
            onSave={(v) => run(() => patch.mutateAsync({ notes: v || null }), "已更新备注", "已改回备注")}
          />
        </div>
      </div>

      <History t={t} />

      <SheetFooter>
        <div className="flex gap-2">
          {!deleted ? (
            <>
              <Button className="flex-1" icon={<PencilSimple size={16} />} onClick={onEdit}>
                修改
              </Button>
              <Button
                variant="danger"
                className="flex-1"
                icon={<Trash size={16} />}
                loading={remove.isPending}
                onClick={() => run(() => remove.mutateAsync(), `已删除 ${t.number}`, `已恢复 ${t.number}`, onDeleted)}
              >
                删除
              </Button>
            </>
          ) : (
            <p className="flex-1 text-center text-sm text-ink-3">已删除的交易不能修改，恢复后再改</p>
          )}
        </div>
      </SheetFooter>
    </div>
  );
}

/** What the amount is made of, from the transaction's computed figures. */
function Breakdown({ t }: { t: TransactionDetail }) {
  const c = t.computed;
  const commodity = c.commodity ?? t.amount?.commodity ?? "CNY";
  const m = (v: unknown) => (typeof v === "number" ? formatMoney({ minor: v, commodity }) : null);
  const rows: [string, string | null, boolean?][] =
    t.type === "sale"
      ? [
          ["毛额", m(c.gross)],
          ["手续费", m(c.fee)],
          ["到账", m(c.net), true],
        ]
      : t.type === "credit_purchase"
        ? [
            ["面值", m(c.face)],
            ["手续费", m(c.fee)],
            ["实付", m(c.total), true],
          ]
        : t.type === "transfer"
          ? [
              ["转出", m(c.amount_out)],
              ["手续费", m(c.fee)],
              ["转入", m(c.amount_in), true],
            ]
          : typeof c.fee === "number" && c.fee !== 0
            ? [
                ["金额", m(c.amount)],
                ["手续费", m(c.fee)],
              ]
            : [];
  const shown = rows.filter(([, v]) => v !== null);
  if (!shown.length) return null;
  const f = t.fee_rule;
  const rate = f?.rule?.rate ? ` ${(Number(f.rule.rate) * 100).toFixed(2).replace(/\.?0+$/, "")}%` : "";
  return (
    <div className="grid gap-2 rounded-field bg-well px-4 py-3.5">
      <dl className="grid grid-cols-3 gap-3">
        {shown.map(([k, v, strong]) => (
          <div key={k}>
            <dt className="text-sm text-ink-2">{k}</dt>
            <dd className={clsx("num mt-0.5", strong ? "font-semibold" : "")}>{v}</dd>
          </div>
        ))}
      </dl>
      {f && (
        <p className="text-sm text-ink-3">
          {f.basis === "rule" ? (
            <>
              手续费按规则「
              <Link to="/settings/fee-rules" className="font-medium text-ink-2 hover:underline">
                {f.rule?.name}
              </Link>
              」{rate}
            </>
          ) : f.basis === "none" ? (
            "没有匹配的手续费规则，手续费按 0"
          ) : (
            "手续费按实际填写"
          )}
        </p>
      )}
    </div>
  );
}

const FIRST: Record<string, string> = { ui: "记一笔", import: "从账单导入", mcp: "AI 通过 MCP 记录", api: "通过 API 记录", migration: "从旧账迁移", cli: "命令行记录", system: "系统记录" };

/**
 * The transaction's history in plain words, read from its ledger entries: recorded, changed, deleted, restored.
 * An edit is a reversal plus a new posting in the ledger; here it is one “修改” with the amount it changed to.
 */
function History({ t }: { t: TransactionDetail }) {
  const entries = [...t.entries].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
  const commodity = t.amount?.commodity;
  const size = (e: JournalEntry): MoneyValue | null => {
    const minor = e.lines.filter((l) => l.commodity === commodity && l.amount.minor > 0).reduce((n, l) => n + l.amount.minor, 0);
    return commodity && minor ? { minor, commodity } : null;
  };
  const events: { id: string; what: string; at: string; amount: MoneyValue | null }[] = [];
  entries.forEach((e, i) => {
    if (e.kind === "repost_reversal") return;
    const what = e.kind === "repost" ? "修改" : e.kind === "reversal" ? "删除" : e.kind === "adjustment" ? "调整" : i === 0 ? (FIRST[t.created_channel] ?? "记录") : "恢复";
    events.push({ id: e.id, what, at: e.recorded_at, amount: e.kind === "reversal" ? null : size(e) });
  });
  return (
    <section aria-labelledby="history-title">
      <h3 id="history-title" className="font-semibold">
        历史
      </h3>
      <ol className="mt-3 grid">
        {events.map((ev, i) => (
          <li key={ev.id} className="relative flex items-baseline gap-3 pb-3 pl-5 last:pb-0">
            <span aria-hidden className={clsx("absolute top-1.5 left-0 size-2 rounded-full", i === events.length - 1 ? "bg-pos" : "bg-line-strong")} />
            {i < events.length - 1 && <span aria-hidden className="absolute top-4 bottom-0 left-[3.5px] w-px bg-line" />}
            <span className="font-medium">{ev.what}</span>
            <span className="num text-sm text-ink-3">
              {shortDate(bookDate(new Date(ev.at)))} {clock(ev.at)}
            </span>
            {ev.amount && <Money value={ev.amount} className="ml-auto text-sm text-ink-2" />}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Click to edit; Enter or leaving the field saves, Esc cancels. */
function InlineText({
  value,
  label,
  placeholder,
  className,
  disabled,
  onSave,
}: {
  value: string;
  label: string;
  placeholder: string;
  className?: string;
  disabled?: boolean;
  onSave: (v: string) => Promise<void> | void;
}): ReactNode {
  const [draft, setDraft] = useState<string | null>(null);
  if (draft === null)
    return (
      <button
        type="button"
        disabled={disabled}
        onClick={() => setDraft(value)}
        title={disabled ? undefined : `点按修改${label}`}
        className={clsx("-mx-1.5 block max-w-full rounded-lg px-1.5 text-left transition-colors duration-150 enabled:hover:bg-well disabled:cursor-default", !value && "text-ink-3", className)}
      >
        <span className="sr-only">修改{label}：</span>
        {value || (disabled ? "—" : placeholder)}
      </button>
    );
  const commit = async () => {
    const v = draft.trim();
    setDraft(null);
    if (v !== value) await onSave(v);
  };
  return (
    <input
      autoFocus
      aria-label={label}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") void commit();
        if (e.key === "Escape") {
          e.stopPropagation();
          e.preventDefault();
          setDraft(null);
        }
      }}
      className={clsx("-mx-1.5 block w-[calc(100%+0.75rem)] rounded-lg bg-well px-1.5 focus:shadow-[0_0_0_3px_var(--lime-wash)] focus:outline-none", className)}
    />
  );
}

function DetailSkeleton() {
  return (
    <div className="grid gap-5" role="status" aria-label="加载中">
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-5 w-64" />
      <Skeleton className="h-16 w-full" />
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-6 w-full" />
      ))}
    </div>
  );
}
