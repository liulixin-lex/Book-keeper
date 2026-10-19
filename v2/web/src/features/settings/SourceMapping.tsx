/**
 * Column mapping for table sources, tried live on a sample file: pick a file, say which column is what, and see the
 * records it would read before saving. Two shapes: one row per record, or a daily sheet with one column per channel
 * (日期, 链动, 云猫, stripe…).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { FileArrowUp } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { useChannels } from "@/api/queries";
import { useBookId } from "@/app/book";
import { Button, Field, Input, Segmented, Select, Switch } from "@/components/ui";

type Config = Record<string, unknown>;

interface Preview {
  rows: string[][];
  records: { row_no: number; occurred_at: string; direction: string; amount: string; commodity: string; fee: string | null; counterparty: string | null; description: string | null }[];
  errors: { row_no: number; message: string }[];
  skipped: number;
  total: number;
  error: string | null;
}

const ROLES: [string, string][] = [
  ["datetime", "时间"],
  ["date", "日期"],
  ["amount", "金额"],
  ["income", "收入金额"],
  ["expense", "支出金额"],
  ["direction", "收/支"],
  ["counterparty", "对方"],
  ["description", "说明"],
  ["order_no", "订单号"],
  ["external_id", "流水号"],
  ["fee", "手续费"],
  ["commodity", "币种"],
  ["status", "状态"],
];
const CURRENCIES = ["CNY", "USD", "GBP", "UCR"];

/** The row most likely to be the header: the one with the most filled cells among the first rows. */
function headerOf(rows: string[][]): string[] {
  let best: string[] = [];
  for (const r of rows.slice(0, 15)) if (r.filter(Boolean).length > best.filter(Boolean).length) best = r;
  return best.filter(Boolean);
}

export function SourceMapping({ kind, config, onChange }: { kind: string; config: Config; onChange: (next: Config) => void }) {
  const bookId = useBookId();
  const channels = useChannels();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const wide = (config.wide ?? null) as { date?: string; direction?: string; columns?: Record<string, { channel?: string; commodity?: string; fee?: string }> } | null;
  const columns = (config.columns ?? {}) as Record<string, string>;
  const auto = kind === "card_shop_orders" && !config.columns;
  const header = useMemo(() => headerOf(preview?.rows ?? []), [preview]);
  const key = JSON.stringify(config);

  useEffect(() => {
    if (!file) return;
    const id = setTimeout(async () => {
      const form = new FormData();
      form.set("kind", kind);
      form.set("config", key);
      form.set("file", file);
      try {
        setPreview((await api.upload<Preview>(`/books/${bookId}/import-sources:preview`, form)).data);
        setFailed(null);
      } catch (e) {
        setFailed(e instanceof ApiError ? e.detail : "预览失败：请稍后重试。");
      }
    }, 350);
    return () => clearTimeout(id);
  }, [file, key, kind, bookId]);

  const set = (patch: Config) => onChange(Object.fromEntries(Object.entries({ ...config, ...patch }).filter(([, v]) => v !== undefined)));
  const setColumn = (role: string, name: string) => {
    const next = { ...columns };
    if (name) next[role] = name;
    else delete next[role];
    set({ columns: next });
  };
  const directionValues = (config.direction_values ?? {}) as Record<string, string>;
  const inWord = Object.entries(directionValues).find(([, v]) => v === "in")?.[0] ?? "收入";
  const outWord = Object.entries(directionValues).find(([, v]) => v === "out")?.[0] ?? "支出";
  const options = [...new Set([...header, ...Object.values(columns), wide?.date ?? "", ...Object.keys(wide?.columns ?? {})].filter(Boolean))];

  return (
    <fieldset className="grid gap-4 rounded-field border border-line p-4">
      <legend className="px-1 text-sm font-semibold">列对应</legend>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" icon={<FileArrowUp size={14} />} onClick={() => input.current?.click()}>
          {file ? "换一个样例文件" : "选一个样例文件"}
        </Button>
        <span className="min-w-0 truncate text-sm text-ink-3">{file ? file.name : "用一份真实账单试，边改边看读出来的记录"}</span>
        <input ref={input} type="file" accept=".csv,.xlsx,.xls,.json,.txt" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </div>

      {kind === "generic_tabular" && (
        <Segmented
          size="sm"
          label="表格形状"
          value={wide ? "wide" : "long"}
          onChange={(v) => (v === "wide" ? set({ wide: { date: header[0] ?? "日期", direction: "in", columns: {} }, columns: undefined }) : set({ wide: undefined }))}
          options={[
            { value: "long", label: "一行一笔" },
            { value: "wide", label: "每天一行，每列一个渠道" },
          ]}
        />
      )}
      {kind === "card_shop_orders" && (
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-ink-2">自动识别列（订单号、商品、实付金额、时间、状态）</span>
          <Switch label="自动识别列" checked={auto} onChange={(on) => set({ columns: on ? undefined : {} })} />
        </div>
      )}

      {wide ? (
        <div className="grid gap-3">
          <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
            <Field label="日期列">
              {(id) => (
                <Select id={id} value={wide.date ?? ""} onChange={(e) => set({ wide: { ...wide, date: e.target.value } })}>
                  {options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="这些钱是">
              {(id) => (
                <Select id={id} value={wide.direction ?? "in"} onChange={(e) => set({ wide: { ...wide, direction: e.target.value } })}>
                  <option value="in">收入</option>
                  <option value="out">支出</option>
                </Select>
              )}
            </Field>
          </div>
          <ul className="grid gap-2">
            {options
              .filter((o) => o !== wide.date && !Object.values(wide.columns ?? {}).some((c) => c.fee === o))
              .map((name) => {
                const col = wide.columns?.[name];
                const setCol = (patch: { channel?: string; commodity?: string; fee?: string } | null) => {
                  const next = { ...(wide.columns ?? {}) };
                  if (patch === null) delete next[name];
                  else next[name] = Object.fromEntries(Object.entries({ ...col, ...patch }).filter(([, v]) => v)) as typeof patch;
                  set({ wide: { ...wide, columns: next } });
                };
                return (
                  <li key={name} className="grid grid-cols-[minmax(0,1fr)_repeat(3,minmax(0,1fr))] items-center gap-2 max-sm:grid-cols-2">
                    <span className="truncate text-sm font-medium">{name}</span>
                    <Select aria-label={`${name} 记到哪个渠道`} value={col?.channel ?? ""} onChange={(e) => (e.target.value ? setCol({ channel: e.target.value }) : setCol(null))}>
                      <option value="">不导入</option>
                      {channels.map((c) => (
                        <option key={c.id} value={c.code}>
                          {c.name}
                        </option>
                      ))}
                    </Select>
                    <Select aria-label={`${name} 的币种`} value={col?.commodity ?? "CNY"} disabled={!col} onChange={(e) => setCol({ commodity: e.target.value === "CNY" ? "" : e.target.value })}>
                      {CURRENCIES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </Select>
                    <Select aria-label={`${name} 的手续费列`} value={col?.fee ?? ""} disabled={!col} onChange={(e) => setCol({ fee: e.target.value })}>
                      <option value="">无手续费列</option>
                      {options
                        .filter((o) => o !== name && o !== wide.date)
                        .map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                    </Select>
                  </li>
                );
              })}
          </ul>
        </div>
      ) : (
        !auto && (
          <div className="grid gap-3">
            <div className="grid grid-cols-2 gap-2 max-sm:grid-cols-1">
              {ROLES.map(([role, label]) => (
                <label key={role} className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-2 text-sm">
                  <span className="text-ink-2">{label}</span>
                  <Select value={columns[role] ?? ""} onChange={(e) => setColumn(role, e.target.value)}>
                    <option value="">不用</option>
                    {options.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </Select>
                </label>
              ))}
            </div>
            {columns.direction ? (
              <div className="grid grid-cols-2 gap-3">
                <Field label="收入写作">{(id) => <Input id={id} value={inWord} onChange={(e) => set({ direction_values: { [e.target.value]: "in", [outWord]: "out" } })} />}</Field>
                <Field label="支出写作">{(id) => <Input id={id} value={outWord} onChange={(e) => set({ direction_values: { [inWord]: "in", [e.target.value]: "out" } })} />}</Field>
              </div>
            ) : (
              !columns.income &&
              !columns.expense && (
                <Segmented
                  size="sm"
                  label="没有收/支列时"
                  value={config.signed ? "signed" : String(config.default_direction ?? "out")}
                  onChange={(v) => set(v === "signed" ? { signed: true, default_direction: undefined } : { signed: undefined, default_direction: v })}
                  options={[
                    { value: "out", label: "都是支出" },
                    { value: "in", label: "都是收入" },
                    { value: "signed", label: "看正负号" },
                  ]}
                />
              )
            )}
            <Field label="没有币种列时按">
              {(id) => (
                <Select id={id} value={String(config.default_commodity ?? "CNY")} onChange={(e) => set({ default_commodity: e.target.value === "CNY" ? undefined : e.target.value })}>
                  {CURRENCIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
        )
      )}

      {file && (failed || preview) && (
        <div className="grid gap-2 rounded-field bg-well px-4 py-3 text-sm" aria-live="polite">
          {failed || preview?.error ? (
            <p className="text-neg">{failed ?? preview?.error}</p>
          ) : (
            <p className="font-medium">
              读到 <span className="num">{preview!.total}</span> 条{preview!.skipped > 0 && <span className="text-ink-3">，按状态跳过 {preview!.skipped} 行</span>}
              {preview!.errors.length > 0 && <span className="text-neg">，{preview!.errors.length} 行读不了</span>}
            </p>
          )}
          {preview?.records.slice(0, 5).map((r, i) => (
            <p key={`${r.row_no}-${i}`} className="num flex gap-3 truncate text-ink-2">
              <span className="shrink-0">{r.occurred_at.slice(0, 16).replace("T", " ")}</span>
              <span className={r.direction === "in" ? "shrink-0 text-pos" : "shrink-0"}>
                {r.direction === "in" ? "+" : "−"}
                {r.amount} {r.commodity}
              </span>
              <span className="truncate text-ink-3">{r.counterparty || r.description}</span>
            </p>
          ))}
          {preview?.errors.slice(0, 3).map((e, i) => (
            <p key={`${e.row_no}-${i}`} className="num text-neg">
              第 {e.row_no} 行：{e.message}
            </p>
          ))}
        </div>
      )}
    </fieldset>
  );
}
