import React, { useEffect, useState } from "react";
import {
  ChatCircleText,
  FlowArrow,
  SlidersHorizontal,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Badge, Select } from "../components/ui/core";
import { useAuth } from "../context/AuthContext";
import { AIProvider } from "../types/api";
import { AIQueryPanel } from "./AIQueryPanel";
import { AIWriteWorkbench } from "./AIWriteWorkbench";

type WorkbenchMode = "query" | "ledger";

export const AIChatView: React.FC = () => {
  const { user } = useAuth();
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [providerId, setProviderId] = useState("");
  const [mode, setMode] = useState<WorkbenchMode>(
    user?.role === "viewer" ? "query" : "ledger",
  );

  useEffect(() => {
    void apiRequest<AIProvider[]>("/ai/providers")
      .then((rows) => {
        const active = rows.filter((provider) => provider.is_active);
        setProviders(active);
        setProviderId((current) => current || active[0]?.id || "");
      })
      .catch(() => {
        setProviders([]);
      });
  }, []);

  return (
    <div className="space-y-3">
      <div className="instrument-strip flex flex-col gap-3 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div className="instrument-inset grid grid-cols-2 p-1">
          <button
            type="button"
            onClick={() => setMode("ledger")}
            disabled={user?.role === "viewer"}
            className={`flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              mode === "ledger"
                ? "bg-primary text-primary-ink shadow-[inset_0_1px_0_rgb(255_255_255_/_0.4)]"
                : "text-muted hover:text-ink"
            }`}
          >
            <FlowArrow size={16} />
            流程记账
          </button>
          <button
            type="button"
            onClick={() => setMode("query")}
            className={`flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors ${
              mode === "query"
                ? "bg-primary text-primary-ink shadow-[inset_0_1px_0_rgb(255_255_255_/_0.4)]"
                : "text-muted hover:text-ink"
            }`}
          >
            <ChatCircleText size={16} />
            只读查询
          </button>
        </div>

        <div className="flex min-w-0 items-center gap-2">
          <SlidersHorizontal size={16} className="shrink-0 text-muted" />
          {providers.length > 0 ? (
            <Select
              value={providerId}
              onChange={(event) => setProviderId(event.target.value)}
              className="min-w-0 text-xs sm:w-60"
              aria-label="AI 供应商"
            >
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name} · {provider.model}
                </option>
              ))}
            </Select>
          ) : (
            <Badge variant="danger">AI 供应商不可用</Badge>
          )}
        </div>
      </div>

      {mode === "ledger" && user?.role !== "viewer" ? (
        <AIWriteWorkbench providerId={providerId} />
      ) : (
        <AIQueryPanel providerId={providerId} />
      )}
    </div>
  );
};
