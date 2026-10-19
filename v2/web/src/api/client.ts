/** REST client for the bookkeeper v2 API: session cookie + CSRF header, idempotent writes, problem+json errors. */

export interface Envelope<T> {
  data: T;
  meta: { request_id?: string; has_more?: boolean; next_cursor?: string | null; total?: number; [k: string]: unknown };
  warnings: ApiWarning[];
}

export interface ApiWarning {
  code: string;
  message: string;
  [k: string]: unknown;
}

export interface FieldError {
  path: string;
  code: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly errors: FieldError[];
  readonly nextAction: string | null;

  constructor(status: number, body: Record<string, unknown>) {
    const detail = String(body.detail ?? body.title ?? "请求失败");
    super(detail);
    this.status = status;
    this.code = String(body.code ?? "ERROR");
    this.detail = detail;
    this.errors = Array.isArray(body.errors) ? (body.errors as FieldError[]) : [];
    this.nextAction = typeof body.next_action === "string" ? body.next_action : null;
  }
}

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

let csrfToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export function buildUrl(path: string, query?: Query): string {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, String(v)));
    else url.searchParams.set(key, String(value));
  }
  return url.pathname + url.search;
}

async function request<T>(method: string, path: string, init: { query?: Query; body?: unknown; form?: FormData; signal?: AbortSignal; idempotencyKey?: string } = {}): Promise<Envelope<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const write = method !== "GET";
  if (write) {
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    headers["Idempotency-Key"] = init.idempotencyKey ?? crypto.randomUUID();
  }
  let body: BodyInit | undefined;
  if (init.form) body = init.form;
  else if (init.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.body);
  }
  const response = await fetch(buildUrl(path, init.query), { method, headers, body, credentials: "same-origin", signal: init.signal });
  if (response.status === 204) return { data: undefined as T, meta: {}, warnings: [] };
  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    if (response.status === 401 && onUnauthorized) onUnauthorized();
    throw new ApiError(response.status, payload);
  }
  return payload as unknown as Envelope<T>;
}

export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown, query?: Query) => request<T>("POST", path, { body, query }),
  patch: <T>(path: string, body?: unknown, query?: Query) => request<T>("PATCH", path, { body, query }),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, { body }),
  del: <T>(path: string, body?: unknown, query?: Query) => request<T>("DELETE", path, { body, query }),
  /** A retry of the same upload should pass the same key, so the server answers it once. */
  upload: <T>(path: string, form: FormData, idempotencyKey?: string) => request<T>("POST", path, { form, idempotencyKey }),
};
