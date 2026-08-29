import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, setCsrfToken } from "../api/client";

afterEach(() => {
  vi.restoreAllMocks();
  setCsrfToken(null);
});

describe("API client contract", () => {
  it("adds the API prefix and write request safeguards", async () => {
    setCsrfToken("csrf-test");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await apiRequest("/records/expenses", {
      method: "POST",
      body: JSON.stringify({ amount: "1.00" }),
      idempotencyKey: "idem-test",
    });

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, options] = fetchMock.mock.calls[0];
    const headers = new Headers(options?.headers);
    expect(url).toBe("/api/v1/records/expenses");
    expect(options?.credentials).toBe("include");
    expect(headers.get("X-CSRF-Token")).toBe("csrf-test");
    expect(headers.get("Idempotency-Key")).toBe("idem-test");
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});
