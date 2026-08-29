import React from "react";
import { Button } from "./core";
import { Tray, WarningCircle } from "@phosphor-icons/react";

export const EmptyState: React.FC<{
  title?: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
  icon?: React.ReactNode;
}> = ({
  title = "暂无数据",
  description = "当前没有找到匹配的记录",
  actionText,
  onAction,
  icon,
}) => {
  return (
    <div className="instrument-inset my-4 flex flex-col items-center justify-center p-10 text-center sm:p-12">
      <div className="mb-3 text-muted/60">
        {icon || <Tray size={36} weight="duotone" />}
      </div>
      <h4 className="text-sm font-semibold text-ink mb-1">{title}</h4>
      <p className="text-xs text-muted max-w-sm mb-4 leading-relaxed">
        {description}
      </p>
      {actionText && onAction && (
        <Button variant="outline" size="sm" onClick={onAction}>
          {actionText}
        </Button>
      )}
    </div>
  );
};

export const ErrorState: React.FC<{
  title?: string;
  message: string;
  onRetry?: () => void;
}> = ({ title = "加载失败", message, onRetry }) => {
  return (
    <div className="my-4 flex flex-col items-center justify-center rounded-lg border border-danger/30 bg-danger/10 p-8 text-center">
      <WarningCircle size={34} className="mb-2 text-danger" weight="duotone" />
      <h4 className="text-sm font-semibold text-ink mb-1">{title}</h4>
      <p className="text-xs text-danger/80 max-w-sm mb-4">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          重试
        </Button>
      )}
    </div>
  );
};

export const TableSkeleton: React.FC<{ rows?: number; cols?: number }> = ({
  rows = 5,
  cols = 4,
}) => {
  return (
    <div className="instrument-inset w-full space-y-3 p-4">
      <div className="skeleton-sheen mb-4 h-8 w-full" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 items-center">
          {Array.from({ length: cols }).map((_, j) => (
            <div
              key={j}
              className="skeleton-sheen h-5 flex-1"
              style={{ opacity: 1 - i * 0.12 }}
            />
          ))}
        </div>
      ))}
    </div>
  );
};
