/**
 * Transient confirmations with an undo window: "已记一笔 · 撤销". Writes take effect at once, so undo replaces
 * confirmation dialogs. Errors that need action stay inline next to their control, not here.
 */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { clsx } from "clsx";
import { CheckCircle, WarningCircle } from "@phosphor-icons/react";
import { ApiError } from "@/api/client";
import { useUndo } from "@/api/queries";

interface Toast {
  id: number;
  tone: "ok" | "error";
  text: string;
  action?: { label: string; run: () => void | Promise<void> };
}

type Push = (t: Omit<Toast, "id">) => void;

const ToastContext = createContext<Push>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((all) => all.filter((x) => x.id !== id));
  }, []);

  const push = useCallback<Push>(
    (t) => {
      const id = Date.now() + Math.random();
      setToasts((all) => [...all.slice(-1), { ...t, id }]);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), t.action ? 6500 : 3200),
      );
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-6 z-50 grid justify-items-center gap-2 px-4 max-lg:bottom-[calc(92px+env(safe-area-inset-bottom))]">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={clsx("toast frost-ink pointer-events-auto flex min-h-12 max-w-[min(520px,100%)] items-center gap-3 rounded-full py-2 pl-4 text-base text-toast-ink", t.action ? "pr-2" : "pr-5")}
          >
            {t.tone === "ok" ? <CheckCircle size={20} weight="fill" className="shrink-0 text-toast-accent" /> : <WarningCircle size={20} weight="fill" className="shrink-0 text-neg" />}
            <span className="min-w-0 truncate">{t.text}</span>
            {t.action && (
              <button
                type="button"
                className="h-8 shrink-0 rounded-full bg-lime px-3.5 text-sm font-semibold text-lime-ink transition-transform duration-150 active:scale-95"
                onClick={async () => {
                  dismiss(t.id);
                  await t.action!.run();
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

/** "已删除 T2026-000798 · 撤销": a success toast whose button undoes the write's change set. */
export function useUndoToast() {
  const toast = useToast();
  const undo = useUndo();
  return (text: string, changeSet: string | null, undone = "已撤销") =>
    toast({
      tone: "ok",
      text,
      action: changeSet
        ? {
            label: "撤销",
            run: async () => {
              try {
                await undo.mutateAsync(changeSet);
                toast({ tone: "ok", text: undone });
              } catch (e) {
                toast({ tone: "error", text: e instanceof ApiError ? e.detail : "撤销失败：网络或服务暂时不可用。请稍后重试。" });
              }
            },
          }
        : undefined,
    });
}
