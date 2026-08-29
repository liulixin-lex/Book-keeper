// Centralized Fetch API Client with CSRF, Error Normalization & Auth Handling

class ApiError extends Error {
  status: number;
  data: any;

  constructor(status: number, message: string, data?: any) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

let storedCsrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  storedCsrfToken = token;
  if (token) {
    localStorage.setItem("ledger_csrf_token", token);
  } else {
    localStorage.removeItem("ledger_csrf_token");
  }
}

export function getCsrfToken(): string | null {
  if (!storedCsrfToken) {
    storedCsrfToken = localStorage.getItem("ledger_csrf_token");
  }
  return storedCsrfToken;
}

export async function apiRequest<T = any>(
  path: string,
  options: RequestInit & { idempotencyKey?: string } = {},
): Promise<T> {
  const url = path.startsWith("/api")
    ? path
    : `/api/v1${path.startsWith("/") ? "" : "/"}${path}`;

  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  // Include CSRF Token if state-modifying request
  const method = (options.method || "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) {
      headers.set("X-CSRF-Token", csrf);
    }
  }

  if (options.idempotencyKey) {
    headers.set("Idempotency-Key", options.idempotencyKey);
  }

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: "include", // Include HttpOnly session cookies
  });

  if (response.status === 204) {
    return null as unknown as T;
  }

  let responseData: any = null;
  const contentType = response.headers.get("content-type");
  if (contentType && contentType.includes("application/json")) {
    try {
      responseData = await response.json();
    } catch {
      responseData = null;
    }
  } else {
    responseData = await response.text();
  }

  if (!response.ok) {
    let errorMessage = "网络请求失败";
    if (responseData) {
      if (typeof responseData.detail === "string") {
        errorMessage = responseData.detail;
      } else if (Array.isArray(responseData.detail)) {
        errorMessage = responseData.detail
          .map((e: any) => e.msg || JSON.stringify(e))
          .join(", ");
      } else if (responseData.message) {
        errorMessage = responseData.message;
      }
    }
    throw new ApiError(response.status, errorMessage, responseData);
  }

  return responseData as T;
}

export { ApiError };
