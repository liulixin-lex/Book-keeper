/**
 * 记一笔 / 修改: one form for every business type, driven by the type's input schema. Every change is dry-run against
 * the API (debounced), so the fee and the amount received shown under the amount are the ledger's own numbers.
 * Saving takes effect at once; the toast that follows offers undo.
 */
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import gsap from "gsap";
import { CaretDown, Plus, Trash, WarningCircle } from "@phosphor-icons/react";
import { api, ApiError, type Envelope } from "@/api/client";
import {
  changeSetOf,
  useAccounts,
  useBook,
  useBookMutation,
  useBookQuery,
  useCan,
  useCategories,
  useChannels,
  useCommodities,
  useCounterparties,
  useDimensions,
  useNames,
  useTransactionTypes,
} from "@/api/queries";
import type { Account, Commodity, FeeRule, TransactionDetail, TransactionType } from "@/api/types";
import { useBookId } from "@/app/book";
import { Button, Chip, DateInput, Field, Input, Segmented, Select, SheetFooter, Skeleton, TimeInput, reducedMotion } from "@/components/ui";
import { addDays, bookDate, clock, formatMoney, parseAmount } from "@/lib/format";
import { fieldsFor, type FieldSpec } from "@/lib/schema";
import { buildPayload, draftFromDetail, fieldErrors, patchBody, type Draft, type LineDraft, type MoneyDraft } from "./payload";

export interface EntryPrefill {
  type?: string;
  counterparty?: string;
}

export interface EntryResult {
  txn: TransactionDetail;
  changeSet: string | null;
}

const SHORT: Record<string, string> = {
  sale: "销售",
  credit_purchase: "采购",
  expense: "费用",
  transfer: "划转",
  sale_refund: "销售退款",
  purchase_refund: "采购退款",
  opening_balance: "期初余额",
  manual_journal: "手工凭证",
};
const PRIMARY_TYPES = ["sale", "credit_purchase", "expense", "transfer"];
const MORE_TYPES = ["sale_refund", "purchase_refund", "opening_balance", "manual_journal"];
/** The amount that leads the form for each type; it carries over when the type changes. */
const HERO: Record<string, string> = { sale: "gross", sale_refund: "amount", credit_purchase: "total", expense: "amount", purchase_refund: "amount", transfer: "amount_out" };
const CHANNEL_TYPES = new Set(["sale", "credit_purchase", "expense", "sale_refund"]);
const NO_COUNTERPARTY = new Set(["transfer", "opening_balance", "manual_journal"]);

/** The channel used last time for each type, so a run of 链动 sales needs no extra click. */
const LAST_CHANNEL = "bk.lastChannel";
function lastChannel(type: string): string {
  try {
    return (JSON.parse(localStorage.getItem(LAST_CHANNEL) ?? "{}") as Record<string, string>)[type] ?? "";
  } catch {
    return "";
  }
}
function rememberChannel(type: string, code: string) {
  try {
    localStorage.setItem(LAST_CHANNEL, JSON.stringify({ ...(JSON.parse(localStorage.getItem(LAST_CHANNEL) ?? "{}") as Record<string, string>), [type]: code }));
  } catch {
    /* private mode */
  }
}

function emptyLine(side: LineDraft["side"], commodity: string): LineDraft {
  return { account: "", side, amount: "", commodity, memo: "" };
}

export function EntryForm({ prefill, editing, onDone }: { prefill?: EntryPrefill; editing?: TransactionDetail; onDone: (r: EntryResult) => void }) {
  const types = useTransactionTypes().data;
  const accounts = useAccounts().data;
  const commodities = useCommodities().data;
  const dims = useDimensions().data;
  const book = useBook().data;
  if (!types || !accounts || !commodities || !dims || !book) return <EntrySkeleton />;
  return <Form types={types} accounts={accounts} commodities={commodities} base={book.base_commodity} timezone={book.timezone} prefill={prefill} editing={editing} onDone={onDone} />;
}

interface FormProps {
  types: TransactionType[];
  accounts: Account[];
  commodities: Commodity[];
  base: string;
  timezone: string;
  prefill?: EntryPrefill;
  editing?: TransactionDetail;
  onDone: (r: EntryResult) => void;
}

function Form({ types, accounts, commodities, base, timezone, prefill, editing, onDone }: FormProps) {
  const bookId = useBookId();
  const names = useNames();
  const today = bookDate();

  const initial = useMemo<Draft>(() => {
    if (editing) {
      return draftFromDetail(editing, {
        accountCode: (id) => accounts.find((a) => a.id === id)?.code,
        channelCode: (id) => names.channel.get(id)?.code,
        scale: (c) => commodities.find((x) => x.code === c)?.scale ?? 2,
        clock: (at) => clock(at, timezone),
      });
    }
    const type = prefill?.type ?? "sale";
    const channel = CHANNEL_TYPES.has(type) ? lastChannel(type) : "";
    return {
      counterparty: prefill?.counterparty ?? "",
      date: today,
      time: "",
      values: channel ? { channel } : {},
      orderNo: "",
      description: "",
      notes: "",
      tags: "",
      lines: [emptyLine("debit", base), emptyLine("credit", base)],
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const [typeCode, setTypeCode] = useState(editing?.type ?? prefill?.type ?? "sale");
  const [draft, setDraft] = useState<Draft>(initial);
  const [more, setMore] = useState(false);
  const [moreTypes, setMoreTypes] = useState(MORE_TYPES.includes(typeCode));
  const [done, setDone] = useState(false);
  const formId = useId();
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const setValue = (key: string, v: string | MoneyDraft) => setDraft((d) => ({ ...d, values: { ...d.values, [key]: v } }));

  const type = types.find((t) => t.code === typeCode);
  const fields = useMemo(() => (type ? fieldsFor(type) : []), [type]);
  const isLines = type?.input_mode === "lines";
  const heroKey = HERO[typeCode];

  const payload = useMemo(() => buildPayload({ type, fields, timezone, ...draft }), [type, fields, timezone, draft]);
  const originalBody = useMemo(() => (editing ? buildPayload({ type, fields, timezone, ...initial }).body : null), [editing, type, fields, timezone, initial]);
  const patch = useMemo(() => (originalBody ? patchBody(originalBody, payload.body) : null), [originalBody, payload.body]);
  const unchanged = !!patch && Object.keys(patch).length === 0;

  const preview = useDryRun(
    bookId,
    editing
      ? patch && !unchanged
        ? { method: "patch", ref: editing.number, body: { expected_version: editing.version, ...patch } }
        : null
      : payload.ready
        ? { method: "post", body: payload.body }
        : null,
  );
  const shown = preview.data ?? (editing && unchanged ? editing : null);

  const save = useBookMutation(async (): Promise<Envelope<TransactionDetail>> => {
    if (editing) return api.patch<TransactionDetail>(`/books/${bookId}/transactions/${editing.number}`, { expected_version: editing.version, ...patch });
    return api.post<TransactionDetail>(`/books/${bookId}/transactions`, payload.body);
  });

  // The dry run checks every keystroke, but what is still missing only turns red once the owner tries to save:
  // the form never opens on an error it raised itself.
  const [attempted, setAttempted] = useState(false);
  const shownError = save.error ?? (attempted ? preview.error : null);
  const errors = fieldErrors(shownError);
  const submitError = shownError instanceof ApiError && (save.error || !Object.keys(errors).length) ? shownError : null;
  const canSave = payload.ready && !done && (!editing || !unchanged);

  async function submit() {
    if (!canSave) return;
    if (preview.error && !preview.loading) {
      setAttempted(true);
      return;
    }
    try {
      const res = await save.mutateAsync();
      if (!editing && CHANNEL_TYPES.has(typeCode) && typeof draft.values.channel === "string") rememberChannel(typeCode, draft.values.channel);
      setDone(true);
      setTimeout(() => onDone({ txn: res.data, changeSet: changeSetOf(res) }), reducedMotion() ? 0 : 560);
    } catch {
      /* shown inline */
    }
  }

  function chooseType(code: string) {
    if (code === typeCode) return;
    const from = HERO[typeCode];
    const to = HERO[code];
    if (from && to && from !== to && draft.values[from]) setDraft((d) => ({ ...d, values: { ...d.values, [to]: d.values[from]! } }));
    if (CHANNEL_TYPES.has(code)) setDraft((d) => ({ ...d, values: { ...d.values, channel: lastChannel(code) } }));
    setTypeCode(code);
  }

  const visible = fields.filter((f) => f.key !== heroKey && f.kind !== "channel" && !f.advanced);
  const advanced = fields.filter((f) => f.key !== heroKey && f.kind !== "channel" && f.advanced);

  return (
    <form
      id={formId}
      className="grid gap-6"
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          void submit();
        }
      }}
    >
      {!editing && (
        <div className="grid gap-2.5">
          <div role="radiogroup" aria-label="交易类型" className="flex flex-wrap gap-2">
            {PRIMARY_TYPES.filter((c) => types.some((t) => t.code === c && t.is_active)).map((c) => (
              <Chip key={c} on={typeCode === c} onClick={() => chooseType(c)} role="radio" aria-checked={typeCode === c} className="h-9 px-4 text-base">
                {SHORT[c]}
              </Chip>
            ))}
            <button
              type="button"
              aria-expanded={moreTypes}
              onClick={() => setMoreTypes((m) => !m)}
              className="inline-flex h-9 items-center gap-1 rounded-full px-3 text-sm font-medium text-ink-2 hover:bg-well hover:text-ink"
            >
              更多
              <CaretDown size={13} className={clsx("transition-transform duration-200", moreTypes && "rotate-180")} />
            </button>
          </div>
          {moreTypes && (
            <div className="flex flex-wrap gap-2">
              {MORE_TYPES.filter((c) => types.some((t) => t.code === c && t.is_active)).map((c) => (
                <Chip key={c} on={typeCode === c} onClick={() => chooseType(c)}>
                  {SHORT[c]}
                </Chip>
              ))}
            </div>
          )}
        </div>
      )}

      {!isLines && heroKey && (
        <HeroAmount
          label={fields.find((f) => f.key === heroKey)?.label ?? "金额"}
          value={(draft.values[heroKey] as MoneyDraft | undefined) ?? { amount: "", commodity: base }}
          onChange={(v) => setValue(heroKey, v)}
          commodities={commodities}
          error={errors[heroKey]}
          autoFocus={!editing}
        />
      )}

      {!isLines && <Split typeCode={typeCode} preview={shown} loading={preview.loading} blocked={!!preview.error} attempted={attempted} base={base} />}

      <div className="grid gap-5">
        {!NO_COUNTERPARTY.has(typeCode) && <CounterpartyField value={draft.counterparty} onChange={(v) => set({ counterparty: v })} error={errors.counterparty} />}

        {CHANNEL_TYPES.has(typeCode) && fields.some((f) => f.kind === "channel") && (
          <ChannelPicker value={String(draft.values.channel ?? "")} onChange={(v) => setValue("channel", v)} error={errors.channel} />
        )}

        {visible.map((f) => (
          <InputField key={f.key} spec={f} value={draft.values[f.key]} base={base} commodities={commodities} accounts={accounts} error={errors[f.key]} onChange={(v) => setValue(f.key, v)} />
        ))}

        {isLines && <LinesEditor lines={draft.lines} onChange={(lines) => set({ lines })} base={base} accounts={accounts} error={errors.lines} />}

        <DatePicker date={draft.date} today={today} onChange={(date) => set({ date })} error={errors.effective_date ?? errors.occurred_at} />

        <Field label="摘要" hint={draft.description || isLines ? undefined : "留空自动生成"} error={errors.description}>
          {(id, note) => (
            <Input
              id={id}
              value={draft.description}
              onChange={(e) => set({ description: e.target.value })}
              placeholder={shown?.description ?? (isLines ? "调整 · 原因" : "")}
              aria-describedby={note}
            />
          )}
        </Field>
      </div>

      <div className="grid gap-5">
        <button
          type="button"
          onClick={() => setMore((s) => !s)}
          className="-mx-1 flex items-center gap-1.5 justify-self-start rounded-full px-1 text-sm font-medium text-ink-2 hover:text-ink"
          aria-expanded={more}
        >
          <CaretDown size={13} className={clsx("transition-transform duration-200", more && "rotate-180")} />
          更多：订单号、时间、备注、标签{advanced.length > 0 && "、科目"}
        </button>
        {more && (
          <div className="grid grid-cols-2 gap-x-3 gap-y-5 max-sm:grid-cols-1">
            {!isLines && (
              <Field label="订单号" error={errors.order_no}>
                {(id) => <Input id={id} value={draft.orderNo} onChange={(e) => set({ orderNo: e.target.value })} placeholder="渠道或站点的订单号" />}
              </Field>
            )}
            <Field label="时间" hint="可选，24 小时制">
              {(id, note) => <TimeInput id={id} value={draft.time} onChange={(e) => set({ time: e.target.value })} aria-describedby={note} />}
            </Field>
            <Field label="备注" error={errors.notes} className="col-span-full">
              {(id) => <Input id={id} value={draft.notes} onChange={(e) => set({ notes: e.target.value })} />}
            </Field>
            <Field label="标签" hint="用逗号分隔，如 赠送, 待补票据" error={errors.tags} className="col-span-full">
              {(id, note) => <Input id={id} value={draft.tags} onChange={(e) => set({ tags: e.target.value })} aria-describedby={note} />}
            </Field>
            {advanced.map((f) => (
              <InputField key={f.key} spec={f} value={draft.values[f.key]} base={base} commodities={commodities} accounts={accounts} error={errors[f.key]} onChange={(v) => setValue(f.key, v)} />
            ))}
          </div>
        )}
      </div>

      <SheetFooter>
        <div className="grid gap-3">
          {submitError && (
            <p role="alert" className="flex items-start gap-2 text-sm text-neg">
              <WarningCircle size={16} weight="fill" className="mt-0.5 shrink-0" />
              {submitError.detail}
            </p>
          )}
          <SubmitButton form={formId} done={done} loading={save.isPending} disabled={!canSave} label={editing ? (unchanged ? "未修改" : "保存修改") : "记一笔"} />
        </div>
      </SheetFooter>
    </form>
  );
}

/** Lime submit capsule; after a successful write its label gives way to a check that draws itself. */
function SubmitButton({ form, done, loading, disabled, label }: { form: string; done: boolean; loading: boolean; disabled: boolean; label: string }) {
  const path = useRef<SVGPathElement>(null);
  useLayoutEffect(() => {
    const p = path.current;
    if (!done || !p) return;
    const len = p.getTotalLength();
    if (reducedMotion()) return;
    gsap.fromTo(p, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 0.42, ease: "power3.out" });
  }, [done]);
  return (
    <Button type="submit" form={form} variant="primary" size="lg" loading={loading} disabled={disabled && !done} className={clsx("w-full", done && "pointer-events-none")} aria-live="polite">
      {done ? (
        <svg viewBox="0 0 24 24" className="size-6" aria-label="已保存">
          <path ref={path} d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <>
          {label}
          <kbd className="ml-1 rounded-md bg-lime-ink/10 px-1.5 font-sans text-xs leading-5 font-semibold">⌘↵</kbd>
        </>
      )}
    </Button>
  );
}

function EntrySkeleton() {
  return (
    <div className="grid gap-5" role="status" aria-label="加载中">
      <div className="flex gap-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-9 w-16 rounded-full" />
        ))}
      </div>
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-2/3" />
    </div>
  );
}

/* ---------- the amount ---------- */

function HeroAmount({
  label,
  value,
  onChange,
  commodities,
  error,
  autoFocus,
}: {
  label: string;
  value: MoneyDraft;
  onChange: (v: MoneyDraft) => void;
  commodities: Commodity[];
  error?: string;
  autoFocus?: boolean;
}) {
  const id = "entry-hero-amount";
  return (
    <div className="grid min-w-0 gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-ink-2">
        {label}
      </label>
      <div
        className={clsx(
          "flex items-center gap-3 rounded-field border bg-card py-2 pr-2 pl-4 transition-[border-color,box-shadow] duration-150 focus-within:border-pos focus-within:shadow-[0_0_0_3px_var(--lime-wash)]",
          error ? "border-neg" : "border-line-strong",
        )}
      >
        <input
          id={id}
          inputMode="decimal"
          autoComplete="off"
          autoFocus={autoFocus}
          value={value.amount}
          onChange={(e) => onChange({ ...value, amount: e.target.value })}
          placeholder="0.00"
          aria-invalid={!!error}
          aria-describedby={error ? `${id}-err` : undefined}
          className="figure h-14 w-0 min-w-0 flex-1 bg-transparent text-3xl leading-none text-ink placeholder:text-ink-3/50 focus:outline-none"
        />
        <span className="relative shrink-0">
          <select
            aria-label="币种"
            value={value.commodity}
            onChange={(e) => onChange({ ...value, commodity: e.target.value })}
            className="h-10 appearance-none rounded-full bg-well pr-8 pl-4 text-base font-semibold text-ink transition-colors hover:bg-well-2 focus:outline-none focus-visible:outline-2"
          >
            {commodities
              .filter((c) => c.is_active)
              .map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
          </select>
          <CaretDown aria-hidden size={13} className="pointer-events-none absolute top-1/2 right-3.5 -translate-y-1/2 text-ink-2" />
        </span>
      </div>
      {error && (
        <p id={`${id}-err`} className="text-sm text-neg">
          {error}
        </p>
      )}
    </div>
  );
}

/** Fee and what actually arrives (or leaves), straight from the dry run. */
function Split({
  typeCode,
  preview,
  loading,
  blocked,
  attempted,
  base,
}: {
  typeCode: string;
  preview: TransactionDetail | null;
  loading: boolean;
  blocked: boolean;
  attempted: boolean;
  base: string;
}) {
  const seesRules = useCan("admin:read"); // fee rules are management info; without it the split shows without the rule name
  const rules = useBookQuery<FeeRule[]>("/fee-rules", undefined, { staleTime: 5 * 60_000, enabled: seesRules }).data?.data;
  const c = preview?.computed;
  const commodity = c?.commodity ?? "CNY";
  const m = (minor: number | undefined) => (minor === undefined ? null : formatMoney({ minor, commodity }));
  const items: { label: string; value: string | null; strong?: boolean }[] = [];
  if (c) {
    if (typeof c.fee === "number" && (c.fee !== 0 || typeCode === "sale" || typeCode === "credit_purchase")) items.push({ label: "手续费", value: m(c.fee) });
    if (typeCode === "sale" && typeof c.net === "number") items.push({ label: "到账", value: m(c.net), strong: true });
    if (typeCode === "credit_purchase") {
      if (typeof c.face === "number") items.push({ label: "面值", value: m(c.face as number) });
      if (typeof c.total === "number") items.push({ label: "实付", value: m(c.total), strong: true });
    }
    if (typeCode === "transfer" && typeof c.amount_in === "number") items.push({ label: "转入", value: m(c.amount_in as number), strong: true });
    // Foreign currency: what it comes to in the base currency, at the rate the ledger will use.
    const fx = (c.fx as { commodity: string; rate: string; rate_date?: string }[] | undefined)?.find((x) => x.commodity === commodity);
    if (fx && c.headline && commodity !== base) {
      items.push({ label: "折合", value: formatMoney({ minor: Math.round(Math.abs(c.headline.minor) * Number(fx.rate)), commodity: base }), strong: items.length === 0 });
      items.push({ label: "汇率", value: `${Number(fx.rate).toFixed(4)}${fx.rate_date ? `（${fx.rate_date.slice(5)}）` : ""}` });
    }
    if (items.length === 0 && typeof c.fee === "number") items.push({ label: "手续费", value: "无" });
  }
  const rule = c?.fee_rule as { code?: string } | undefined;
  const ruleName = rule?.code ? (rules?.find((r) => r.code === rule.code)?.name ?? rule.code) : null;
  const warnings = c?.warnings ?? [];

  return (
    <div aria-live="polite" className={clsx("-mt-2 min-h-12 rounded-field bg-well px-4 py-3 transition-opacity duration-200", loading && "opacity-60")}>
      {items.length === 0 ? (
        <p className="text-sm text-ink-3">
          {loading ? "正在计算…" : blocked && attempted ? "补全标红的信息后，这里显示手续费和实际到账" : blocked ? "信息填全后，这里显示手续费和实际到账" : "填好金额后，这里显示手续费和实际到账"}
        </p>
      ) : (
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          {items.map((i) => (
            <span key={i.label} className="flex items-baseline gap-2 text-sm">
              <span className="text-ink-2">{i.label}</span>
              <span className={clsx("num text-base", i.strong ? "font-semibold text-ink" : "text-ink")}>{i.value}</span>
            </span>
          ))}
          {ruleName && <span className="text-sm text-ink-3">按规则「{ruleName}」</span>}
        </div>
      )}
      {warnings.map((w) => (
        <p key={w.code} className="mt-1 text-sm text-warn-text">
          {w.message}
        </p>
      ))}
    </div>
  );
}

/* ---------- fields ---------- */

function CounterpartyField({ value, onChange, error }: { value: string; onChange: (v: string) => void; error?: string }) {
  const cps = useCounterparties().data ?? [];
  return (
    <Field label="往来方" hint="站点、服务商或平台；别名也能识别" error={error}>
      {(id, note) => (
        <>
          <Input
            id={id}
            list={`${id}-list`}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="如 relay-b.example、OpenAI、链动"
            aria-describedby={note}
            aria-invalid={!!error}
            autoComplete="off"
          />
          <datalist id={`${id}-list`}>
            {cps
              .filter((c) => c.is_active)
              .map((c) => (
                <option key={c.id} value={c.name} />
              ))}
          </datalist>
        </>
      )}
    </Field>
  );
}

function ChannelPicker({ value, onChange, error }: { value: string; onChange: (v: string) => void; error?: string }) {
  const channels = useChannels();
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-2 text-sm font-medium text-ink-2">渠道</legend>
      <div className="flex flex-wrap gap-2">
        <Chip on={!value} onClick={() => onChange("")} title="用往来方的默认渠道">
          自动
        </Chip>
        {channels.map((c) => (
          <Chip key={c.id} on={value === c.code} onClick={() => onChange(c.code)}>
            {c.name}
          </Chip>
        ))}
      </div>
      {error ? <p className="text-sm text-neg">{error}</p> : !value && <p className="text-sm text-ink-3">自动：用往来方的默认渠道</p>}
    </fieldset>
  );
}

function DatePicker({ date, today, onChange, error }: { date: string; today: string; onChange: (d: string) => void; error?: string }) {
  const yesterday = addDays(today, -1);
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-2 text-sm font-medium text-ink-2">日期</legend>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          label="快捷日期"
          value={date === today ? "today" : date === yesterday ? "yesterday" : ""}
          onChange={(v) => onChange(v === "today" ? today : yesterday)}
          options={[
            { value: "today", label: "今天" },
            { value: "yesterday", label: "昨天" },
          ]}
        />
        <DateInput aria-label="业务日期" value={date} onChange={(e) => onChange(e.target.value)} className="w-44" aria-invalid={!!error} />
      </div>
      {error && <p className="text-sm text-neg">{error}</p>}
    </fieldset>
  );
}

function InputField({
  spec,
  value,
  base,
  commodities,
  accounts,
  error,
  onChange,
}: {
  spec: FieldSpec;
  value: string | MoneyDraft | undefined;
  base: string;
  commodities: Commodity[];
  accounts: Account[];
  error?: string;
  onChange: (v: string | MoneyDraft) => void;
}) {
  const categories = useCategories();
  if (spec.kind === "money") {
    const m = (value as MoneyDraft | undefined) ?? { amount: "", commodity: base };
    return (
      <Field label={spec.label} hint={spec.hint} error={error} required={spec.required}>
        {(id, note) => (
          <div className="flex gap-2">
            <Input
              id={id}
              inputMode="decimal"
              value={m.amount}
              onChange={(e) => onChange({ ...m, amount: e.target.value })}
              aria-describedby={note}
              aria-invalid={!!error}
              className="num flex-1"
              placeholder="0.00"
            />
            <Select aria-label={`${spec.label}币种`} value={m.commodity} onChange={(e) => onChange({ ...m, commodity: e.target.value })} className="w-28 shrink-0">
              {commodities
                .filter((c) => c.is_active)
                .map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code}
                  </option>
                ))}
            </Select>
          </div>
        )}
      </Field>
    );
  }
  const v = (value as string | undefined) ?? "";
  let control: (id: string, note?: string) => ReactNode;
  if (spec.kind === "category")
    control = (id, note) => (
      <Select id={id} value={v} onChange={(e) => onChange(e.target.value)} aria-describedby={note} aria-invalid={!!error}>
        <option value="">选择收支分类</option>
        {categories.map((a) => (
          <option key={a.id} value={a.code}>
            {a.name}
          </option>
        ))}
      </Select>
    );
  else if (spec.kind === "account")
    control = (id, note) => (
      <Select id={id} value={v} onChange={(e) => onChange(e.target.value)} aria-describedby={note} aria-invalid={!!error}>
        <option value="">{spec.required ? "选择科目" : "账套默认"}</option>
        {accounts
          .filter((a) => !a.is_group && a.is_active)
          .map((a) => (
            <option key={a.id} value={a.code}>
              {a.code} {a.name}
            </option>
          ))}
      </Select>
    );
  else
    control = (id, note) => (
      <Input
        id={id}
        value={v}
        inputMode={spec.kind === "decimal" ? "decimal" : undefined}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={note}
        aria-invalid={!!error}
        className={spec.kind === "decimal" ? "num" : undefined}
      />
    );
  return (
    <Field label={spec.label} hint={spec.hint} error={error} required={spec.required}>
      {(id, note) => control(id, note)}
    </Field>
  );
}

function LinesEditor({ lines, onChange, base, accounts, error }: { lines: LineDraft[]; onChange: (l: LineDraft[]) => void; base: string; accounts: Account[]; error?: string }) {
  const postable = accounts.filter((a) => !a.is_group && a.is_active);
  const setLine = (i: number, patch: Partial<LineDraft>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const sum = (side: LineDraft["side"]) => lines.filter((l) => l.side === side).reduce((s, l) => s + Number(parseAmount(l.amount) ?? 0), 0);
  const diff = Math.round((sum("debit") - sum("credit")) * 100) / 100;
  return (
    <fieldset className="grid gap-3">
      <legend className="mb-2 text-sm font-medium text-ink-2">分录</legend>
      {lines.map((l, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto_112px_auto] items-center gap-2 max-sm:grid-cols-[minmax(0,1fr)_auto] max-sm:gap-y-2">
          <Select aria-label={`第 ${i + 1} 行科目`} value={l.account} onChange={(e) => setLine(i, { account: e.target.value })}>
            <option value="">选择科目</option>
            {postable.map((a) => (
              <option key={a.id} value={a.code}>
                {a.code} {a.name}
              </option>
            ))}
          </Select>
          <Segmented
            size="sm"
            label={`第 ${i + 1} 行方向`}
            value={l.side}
            onChange={(side) => setLine(i, { side })}
            options={[
              { value: "debit", label: "借" },
              { value: "credit", label: "贷" },
            ]}
          />
          <Input
            aria-label={`第 ${i + 1} 行金额`}
            inputMode="decimal"
            className="num"
            value={l.amount}
            onChange={(e) => setLine(i, { amount: e.target.value, commodity: l.commodity || base })}
            placeholder="0.00"
          />
          <button
            type="button"
            aria-label={`删除第 ${i + 1} 行`}
            onClick={() => onChange(lines.filter((_, j) => j !== i))}
            disabled={lines.length <= 2}
            className="grid size-9 place-items-center rounded-full text-ink-3 hover:bg-well hover:text-neg disabled:opacity-30"
          >
            <Trash size={16} />
          </button>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <Button size="sm" variant="ghost" icon={<Plus size={14} />} onClick={() => onChange([...lines, emptyLine(diff > 0 ? "credit" : "debit", base)])}>
          加一行
        </Button>
        <span className={clsx("num text-sm", diff === 0 ? "text-ink-3" : "text-neg")}>{diff === 0 ? "借贷平衡" : `借贷差 ${diff.toFixed(2)}`}</span>
      </div>
      {error && <p className="text-sm text-neg">{error}</p>}
    </fieldset>
  );
}

/* ---------- dry run ---------- */

interface DryRun {
  data: TransactionDetail | null;
  error: unknown;
  loading: boolean;
}

type DryRequest = { method: "post"; body: Record<string, unknown> } | { method: "patch"; ref: string; body: Record<string, unknown> };

function useDryRun(bookId: string, req: DryRequest | null): DryRun {
  const [state, setState] = useState<DryRun>({ data: null, error: null, loading: false });
  const key = req ? JSON.stringify(req) : null;
  const seq = useRef(0);
  useEffect(() => {
    if (!key) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const n = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    const timer = setTimeout(async () => {
      const r = JSON.parse(key) as DryRequest;
      try {
        const res =
          r.method === "post"
            ? await api.post<TransactionDetail>(`/books/${bookId}/transactions`, r.body, { dry_run: true })
            : await api.patch<TransactionDetail>(`/books/${bookId}/transactions/${r.ref}`, r.body, { dry_run: true });
        if (n === seq.current) setState({ data: res.data, error: null, loading: false });
      } catch (error) {
        if (n === seq.current) setState({ data: null, error, loading: false });
      }
    }, 320);
    return () => clearTimeout(timer);
  }, [bookId, key]);
  return state;
}
