import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../context/ToastContext";
import { BackupSettingsView } from "../views/BackupSettingsView";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BackupSettingsView", () => {
  it("loads storage, schedule and backup history", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/backups/storage")) {
        return new Response(
          JSON.stringify({
            storage_type: "r2",
            endpoint_url: "https://account.r2.cloudflarestorage.com",
            region: "auto",
            bucket: "ledger-backups",
            access_key_id: "access-key",
            prefix: "book-keeper",
            force_path_style: false,
            secret_configured: true,
            version: 2,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      if (url.endsWith("/backups/schedule")) {
        return new Response(
          JSON.stringify({
            enabled: true,
            cron_expression: "0 2 * * *",
            retain_days: 14,
            retain_count: 10,
            timezone: "Asia/Shanghai",
            next_run_at: "2026-08-31T18:00:00Z",
            version: 3,
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "backup-1",
              status: "completed",
              trigger: "scheduled",
              file_name: "ledger-20260830.db",
              object_key: "book-keeper/2026/08/ledger-20260830.db",
              size_bytes: 4096,
              checksum_sha256: "a".repeat(64),
              error_message: null,
              started_at: "2026-08-30T18:00:00Z",
              finished_at: "2026-08-30T18:00:02Z",
              expires_at: "2026-09-13T18:00:00Z",
            },
          ],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });

    render(
      <ToastProvider>
        <BackupSettingsView />
      </ToastProvider>,
    );

    expect(
      await screen.findByDisplayValue("ledger-backups"),
    ).toBeInTheDocument();
    expect(screen.getByText("密钥已保存")).toBeInTheDocument();
    expect(screen.getByText("ledger-20260830.db")).toBeInTheDocument();
    expect(screen.getByText("定时")).toBeInTheDocument();
    expect(screen.queryByText("top-secret-value")).not.toBeInTheDocument();
  });
});
