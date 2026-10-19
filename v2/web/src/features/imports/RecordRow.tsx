/**
 * One statement line: what the file said, what the rules decided, and — when something is missing — the few fields
 * to fill in. A line that is already in the books says which transaction it backs; a line that may be says so and
 * asks one question: the same one, or not?
 */
import { useState } from "react";
import { Link } from "react-router";
import { clsx } from "clsx";
import { CaretDown, LinkSimple, Prohibit } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { useBookMutation, useCategories, useChannels, useCounterparties, useTransactionTypes } from "@/api/queries";
import type { RecordMatch, SourceRecord } from "@/api/types";
import { useBookId } from "@/app/book";
import { Button, Chip, Field, Input, Select } from "@/components/ui";
import { useToast } from "@/components/toast";
import { clock, formatMoney, shortDate } from "@/lib/format";

const MISSING_LABELS: Record<string, string> = {
  "inputs.category": "收支分类",
  "inputs.channel": "渠道",
  "inputs.face": "面值",
  "inputs.total": "实付",
  "inputs.from_account": "转出科目",
  "inputs.to_account": "转入科目",
  counterparty: "往来方",
  type: "交易类型",
};

export function RecordRow({ record: r, editable, committed = false }: { record: SourceRecord; editable: boolean; committed?: boolean }) {
  const types = useTransactionTypes().data ?? [];
  const [open, setOpen] = useState(false);
  const cls = r.classification;
  const typeName = types.find((t) => t.code === cls?.type)?.name;
  // The server's display knows each currency's scale (site credits keep 4 places); trim to cents for reading.
  const abs = (r.amount.display ?? formatMoney({ ...r.amount, display: undefined })).replace(/^[-−]/, "").replace(/(\.\d\d)0+(?=\D|$)/, "$1");
  const pending = r.match?.status === "pending";
  const actionable = editable && ["new", "classified"].includes(r.status) && !pending;
  const linked = editable && r.status === "matched" && !!r.match;
  const time = clock(r.occurred_at);

  return (
    <li className="py-1">
      <div className="flex items-center gap-4 py-2.5">
        <span className="num w-20 shrink-0 text-sm text-ink-2 max-sm:w-14">
          {shortDate(r.effective_date)}
          {time && <span className="block text-ink-3">{time}</span>}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{r.counterparty_text || r.description || "未写对方"}</p>
          <p className="mt-0.5 truncate text-sm">
            {r.error ? (
              <span className="text-neg">{r.error.detail}</span>
            ) : r.match && !pending ? (
              <span className="text-ink-2">
                已记过 ·{" "}
                <Link to={`/transactions?tx=${r.match.transaction.number}`} className="num font-medium text-ink hover:underline">
                  {r.match.transaction.number}
                </Link>
                <span className="text-ink-3"> · {r.match.method === "daily_total" ? "当天合计里的一笔" : r.match.transaction.description}</span>
              </span>
            ) : r.ignore_reason ? (
              <span className="text-ink-3">已忽略：{r.ignore_reason}</span>
            ) : cls?.type ? (
              <>
                <span className="text-ink-2">{typeName ?? cls.type}</span>
                {cls.counterparty && <span className="text-ink-3"> · {cls.counterparty}</span>}
                {r.fee_rule?.basis === "rule" && <span className="text-ink-3"> · 手续费按「{r.fee_rule.rule?.name}」</span>}
                {r.fee_rule?.basis === "none" && <span className="text-ink-3"> · 无手续费规则（按 0）</span>}
                {(cls.missing?.length ?? 0) > 0 && <span className="text-warn-text"> · 缺 {cls.missing!.map((m) => MISSING_LABELS[m] ?? m).join("、")}</span>}
              </>
            ) : (
              <span className="text-warn-text">未分类{r.description && r.counterparty_text ? <span className="text-ink-3"> · {r.description}</span> : null}</span>
            )}
          </p>
        </div>
        <span className={clsx("num shrink-0 font-semibold", r.direction === "in" ? "text-pos" : "text-ink")}>
          {r.direction === "in" ? "+" : r.direction === "out" ? "−" : ""}
          {abs}
        </span>
        {(actionable || linked) && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label={open ? "收起" : linked ? "这条对上的交易" : "补全这条记录"}
            className="grid size-8 shrink-0 place-items-center rounded-full text-ink-2 hover:bg-well hover:text-ink"
          >
            <CaretDown size={14} className={clsx("transition-transform duration-200", open && "rotate-180")} />
          </button>
        )}
      </div>
      {open && linked && <NotThisOne match={r.match!} />}
      {open && actionable && <ClassifyEditor record={r} committed={committed} onDone={() => setOpen(false)} />}
    </li>
  );
}

function useDecision(match: RecordMatch) {
  const bookId = useBookId();
  const same = useBookMutation(async () => api.post(`/books/${bookId}/match-suggestions/${match.suggestion_id}:accept`, {}));
  const other = useBookMutation(async () => api.post(`/books/${bookId}/match-suggestions/${match.suggestion_id}:reject`, {}));
  return { same, other };
}

/** An automatic match can be wrong: one quiet way to say so. */
function NotThisOne({ match }: { match: RecordMatch }) {
  const toast = useToast();
  const { other } = useDecision(match);
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-field border border-line px-4 py-3 text-sm sm:ml-24">
      <span className="text-ink-2">
        这条是{" "}
        <Link to={`/transactions?tx=${match.transaction.number}`} className="num font-medium text-ink hover:underline">
          {match.transaction.number}
        </Link>{" "}
        的凭证{match.method === "daily_total" ? "（当天合计里的一笔）" : ""}。
      </span>
      <Button
        size="sm"
        loading={other.isPending}
        onClick={async () => {
          try {
            await other.mutateAsync();
            toast({ tone: "ok", text: `已取消与 ${match.transaction.number} 的关联` });
          } catch (e) {
            toast({ tone: "error", text: e instanceof ApiError ? e.detail : "操作失败：请稍后重试。" });
          }
        }}
      >
        不是这笔
      </Button>
    </div>
  );
}

const TYPES_BY_DIRECTION: Record<string, string[]> = {
  out: ["expense", "credit_purchase", "transfer", "sale_refund"],
  in: ["sale", "purchase_refund", "transfer"],
  neutral: ["transfer", "expense", "sale"],
};
const CHANNEL_TYPES = ["sale", "credit_purchase", "expense", "sale_refund"];

function ClassifyEditor({ record: r, committed, onDone }: { record: SourceRecord; committed: boolean; onDone: () => void }) {
  const bookId = useBookId();
  const toast = useToast();
  const types = useTransactionTypes().data ?? [];
  const categories = useCategories();
  const channels = useChannels();
  const cps = useCounterparties().data ?? [];
  const cls = r.classification ?? {};
  const options = TYPES_BY_DIRECTION[r.direction] ?? TYPES_BY_DIRECTION.neutral!;
  const [type, setType] = useState(cls.type ?? options[0]!);
  const raw = (r.counterparty_text ?? "").trim();
  const known = (name: string) => cps.some((c) => c.name.toLowerCase() === name.toLowerCase());
  const [counterparty, setCounterparty] = useState(cls.counterparty ?? (raw && known(raw) ? raw : ""));
  const [category, setCategory] = useState(String((cls.inputs?.category as string | undefined) ?? ""));
  const [channel, setChannel] = useState(String((cls.inputs?.channel as string | undefined) ?? ""));
  const [txRef, setTxRef] = useState("");

  const classify = useBookMutation(async () => {
    const inputs: Record<string, unknown> = {};
    if (type === "expense" && category) inputs.category = category;
    if (CHANNEL_TYPES.includes(type) && channel) inputs.channel = channel;
    return api.patch(`/books/${bookId}/source-records/${r.id}`, { type, counterparty: counterparty.trim() || null, inputs });
  });
  const ignore = useBookMutation(async () => api.post(`/books/${bookId}/source-records:ignore`, { record_ids: [r.id], reason: "手动忽略" }));
  const link = useBookMutation(async () => api.post(`/books/${bookId}/source-records/${r.id}:link`, { transaction: txRef.trim() }));
  const createParty = useBookMutation(async () => api.post(`/books/${bookId}/counterparties`, { name: raw, category: type === "credit_purchase" ? "upstream_site" : "other" }));
  const error = [classify.error, ignore.error, link.error, createParty.error].find((e) => e instanceof ApiError) as ApiError | undefined;

  async function run(fn: () => Promise<unknown>, text: string) {
    try {
      await fn();
      toast({ tone: "ok", text });
      onDone();
    } catch {
      /* shown inline */
    }
  }

  return (
    <div className="mb-3 grid gap-4 rounded-field border border-line p-4 sm:ml-24">
      <div role="radiogroup" aria-label="交易类型" className="flex flex-wrap gap-2">
        {[...new Set([...options, ...(cls.type && !options.includes(cls.type) ? [cls.type] : [])])].map((code) => (
          <Chip key={code} role="radio" aria-checked={type === code} on={type === code} onClick={() => setType(code)}>
            {types.find((t) => t.code === code)?.name ?? code}
          </Chip>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="往来方" hint={raw && !known(raw) && !counterparty ? `账单上写的是「${raw}」` : undefined}>
          {(id, note) => (
            <>
              <Input id={id} aria-describedby={note} list={`${id}-cps`} value={counterparty} onChange={(e) => setCounterparty(e.target.value)} autoComplete="off" placeholder="可留空" />
              <datalist id={`${id}-cps`}>
                {cps.map((c) => (
                  <option key={c.id} value={c.name} />
                ))}
              </datalist>
            </>
          )}
        </Field>
        {type === "expense" && (
          <Field label="收支分类" required>
            {(id) => (
              <Select id={id} value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">选择分类</option>
                {categories.map((a) => (
                  <option key={a.id} value={a.code}>
                    {a.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        {CHANNEL_TYPES.includes(type) && (
          <Field label="渠道">
            {(id) => (
              <Select id={id} value={channel} onChange={(e) => setChannel(e.target.value)}>
                <option value="">按往来方默认</option>
                {channels.map((c) => (
                  <option key={c.id} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
      </div>
      {raw && !known(raw) && !counterparty && (
        <Button
          size="sm"
          className="justify-self-start"
          loading={createParty.isPending}
          onClick={async () => {
            try {
              await createParty.mutateAsync();
              setCounterparty(raw);
            } catch {
              /* inline */
            }
          }}
        >
          把「{raw}」加为往来方
        </Button>
      )}
      {error && <p className="text-sm text-neg">{error.detail}</p>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Input aria-label="已记过的交易号" placeholder="已记过？填交易号" value={txRef} onChange={(e) => setTxRef(e.target.value)} className="h-8 w-48 text-sm" />
          <Button size="sm" icon={<LinkSimple size={14} />} disabled={!txRef.trim()} loading={link.isPending} onClick={() => run(() => link.mutateAsync(), `已关联到 ${txRef.trim()}`)}>
            关联
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" icon={<Prohibit size={14} />} loading={ignore.isPending} onClick={() => run(() => ignore.mutateAsync(), "已忽略这条记录")}>
            忽略
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={type === "expense" && !category}
            loading={classify.isPending}
            onClick={() => run(() => classify.mutateAsync(), committed ? "已补全并入账" : "已补全，完成导入时入账")}
          >
            保存
          </Button>
        </div>
      </div>
    </div>
  );
}
