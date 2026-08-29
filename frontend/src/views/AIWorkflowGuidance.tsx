import React, { useEffect, useRef } from "react";
import {
  ChatCircleDots,
  PaperPlaneTilt,
  Question,
} from "@phosphor-icons/react";
import type { AIWorkflow } from "../types/api";

interface AIWorkflowGuidanceProps {
  messages: AIWorkflow["messages"];
  value: string;
  disabled: boolean;
  isSending: boolean;
  onChange: (value: string) => void;
  onSend: () => void;
}

export const AIWorkflowGuidance: React.FC<AIWorkflowGuidanceProps> = ({
  messages,
  value,
  disabled,
  isSending,
  onChange,
  onSend,
}) => {
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages]);

  return (
    <div className="flex min-h-[360px] flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="flex items-center gap-2 text-xs font-semibold text-ink">
          <ChatCircleDots size={17} className="text-primary" />
          判断引导
        </span>
        <span className="text-[10px] tabular-nums text-muted">
          {messages.length} 条记录
        </span>
      </div>

      <div
        ref={logRef}
        aria-live="polite"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3"
      >
        {messages.length === 0 ? (
          <div className="flex min-h-40 items-center justify-center text-xs text-muted">
            暂无判断记录
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[88%] rounded-lg px-3 py-2 text-xs leading-5 ${
                  message.role === "user"
                    ? "bg-primary text-primary-ink"
                    : "border border-border bg-surface-inset text-ink"
                }`}
              >
                <div className="whitespace-pre-wrap break-words">
                  {message.content}
                </div>
                {message.clarifying_questions.length > 0 && (
                  <div className="mt-2 space-y-1.5 border-t border-border/70 pt-2">
                    {message.clarifying_questions.map((question) => (
                      <div key={question} className="flex items-start gap-1.5">
                        <Question
                          size={14}
                          className="mt-0.5 shrink-0 text-warning"
                        />
                        <span>{question}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2 rounded-lg border border-border bg-surface-inset p-2 shadow-control-inset focus-within:border-primary">
          <textarea
            aria-label="判断引导"
            value={value}
            rows={2}
            maxLength={8000}
            disabled={disabled || isSending}
            placeholder="补充背景或回答澄清问题"
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (value.trim() && !disabled && !isSending) onSend();
              }
            }}
            className="min-h-12 flex-1 resize-none bg-transparent px-1 py-1 text-xs leading-5 text-ink outline-none placeholder:text-muted/70 disabled:opacity-50"
          />
          <button
            type="button"
            title="发送"
            aria-label="发送判断引导"
            disabled={disabled || isSending || !value.trim()}
            onClick={onSend}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-ink transition-colors hover:bg-primary-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-40"
          >
            <PaperPlaneTilt size={17} />
          </button>
        </div>
      </div>
    </div>
  );
};
