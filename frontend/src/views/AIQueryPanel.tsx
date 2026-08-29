import React, { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  ChatCircleText,
  ClockCounterClockwise,
  PaperPlaneTilt,
  Robot,
  Stop,
  User,
} from "@phosphor-icons/react";
import { getCsrfToken } from "../api/client";
import { Button } from "../components/ui/core";
import { useToast } from "../context/ToastContext";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface AIQueryPanelProps {
  providerId: string;
}

interface StreamEvent {
  type: string;
  text?: string;
  error?: string;
  tool_call?: { name?: string };
  result?: Record<string, unknown>;
}

const writeIntent = /(录入|记一笔|记账|新增收入|新增支出|删除账单|冲正)/;

export const AIQueryPanel: React.FC<AIQueryPanelProps> = ({ providerId }) => {
  const { error: toastError, toast } = useToast();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [streamStatus, setStreamStatus] = useState("");
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [retryRequest, setRetryRequest] = useState<{
    messages: ChatMessage[];
    key: string;
  } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === "function") {
      endRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [messages, streamStatus]);

  const run = async (requestMessages: ChatMessage[], key: string) => {
    setIsLoading(true);
    setStreamStatus("");
    abortRef.current = new AbortController();
    let accumulated = "";
    let assistantAdded = false;
    try {
      const headers = new Headers({
        "Content-Type": "application/json",
        "Idempotency-Key": key,
      });
      const csrf = getCsrfToken();
      if (csrf) headers.set("X-CSRF-Token", csrf);
      const response = await fetch(
        `/api/v1/ai/providers/${providerId}/run/stream`,
        {
          method: "POST",
          headers,
          credentials: "include",
          signal: abortRef.current.signal,
          body: JSON.stringify({
            mode: "chat",
            messages: requestMessages,
            max_output_tokens: 2048,
            stream: true,
          }),
        },
      );
      setLastRunId(response.headers.get("X-AI-Run-Id"));
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || "AI 查询失败");
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error("流式连接不可用");
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const data = block
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim())
            .join("\n");
          if (!data) continue;
          const event = JSON.parse(data) as StreamEvent;
          if (event.type === "text_delta" && event.text) {
            accumulated += event.text;
            if (!assistantAdded) {
              assistantAdded = true;
              setMessages((current) => [
                ...current,
                { role: "assistant", content: accumulated },
              ]);
            } else {
              setMessages((current) => {
                const next = [...current];
                next[next.length - 1] = {
                  role: "assistant",
                  content: accumulated,
                };
                return next;
              });
            }
          } else if (event.type === "tool_call") {
            setStreamStatus(event.tool_call?.name || "正在查询账本");
          } else if (event.type === "tool_result") {
            setStreamStatus("账本数据已返回");
          } else if (event.type === "error") {
            throw new Error(event.error || "AI 查询失败");
          } else if (event.type === "done") {
            setStreamStatus("");
          }
        }
      }
      if (!assistantAdded) {
        setMessages((current) => [
          ...current,
          { role: "assistant", content: "AI 未返回文本结果" },
        ]);
      }
      setRetryRequest(null);
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        toast("查询已中止", "info");
      } else {
        setRetryRequest({ messages: requestMessages, key });
        toastError((error as Error).message || "AI 查询失败");
      }
    } finally {
      setIsLoading(false);
      setStreamStatus("");
      abortRef.current = null;
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = input.trim();
    if (!value || isLoading || !providerId) return;
    if (writeIntent.test(value) && !value.startsWith("/")) {
      setMessages((current) => [
        ...current,
        { role: "user", content: value },
        {
          role: "assistant",
          content: "该请求涉及账本写入，请切换到“流程记账”并选择对应斜杠命令。",
        },
      ]);
      setInput("");
      return;
    }
    const next = [...messages, { role: "user", content: value } as ChatMessage];
    setMessages(next);
    setInput("");
    void run(next, crypto.randomUUID());
  };

  return (
    <section className="instrument-panel flex h-[calc(100dvh-174px)] min-h-[440px] flex-col overflow-hidden">
      <div className="flex min-h-10 items-center justify-between border-b border-border px-3">
        <div className="flex items-center gap-2 text-xs font-medium text-ink">
          <ChatCircleText size={16} className="text-primary" />
          账本查询
        </div>
        <div className="flex items-center gap-1">
          {retryRequest && (
            <button
              type="button"
              title="恢复上次查询"
              aria-label="恢复上次查询"
              disabled={isLoading}
              onClick={() => void run(retryRequest.messages, retryRequest.key)}
              className="rounded-md p-1.5 text-warning hover:bg-warning/10 disabled:opacity-40"
            >
              <ArrowClockwise size={16} />
            </button>
          )}
          <button
            type="button"
            title="清空查询"
            aria-label="清空查询"
            onClick={() => setMessages([])}
            className="rounded-md p-1.5 text-muted hover:bg-surface-strong hover:text-ink"
          >
            <ClockCounterClockwise size={16} />
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4" aria-live="polite">
        {messages.length === 0 && (
          <div className="flex h-full min-h-52 flex-col items-center justify-center gap-2 text-muted">
            <Robot size={28} weight="duotone" />
            <span className="text-xs">暂无查询记录</span>
          </div>
        )}
        {messages.map((message, index) => {
          const assistant = message.role === "assistant";
          return (
            <div
              key={`${message.role}-${index}`}
              className={`flex items-start gap-2.5 ${assistant ? "justify-start" : "justify-end"}`}
            >
              {assistant && (
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Robot size={15} />
                </span>
              )}
              <div
                className={`max-w-[min(42rem,85%)] whitespace-pre-wrap rounded-lg px-3 py-2.5 text-xs leading-5 ${
                  assistant
                    ? "border border-border bg-surface-inset text-ink"
                    : "bg-primary text-primary-ink"
                }`}
              >
                {message.content}
              </div>
              {!assistant && (
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border border-border text-muted">
                  <User size={15} />
                </span>
              )}
            </div>
          );
        })}
        {streamStatus && (
          <div className="flex items-center gap-2 text-xs text-ink">
            <ArrowClockwise size={14} className="animate-spin text-primary" />
            {streamStatus}
          </div>
        )}
        {lastRunId && <span className="sr-only">运行编号 {lastRunId}</span>}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="border-t border-border p-3">
        <div className="flex items-center gap-2">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            disabled={isLoading}
            placeholder="输入账本查询"
            className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-surface-inset px-3 text-sm text-ink shadow-control-inset outline-none placeholder:text-muted/60 focus:border-primary"
          />
          {isLoading ? (
            <Button
              type="button"
              variant="danger"
              size="sm"
              onClick={() => abortRef.current?.abort()}
              title="中止查询"
            >
              <Stop size={16} />
              中止
            </Button>
          ) : (
            <Button
              type="submit"
              size="sm"
              disabled={!input.trim() || !providerId}
            >
              <PaperPlaneTilt size={16} />
              发送
            </Button>
          )}
        </div>
      </form>
    </section>
  );
};
