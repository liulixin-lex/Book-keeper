/** React Query bindings. Reference data (types, enums, accounts, dimensions, counterparties) is cached for the session. */
import { QueryClient, useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api, ApiError, type Envelope } from "./client";
import type { Account, Batch, Book, Capabilities, Commodity, Counterparty, SourceRecord, DimensionType, Enums, Me, TransactionDetail, TransactionType, WorkSummary } from "./types";
import { useBookId } from "@/app/book";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: true,
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
    },
  },
});

const STATIC = { staleTime: 10 * 60_000 } as const;

export const keys = {
  me: ["me"] as const,
  book: (b: string) => ["book", b] as const,
  scope: (b: string, ...rest: unknown[]) => ["book", b, ...rest] as const,
};

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: async () => (await api.get<Me>("/auth/me")).data, retry: false, staleTime: 5 * 60_000 });
}

export function useEnums() {
  return useQuery({ queryKey: ["enums"], queryFn: async () => (await api.get<Enums>("/meta/enums")).data, ...STATIC });
}

export function useCapabilities() {
  return useQuery({ queryKey: ["capabilities"], queryFn: async () => (await api.get<Capabilities>("/meta/capabilities")).data, ...STATIC });
}

/** Display label for an enum value, falling back to the raw code. */
export function useLabel() {
  const { data } = useEnums();
  return (group: string, code: string | null | undefined) => (code ? (data?.[group]?.[code] ?? code) : "");
}

export function useBook() {
  const b = useBookId();
  return useQuery({ queryKey: keys.book(b), queryFn: async () => (await api.get<Book>(`/books/${b}`)).data, ...STATIC });
}

/** Whether you hold a permission in the current book (false while the book loads). */
export function useCan(scope: string): boolean {
  return useBook().data?.scopes.includes(scope) ?? false;
}

export function useBookQuery<T>(
  path: string,
  query?: Record<string, unknown>,
  opts: { enabled?: boolean; staleTime?: number; keep?: boolean; refetchInterval?: number | false | ((data: Envelope<T> | undefined) => number | false) } = {},
) {
  const b = useBookId();
  return useQuery({
    queryKey: keys.scope(b, path, query ?? {}),
    queryFn: async ({ signal }) => await api.get<T>(`/books/${b}${path}`, query as never, signal),
    enabled: opts.enabled ?? true,
    staleTime: opts.staleTime,
    placeholderData: opts.keep ? keepPreviousData : undefined,
    refetchInterval: typeof opts.refetchInterval === "function" ? (q) => (opts.refetchInterval as (d: Envelope<T> | undefined) => number | false)(q.state.data) : opts.refetchInterval,
  });
}

export function useTransactionTypes() {
  const b = useBookId();
  return useQuery({ queryKey: keys.scope(b, "types"), queryFn: async () => (await api.get<TransactionType[]>(`/books/${b}/transaction-types`)).data, ...STATIC });
}

export function useAccounts() {
  const b = useBookId();
  return useQuery({ queryKey: keys.scope(b, "accounts"), queryFn: async () => (await api.get<Account[]>(`/books/${b}/accounts`)).data, ...STATIC });
}

export function useDimensions() {
  const b = useBookId();
  return useQuery({ queryKey: keys.scope(b, "dimensions"), queryFn: async () => (await api.get<DimensionType[]>(`/books/${b}/dimensions`)).data, ...STATIC });
}

/** Active sales / purchase channels (链动, 云猫, Stripe…). */
export function useChannels() {
  return (
    useDimensions()
      .data?.find((d) => d.code === "channel")
      ?.values.filter((v) => v.is_active) ?? []
  );
}

export function useCommodities() {
  const b = useBookId();
  return useQuery({ queryKey: keys.scope(b, "commodities"), queryFn: async () => (await api.get<Commodity[]>(`/books/${b}/commodities`)).data, ...STATIC });
}

export function useCounterparties() {
  const b = useBookId();
  return useQuery({
    queryKey: keys.scope(b, "counterparties"),
    queryFn: async () => (await api.get<Counterparty[]>(`/books/${b}/counterparties`, { limit: 200 })).data,
    ...STATIC,
  });
}

/** Expense categories offered in entry and import forms: active expense accounts, without system roles. */
const SYSTEM_EXPENSE_ROLES = new Set(["fx_gain_loss", "rounding", "current_year_profit", "trading"]);
export function useCategories() {
  return (useAccounts().data ?? []).filter((a) => a.classification === "expense" && !a.is_group && a.is_active && !SYSTEM_EXPENSE_ROLES.has(a.role ?? "") && a.code !== "5401.01");
}

/** id → name lookups for list rows, which carry only ids. */
export function useNames() {
  const cps = useCounterparties().data;
  const dims = useDimensions().data;
  const counterparty = new Map(cps?.map((c) => [c.id, c.name]));
  const channel = new Map<string, { code: string; name: string }>();
  dims?.find((d) => d.code === "channel")?.values.forEach((v) => channel.set(v.id, { code: v.code, name: v.name }));
  return { counterparty, channel };
}

/** Statement records not yet in the books, summed over every import (the 导入 badge, the 概览 to-do and the 导入 page agree). */
export function useImportBacklog(): { count: number; first: string | null } {
  const b = useBookId();
  const batches = useQuery({
    queryKey: keys.scope(b, "/import-batches", { limit: 200 }),
    queryFn: async ({ signal }) => await api.get<Batch[]>(`/books/${b}/import-batches`, { limit: 200 }, signal),
    staleTime: 10_000,
  }).data?.data;
  const waiting = (batches ?? []).filter((x) => (x.open_records ?? 0) > 0);
  return { count: waiting.reduce((n, x) => n + (x.open_records ?? 0), 0), first: waiting[0]?.id ?? null };
}

export function useWorkSummary() {
  const b = useBookId();
  return useQuery({ queryKey: keys.scope(b, "work-summary"), queryFn: async () => (await api.get<WorkSummary>(`/books/${b}/work-items/summary`)).data, staleTime: 10_000 });
}

export function useTransaction(ref: string | null) {
  const b = useBookId();
  return useQuery({
    queryKey: keys.scope(b, "transaction", ref),
    queryFn: async () => (await api.get<TransactionDetail>(`/books/${b}/transactions/${ref}`)).data,
    enabled: !!ref,
  });
}

/** Mutation helper: runs a write and refreshes everything in the book (lists, balances, reports) afterwards. */
/** Every record of an import, page by page (the API serves at most 500 at a time). */
export function useBatchRecords(batchId: string | undefined, status?: string) {
  const b = useBookId();
  return useQuery({
    // the batch status is part of the key: when an AI read finishes, its records load at once
    queryKey: keys.scope(b, "/source-records", { batch_id: batchId, all: true, status }),
    enabled: !!batchId,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const all: SourceRecord[] = [];
      for (let offset = 0; ; offset += 500) {
        const page = (await api.get<SourceRecord[]>(`/books/${b}/source-records`, { batch_id: batchId, limit: 500, offset })).data;
        all.push(...page);
        if (page.length < 500) return all;
      }
    },
  });
}

export function useBookMutation<TVars, TData = unknown>(fn: (vars: TVars, bookId: string) => Promise<TData>) {
  const b = useBookId();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: TVars) => fn(vars, b),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.book(b) }),
  });
}

/** Undo one write by its change set: what was created is deleted, what was deleted comes back, edits are put back. */
export function useUndo() {
  return useBookMutation(async (changeSetId: string, b) => api.post(`/books/${b}/change-sets/${changeSetId}:undo`, {}));
}

/** The change set a write produced, for its undo toast. */
export function changeSetOf(res: Envelope<unknown>): string | null {
  return typeof res.meta.change_set_id === "string" ? res.meta.change_set_id : null;
}
