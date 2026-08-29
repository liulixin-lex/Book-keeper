import React, { createContext, useContext, useState, useCallback } from "react";
import {
  X,
  CheckCircle,
  Warning,
  Info,
  WarningCircle,
} from "@phosphor-icons/react";

export type ToastType = "success" | "error" | "warning" | "info";

export interface ToastMessage {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastContextType {
  toast: (message: string, type?: ToastType) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  warning: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = Math.random().toString(36).substring(2, 9);
      setToasts((prev) => [...prev, { id, type, message }]);
      setTimeout(() => {
        removeToast(id);
      }, 4000);
    },
    [removeToast],
  );

  const success = useCallback(
    (msg: string) => addToast(msg, "success"),
    [addToast],
  );
  const error = useCallback(
    (msg: string) => addToast(msg, "error"),
    [addToast],
  );
  const warning = useCallback(
    (msg: string) => addToast(msg, "warning"),
    [addToast],
  );
  const info = useCallback((msg: string) => addToast(msg, "info"), [addToast]);

  return (
    <ToastContext.Provider
      value={{ toast: addToast, success, error, warning, info }}
    >
      {children}
      <div
        className="pointer-events-none fixed inset-x-3 bottom-3 z-50 flex flex-col items-end gap-2 sm:left-auto sm:right-4 sm:bottom-4 sm:w-auto"
        aria-live="polite"
      >
        {toasts.map((t) => {
          let Icon = Info;
          let iconColor = "text-primary";

          if (t.type === "success") {
            Icon = CheckCircle;
            iconColor = "text-success";
          } else if (t.type === "error") {
            Icon = WarningCircle;
            iconColor = "text-danger";
          } else if (t.type === "warning") {
            Icon = Warning;
            iconColor = "text-warning";
          }

          return (
            <div
              key={t.id}
              role={t.type === "error" ? "alert" : "status"}
              className="instrument-panel-raised pointer-events-auto flex w-full max-w-md items-center gap-3 px-3.5 py-3 text-ink sm:min-w-[300px]"
            >
              <Icon
                size={19}
                className={`shrink-0 ${iconColor}`}
                weight="duotone"
              />
              <div className="flex-1 break-words text-sm leading-snug">
                {t.message}
              </div>
              <button
                type="button"
                onClick={() => removeToast(t.id)}
                aria-label="关闭通知"
                className="instrument-control shrink-0 p-1.5 text-muted hover:text-ink"
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = (): ToastContextType => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
};
