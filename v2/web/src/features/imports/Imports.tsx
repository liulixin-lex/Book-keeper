/**
 * 导入: choose a source, drop the statement, finish the lines the rules could not classify, then 完成导入 books
 * everything at once. The toast offers undo; a finished import can also be taken back as a whole.
 */
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Link, Route, Routes, useNavigate, useParams } from "react-router";
import { clsx } from "clsx";
import { ArrowLeft, CheckCircle, FileArrowUp, Lightning, Sparkle, Tray, WarningCircle, XCircle } from "@phosphor-icons/react";
import { api, ApiError } from "@/api/client";
import { changeSetOf, useBatchRecords, useBookMutation, useBookQuery, useCapabilities, useImportBacklog, useLabel } from "@/api/queries";
import type { Batch, ImportSource, SourceRecord } from "@/api/types";
import { useBookId } from "@/app/book";
import { Badge, Button, Card, CardHeader, Chip, Empty, ErrorNote, Input, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { useToast, useUndoToast } from "@/components/toast";
import { shortDate } from "@/lib/format";
import { RecordRow } from "./RecordRow";
import { ReviewGroups } from "./ReviewGroups";

export const KIND_NAMES: Record<string, string> = {
  wechat_bill: "微信账单",
  alipay_bill: "支付宝账单",
  stripe_balance: "Stripe 余额明细",
  card_shop_orders: "卡网订单",
  upstream_usage_log: "上游兑换记录（表格）",
  redeem_page: "兑换码页面（PDF）",
  ai_extract: "AI 识别（截图与 PDF）",
  generic_tabular: "通用表格",
  records: "结构化记录",
};

/** What each kind of source reads, for the file picker and the drop zone. */
const KIND_FILES: Record<string, { accept: string; hint: string; multiple?: boolean }> = {
  redeem_page: {
    accept: ".pdf,application/pdf",
    hint: "在浏览器里把兑换码页面打印成 PDF，可一次选多个",
    multiple: true,
  },
  ai_extract: {
    accept: "image/png,image/jpeg,image/webp,.pdf,application/pdf",
    hint: "截图或 PDF，可一次选多个；由 AI 读取，稍等片刻",
    multiple: true,
  },
};
/** One upload request, all files together (nginx allows 30 MB per request; the server 25 MB per file). */
const UPLOAD_LIMIT = 25 * 1024 * 1024;
/**
 * Screenshots go at their own resolution up to the model's 2576px long edge: scaling down blurs the digits it has to
 * read, and a misread amount costs far more than the read. Only larger ones are scaled to that edge; a file still
 * over the API's size for one image is re-encoded as JPEG at the same size.
 */
const AI_LONG_EDGE = 2576;
const AI_MAX_BYTES = 3.5 * 1024 * 1024;

async function shrink(file: File): Promise<File> {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) return file;
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, AI_LONG_EDGE / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size <= AI_MAX_BYTES) {
    bitmap.close();
    return file;
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const encode = (type: string) => new Promise<Blob | null>((done) => canvas.toBlob(done, type, 0.92));
  let type = file.type === "image/jpeg" ? "image/jpeg" : "image/png";
  let blob = await encode(type);
  if (blob && blob.size > AI_MAX_BYTES && type === "image/png") {
    type = "image/jpeg";
    blob = await encode(type);
  }
  return blob ? new File([blob], file.name.replace(/\.\w+$/, type === "image/png" ? ".png" : ".jpg"), { type }) : file;
}

const TABLE_FILES: { accept: string; hint: string; multiple?: boolean } = {
  accept: ".csv,.xlsx,.xls,.json,.txt",
  hint: "CSV、XLSX 或 JSON，最大 25 MB",
};

const STATUS_TONE: Record<Batch["status"], "warn" | "pos" | "neutral" | "neg"> = {
  extracting: "neutral",
  failed: "neg",
  parsed: "warn",
  committed: "pos",
  reverted: "neutral",
};
/** Poll while an AI read is running on the server. */
const whileReading = (busy: boolean) => (busy ? 3000 : false);

export default function Imports() {
  return (
    <Routes>
      <Route index element={<Home />} />
      <Route path=":batchId" element={<BatchView />} />
    </Routes>
  );
}

function sourceName(b: Batch, sources: ImportSource[]): string {
  if (typeof b.source !== "string") return b.source.name;
  return sources.find((s) => s.id === b.source)?.name ?? "导入";
}

function Home() {
  const label = useLabel();
  const batches = useBookQuery<Batch[]>(
    "/import-batches",
    { limit: 30 },
    {
      refetchInterval: (d) => whileReading(!!d?.data.some((b) => b.status === "extracting")),
    },
  );
  const sources = useBookQuery<ImportSource[]>("/import-sources");
  // A batch that holds no records (an empty migration placeholder) says nothing; leave it out.
  const list = (batches.data?.data ?? []).filter((b) => (b.summary.records ?? 0) > 0 || (b.open_records ?? 0) > 0 || b.status === "extracting" || b.status === "failed");
  const srcs = sources.data?.data ?? [];
  const backlog = useImportBacklog();

  return (
    <>
      <PageHeader title="导入" />
      <div className="grid gap-5 lg:grid-cols-12">
        <Upload sources={srcs} loading={!sources.data} />
        <Card className="p-6 lg:col-span-7 max-sm:p-5" aria-labelledby="batches-title">
          <CardHeader
            id="batches-title"
            title="最近导入"
            action={
              backlog.count > 0 && (
                <Link
                  to={backlog.first ? `/imports/${backlog.first}` : "/imports"}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full bg-warn-wash px-3.5 text-sm font-semibold text-warn-text transition-colors duration-150 hover:bg-warn/25"
                >
                  <span className="num">{backlog.count}</span> 条待入账
                </Link>
              )
            }
          />
          <div className="mt-2">
            {batches.error ? (
              <ErrorNote error={batches.error} onRetry={() => batches.refetch()} />
            ) : !batches.data ? (
              <div className="grid gap-4 py-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : list.length === 0 ? (
              <Empty icon={<Tray size={22} />} title="还没有导入过账单">
                选一个来源，把账单文件拖进左边。解析后先在这里补全，完成导入时才写入账本。
              </Empty>
            ) : (
              <ul>
                {list.map((b) => {
                  const open = b.open_records ?? 0;
                  return (
                    <li key={b.id}>
                      <Link to={`/imports/${b.id}`} className="-mx-3 flex items-center gap-3.5 rounded-field px-3 py-3 transition-colors duration-150 hover:bg-well">
                        <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-full bg-well text-ink-2">
                          <FileArrowUp size={19} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate font-medium">{sourceName(b, srcs)}</span>
                            <Badge tone={STATUS_TONE[b.status]}>{label("import_batch_status", b.status)}</Badge>
                          </span>
                          <span className="num mt-0.5 block truncate text-sm text-ink-3">
                            {b.created_at.slice(0, 10)} 导入
                            {b.summary.period && ` · 账单 ${shortDate(b.summary.period[0])} – ${shortDate(b.summary.period[1])}`}
                            {b.note && ` · ${b.note}`}
                          </span>
                        </span>
                        <span className="num shrink-0 text-right text-sm text-ink-2">
                          {b.status === "extracting" ? "读取中…" : b.status === "failed" ? <span className="text-neg">没读成</span> : `${b.summary.records ?? 0} 条`}
                          {open > 0 && <span className="block text-warn-text">{open} 条待入账</span>}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}

function Upload({ sources, loading }: { sources: ImportSource[]; loading: boolean }) {
  const bookId = useBookId();
  const navigate = useNavigate();
  const capabilities = useCapabilities();
  const [source, setSource] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [note, setNote] = useState("");
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const active = sources.filter((s) => s.is_active && s.kind !== "records");
  const chosen = source || active[0]?.code || "";
  const kind = active.find((s) => s.code === chosen)?.kind ?? "";
  const reads = KIND_FILES[kind] ?? TABLE_FILES;
  const ai = kind === "ai_extract";
  const aiOff = ai && capabilities.data?.features.ai_extract === false;

  // One key per selection: pressing the button again after a lost answer is the same upload, answered once.
  const attempt = useMemo(() => crypto.randomUUID(), [files, chosen, note]);
  const upload = useBookMutation(async () => {
    const form = new FormData();
    form.set("source", chosen);
    const sending = ai ? await Promise.all(files.map(shrink)) : files;
    if (sending.reduce((n, f) => n + f.size, 0) > UPLOAD_LIMIT)
      throw new ApiError(413, {
        detail: "这些文件合计超过 25 MB，请分几次上传。",
      });
    for (const f of sending) form.append("file", f);
    if (note.trim()) form.set("note", note.trim());
    return (await api.upload<Batch>(`/books/${bookId}/import-batches:upload`, form, attempt)).data;
  });

  function pick(list: FileList | null) {
    const all = [...(list ?? [])];
    setFiles(reads.multiple ? all : all.slice(0, 1));
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    pick(e.dataTransfer.files);
  }

  return (
    <Card className="self-start p-6 lg:col-span-5 max-sm:p-5" aria-labelledby="upload-title">
      <CardHeader
        id="upload-title"
        title="上传账单"
        action={
          <Link to="/settings/sources" className="text-sm font-medium text-ink-2 hover:text-ink">
            管理来源
          </Link>
        }
      />
      {loading ? (
        <Skeleton className="mt-4 h-48 w-full" />
      ) : active.length === 0 ? (
        <Empty
          title="先建一个来源"
          action={
            <Link to="/settings/sources" className="font-semibold text-pos hover:underline">
              去创建来源
            </Link>
          }
        >
          来源决定怎么读文件（微信、支付宝、Stripe、卡网订单、兑换码页面、AI 识别截图…）以及默认记成什么交易。
        </Empty>
      ) : (
        <div className="mt-4 grid gap-4">
          <div role="radiogroup" aria-label="来源" className="flex flex-wrap gap-2">
            {active.map((s) => (
              <Chip
                key={s.id}
                role="radio"
                aria-checked={chosen === s.code}
                on={chosen === s.code}
                onClick={() => {
                  setSource(s.code);
                  setFiles([]);
                }}
                title={KIND_NAMES[s.kind] ?? s.kind}
              >
                {s.name}
              </Chip>
            ))}
          </div>
          <button
            type="button"
            onClick={() => input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={onDrop}
            disabled={aiOff}
            className={clsx(
              "grid justify-items-center gap-2 rounded-card border-2 border-dashed px-4 py-9 text-center transition-colors duration-150 disabled:opacity-60",
              over ? "border-pos bg-lime-wash" : files.length ? "border-line-strong bg-well" : "border-line-strong hover:bg-well",
            )}
          >
            <span aria-hidden className={clsx("grid size-12 place-items-center rounded-full", files.length ? "bg-lime text-lime-ink" : "bg-well text-ink-2")}>
              {files.length ? <CheckCircle size={24} weight="fill" /> : ai ? <Sparkle size={24} /> : <FileArrowUp size={24} />}
            </span>
            {files.length === 1 ? (
              <span className="max-w-full truncate font-semibold">{files[0]!.name}</span>
            ) : files.length > 1 ? (
              <span className="font-semibold">已选 {files.length} 个文件</span>
            ) : (
              <span className="font-semibold">{ai ? "把截图或 PDF 拖到这里，或点击选择" : "把账单拖到这里，或点击选择"}</span>
            )}
            <span className="text-sm text-ink-3">{files.length ? "点击重新选择" : reads.hint}</span>
          </button>
          <input ref={input} type="file" accept={reads.accept} multiple={!!reads.multiple} className="hidden" onChange={(e) => pick(e.target.files)} />
          <Input aria-label="备注" value={note} onChange={(e) => setNote(e.target.value)} placeholder="备注（可选），如 10 月微信账单" />
          {upload.error instanceof ApiError && <p className="text-sm text-neg">{upload.error.detail}</p>}
          <Button
            variant="primary"
            size="lg"
            disabled={!files.length || !chosen || aiOff}
            loading={upload.isPending}
            onClick={async () => {
              try {
                const b = await upload.mutateAsync();
                navigate(`/imports/${b.id}`);
              } catch {
                /* inline */
              }
            }}
          >
            {ai ? (upload.isPending ? "上传中…" : "让 AI 读取") : "解析账单"}
          </Button>
          <p className="text-sm text-ink-3">
            {aiOff
              ? "服务器还没配置 AI 密钥（BK_AI_API_KEY），AI 识别暂不可用。"
              : ai
                ? "截图会从服务器发给 AI（Anthropic 的 Claude）读取，在后台进行；读到的记录先留在这里，完成导入时才写入账本，看不清的行会单独列出。"
                : "解析只读取文件，完成导入时才写入账本；同一行不会被导入两次，已经记过的会自动对上。"}
          </p>
        </div>
      )}
    </Card>
  );
}

const RECORD_TABS = ["review", "new", "classified", "matched", "booked", "ignored", "duplicate"] as const;

function BatchView() {
  const { batchId } = useParams();
  const bookId = useBookId();
  const label = useLabel();
  const toast = useToast();
  const undoToast = useUndoToast();
  const [tab, setTab] = useState<string | null>(null);
  const [confirmRevert, setConfirmRevert] = useState(false);
  const batch = useBookQuery<Batch>(`/import-batches/${batchId}`, { limit: 0 }, { refetchInterval: (d) => whileReading(d?.data.status === "extracting") });
  const sources = useBookQuery<ImportSource[]>("/import-sources");
  const b = batch.data?.data;
  // One list feeds the tab counts and the rows, so they never disagree.
  const records = useBatchRecords(batchId, b?.status);
  const all = records.data ?? [];
  // A record that may already be in the books waits in 待确认 until someone says "same" or "not the same".
  const bucket = (r: SourceRecord) => (r.match?.status === "pending" ? "review" : r.status);
  const by = all.reduce<Record<string, number>>((m, r) => ((m[bucket(r)] = (m[bucket(r)] ?? 0) + 1), m), {});
  const done = b?.status === "committed" || b?.status === "reverted";
  const active = tab ?? (by.review ? "review" : by.new ? "new" : done && by.booked ? "booked" : (RECORD_TABS.find((s) => by[s]) ?? "new"));
  const rows = all.filter((r) => bucket(r) === active);
  const open = by.new ?? 0;
  const review = by.review ?? 0;
  const toBook = by.classified ?? 0; // new transactions on 完成导入
  const linked = by.matched ?? 0; // already in the books: kept as evidence
  const ready = toBook + linked;

  const applyRules = useBookMutation(async () =>
    api.post<{ changed?: number }>(`/books/${bookId}/rules:apply`, {
      batch_id: batchId,
    }),
  );
  const commit = useBookMutation(async (skipRows: boolean) => api.post<{ counts?: Record<string, number> }>(`/books/${bookId}/import-batches/${batchId}:commit`, { accept_row_errors: skipRows }));
  const revert = useBookMutation(async () => api.post(`/books/${bookId}/import-batches/${batchId}:revert`, {}));
  const allSame = useBookMutation(async () => api.post<{ decided: number }>(`/books/${bookId}/import-batches/${batchId}:decide-matches`, { same: true }));
  const retry = useBookMutation(async () => api.post(`/books/${bookId}/import-batches/${batchId}:retry`, {}));

  useEffect(() => {
    if (!confirmRevert) return;
    const id = setTimeout(() => setConfirmRevert(false), 4000);
    return () => clearTimeout(id);
  }, [confirmRevert]);

  if (batch.error) return <ErrorNote error={batch.error} onRetry={() => batch.refetch()} />;

  // A finished import keeps whatever it could not book; completing such a record books it at once.
  const editable = b?.status === "parsed" || b?.status === "committed";
  const blocking = b?.summary.blocking ?? [];
  // Rows that could not be read are the one block an owner can wave through: they are skipped, not guessed.
  const skipRows = blocking.length > 0 && blocking.every((x) => x === "row_errors");
  const unreadRows = b?.summary.row_errors?.length ?? 0;
  const extraction = b?.summary.extraction;
  const failed = (b?.summary.checks ?? []).filter((c) => !c.ok);
  const name = b ? sourceName(b, sources.data?.data ?? []) : "导入";

  return (
    <>
      <Link to="/imports" className="-ml-1 mb-3 inline-flex items-center gap-1 rounded-full px-1 text-sm font-medium text-ink-2 hover:text-ink">
        <ArrowLeft size={14} />
        导入
      </Link>
      <PageHeader title={name} badge={b && <Badge tone={STATUS_TONE[b.status]}>{label("import_batch_status", b.status)}</Badge>} />

      {b?.status === "extracting" || b?.status === "failed" ? (
        <Reading batch={b} retrying={retry.isPending} reverting={revert.isPending} onRetry={() => retry.mutateAsync(undefined)} onRevert={() => revert.mutateAsync(undefined)} />
      ) : (
        <div className="grid gap-5">
          <Card className="p-6 max-sm:p-5">
            {!b || !records.data ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <div className="flex flex-wrap items-center justify-between gap-5">
                <dl className="flex flex-wrap gap-x-8 gap-y-3">
                  <Fig label="记录" value={all.length} />
                  {review > 0 && <Fig label="待确认" value={review} tone="warn" />}
                  {(!done || open > 0) && <Fig label="待补全" value={open} tone={open ? "warn" : undefined} />}
                  {!done && <Fig label="可入账" value={toBook} />}
                  {linked > 0 && <Fig label="已对上" value={linked} />}
                  {(by.booked ?? 0) > 0 && <Fig label="已入账" value={by.booked!} />}
                  {(by.ignored ?? 0) + (by.duplicate ?? 0) > 0 && <Fig label="忽略与重复" value={(by.ignored ?? 0) + (by.duplicate ?? 0)} />}
                  {b.summary.period && (
                    <div>
                      <dt className="text-sm text-ink-2">账单日期</dt>
                      <dd className="num mt-0.5 text-lg font-semibold">
                        {shortDate(b.summary.period[0])} – {shortDate(b.summary.period[1])}
                      </dd>
                    </div>
                  )}
                </dl>
                <div className="flex flex-wrap gap-2">
                  {editable && (
                    <>
                      <Button
                        icon={<Lightning size={16} />}
                        loading={applyRules.isPending}
                        onClick={async () => {
                          try {
                            await applyRules.mutateAsync();
                            toast({ tone: "ok", text: "已按分类规则重新处理" });
                          } catch (e) {
                            toast({
                              tone: "error",
                              text: e instanceof ApiError ? e.detail : "应用规则失败：请稍后重试。",
                            });
                          }
                        }}
                      >
                        应用规则
                      </Button>
                      {b.status === "parsed" && (
                        <Button
                          variant="primary"
                          disabled={(blocking.length > 0 && !skipRows) || ready === 0}
                          loading={commit.isPending}
                          onClick={async () => {
                            try {
                              const res = await commit.mutateAsync(skipRows);
                              const c = res.data.counts ?? {};
                              const parts = [`已入账 ${c.booked ?? 0} 笔`];
                              if (c.linked) parts.push(`${c.linked} 条对上了已记的交易`);
                              if (c.pending_match) parts.push(`${c.pending_match} 条可能已记过，等你确认`);
                              if (open) parts.push(`${open} 条待补全的留在这里`);
                              undoToast(parts.join("，"), changeSetOf(res), "已撤销这次导入");
                            } catch (e) {
                              toast({
                                tone: "error",
                                text: e instanceof ApiError ? e.detail : "完成导入失败：请稍后重试。",
                              });
                            }
                          }}
                        >
                          {skipRows ? `跳过 ${unreadRows} 行，完成导入` : "完成导入"}
                          {toBook > 0 && ` · 入账 ${toBook} 笔`}
                        </Button>
                      )}
                    </>
                  )}
                  {b.status === "committed" && (
                    <Button
                      variant="danger"
                      loading={revert.isPending}
                      onClick={async () => {
                        if (!confirmRevert) return setConfirmRevert(true);
                        setConfirmRevert(false);
                        try {
                          await revert.mutateAsync();
                          toast({
                            tone: "ok",
                            text: "已撤销导入：这批生成的交易已删除，记录保留可重新导入",
                          });
                        } catch (e) {
                          toast({
                            tone: "error",
                            text: e instanceof ApiError ? e.detail : "撤销导入失败：请稍后重试。",
                          });
                        }
                      }}
                    >
                      {confirmRevert ? "再点一次，撤销整批" : "撤销导入"}
                    </Button>
                  )}
                </div>
              </div>
            )}
            {extraction && (
              <div className="mt-5 grid gap-1.5 border-t border-line pt-4 text-sm">
                <p className="flex items-center gap-2 text-ink-2">
                  <Sparkle size={16} className="shrink-0 text-pos" />
                  AI 读取了 {extraction.files.length} 个文件，读到 {b?.summary.records ?? 0} 条；请对照原图核对金额和日期。
                </p>
                {extraction.totals.length > 0 && <p className="text-ink-3">页面上的合计：{extraction.totals.join("；")}</p>}
                {extraction.unreadable.map((u) => (
                  <p key={u} className="flex items-start gap-2 text-warn-text">
                    <WarningCircle size={16} className="mt-0.5 shrink-0" />
                    没读清：{u}
                  </p>
                ))}
              </div>
            )}
            {(failed.length > 0 || blocking.length > 0 || (b?.summary.row_errors?.length ?? 0) > 0) && (
              <ul className="mt-5 grid gap-1.5 border-t border-line pt-4 text-sm">
                {failed.map((c, i) => (
                  <li key={i} className={clsx("flex items-start gap-2", c.severity === "error" ? "text-neg" : "text-warn-text")}>
                    {c.severity === "error" ? <XCircle size={16} className="mt-0.5 shrink-0" /> : <WarningCircle size={16} className="mt-0.5 shrink-0" />}
                    {c.message}
                  </li>
                ))}
                {blocking
                  .filter((m) => m !== "row_errors")
                  .map((m) => (
                    <li key={m} className="flex items-start gap-2 text-neg">
                      <XCircle size={16} className="mt-0.5 shrink-0" />
                      {m}
                    </li>
                  ))}
                {b?.summary.row_errors?.slice(0, 8).map((r) => (
                  <li key={r.row_no} className="num text-neg">
                    第 {r.row_no} 行：{r.message}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {b?.status === "committed" && open > 0 && (
            <p className="-mt-1 flex items-center gap-2 px-1 text-sm text-ink-2">
              <span aria-hidden className="size-1.5 rounded-full bg-warn" />
              这批已完成导入，还有 {open} 条没入账；补全后会立即入账。
            </p>
          )}
          <Card className="px-6 pt-5 pb-3 max-sm:px-5" aria-label="来源记录">
            <div className="-mx-1 overflow-x-auto px-1 pb-1">
              <Segmented
                size="sm"
                label="记录状态"
                value={active}
                onChange={setTab}
                options={RECORD_TABS.filter((s) => (s === "new" && !done) || (by[s] ?? 0) > 0).map((s) => ({
                  value: s,
                  label: s === "review" ? "待确认" : s === "new" ? "待补全" : s === "matched" ? "已对上" : label("source_record_status", s),
                  count: by[s] ?? 0,
                }))}
              />
            </div>
            {active === "review" && review > 0 && editable && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-field border border-line px-4 py-3">
                <p className="text-sm text-ink-2">这些记录和账本里同一天、同一往来方的交易对不上金额，可能是同一笔（手续费算法不同、隔天兑换）。按交易分组，每组确认一次。</p>
                <Button
                  size="sm"
                  loading={allSame.isPending}
                  onClick={async () => {
                    try {
                      const res = await allSame.mutateAsync();
                      toast({
                        tone: "ok",
                        text: `已把 ${res.data.decided} 条关联到已记的交易`,
                      });
                    } catch (e) {
                      toast({
                        tone: "error",
                        text: e instanceof ApiError ? e.detail : "操作失败：请稍后重试。",
                      });
                    }
                  }}
                >
                  这 {review} 条都是已记过的
                </Button>
              </div>
            )}
            <div className="mt-2">
              {!records.data ? (
                <div className="grid gap-4 py-4">
                  {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-10 w-full" />
                  ))}
                </div>
              ) : rows.length === 0 ? (
                <Empty
                  icon={<CheckCircle size={24} weight="fill" className="text-pos" />}
                  title={active === "review" ? "都确认过了" : active === "new" ? "没有要补全的记录" : "这一类没有记录"}
                  className="py-10"
                >
                  {active === "new" && b?.status === "parsed" ? "全部记录都已分类、匹配或忽略，可以完成导入了。" : undefined}
                </Empty>
              ) : active === "review" ? (
                <ReviewGroups batchId={batchId!} records={rows} editable={!!editable} />
              ) : (
                <ul className="divide-y divide-line">
                  {rows.map((r) => (
                    <RecordRow key={r.id} record={r} editable={!!editable} committed={b?.status === "committed"} />
                  ))}
                </ul>
              )}
            </div>
          </Card>
        </div>
      )}
    </>
  );
}

/** An AI read on the server: what is happening while it runs, and what to do when it failed. */
function Reading({ batch: b, retrying, reverting, onRetry, onRevert }: { batch: Batch; retrying: boolean; reverting: boolean; onRetry: () => Promise<unknown>; onRevert: () => Promise<unknown> }) {
  const toast = useToast();
  const files = b.summary.files?.length ?? 1;
  if (b.status === "extracting")
    return (
      <Card className="grid justify-items-center gap-3 px-6 py-14 text-center max-sm:px-5" aria-live="polite">
        <span aria-hidden className="grid size-12 animate-pulse place-items-center rounded-full bg-lime-wash text-pos">
          <Sparkle size={24} weight="fill" />
        </span>
        <p className="text-md font-semibold">AI 正在读取 {files} 个文件…</p>
        <p className="max-w-[40ch] text-sm text-balance break-keep wrap-anywhere text-ink-2">一般几十秒。读完会自动出现在这里，可以先去做别的。</p>
      </Card>
    );
  return (
    <Card className="grid justify-items-center gap-3 px-6 py-14 text-center max-sm:px-5">
      <span aria-hidden className="grid size-12 place-items-center rounded-full bg-neg-wash text-neg">
        <WarningCircle size={24} />
      </span>
      <p className="text-md font-semibold">这次没读成</p>
      <p className="max-w-[44ch] text-sm text-balance break-keep wrap-anywhere text-ink-2">{b.summary.error ?? "AI 读取失败。"}</p>
      <div className="mt-2 flex flex-wrap justify-center gap-2">
        <Button
          variant="primary"
          loading={retrying}
          onClick={async () => {
            try {
              await onRetry();
            } catch (e) {
              toast({
                tone: "error",
                text: e instanceof ApiError ? e.detail : "重试失败：请稍后再试。",
              });
            }
          }}
        >
          再读一次
        </Button>
        <Button
          loading={reverting}
          onClick={async () => {
            try {
              await onRevert();
              toast({ tone: "ok", text: "已放弃这次识别" });
            } catch (e) {
              toast({
                tone: "error",
                text: e instanceof ApiError ? e.detail : "操作失败：请稍后重试。",
              });
            }
          }}
        >
          放弃
        </Button>
      </div>
    </Card>
  );
}

function Fig({ label, value, tone }: { label: string; value: number; tone?: "warn" }) {
  return (
    <div>
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className={clsx("figure mt-0.5 text-lg", tone === "warn" && "text-warn-text")}>{value}</dd>
    </div>
  );
}
