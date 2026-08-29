import React from "react";
import { BookOpenText } from "@phosphor-icons/react";
import { cn } from "../ui/core";

export type BrandSize = "sm" | "md" | "lg";

export interface BrandMarkProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: BrandSize;
}

export interface BrandWordmarkProps extends React.HTMLAttributes<HTMLSpanElement> {
  size?: BrandSize;
}

export interface BrandLockupProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: BrandSize;
  collapsed?: boolean;
}

const markSizeMap: Record<
  BrandSize,
  { container: string; book: number; kText: string }
> = {
  sm: {
    container: "size-8 rounded-lg",
    book: 16,
    kText: "text-[10px] translate-x-[-1px] translate-y-[1px]",
  },
  md: {
    container: "size-9 rounded-lg",
    book: 19,
    kText: "text-[11px] translate-x-[-1px] translate-y-[1px]",
  },
  lg: {
    container: "size-11 rounded-xl",
    book: 24,
    kText: "text-[13px] translate-x-[-2px] translate-y-[2px]",
  },
};

const wordmarkSizeMap: Record<BrandSize, string> = {
  sm: "text-base tracking-normal",
  md: "text-lg tracking-normal",
  lg: "text-2xl tracking-normal",
};

/**
 * BrandMark: 青绿到电蓝的清透磨砂玻璃徽标，
 * 使用 Phosphor 的 BookOpenText 作为主体，在右下角叠加 Syne 字体的 K。
 */
export const BrandMark: React.FC<BrandMarkProps> = ({
  size = "md",
  className,
  ...props
}) => {
  const cfg = markSizeMap[size];

  return (
    <div
      className={cn(
        "brand-mark relative flex shrink-0 select-none items-center justify-center overflow-hidden font-brand",
        cfg.container,
        className,
      )}
      aria-hidden="true"
      {...props}
    >
      <BookOpenText
        size={cfg.book}
        weight="duotone"
        className="brand-mark-book text-primary-ink/90 transition-transform"
      />
      <span
        className={cn(
          "brand-mark-k absolute right-0.5 bottom-0 font-extrabold leading-none select-none text-primary-ink drop-shadow-xs",
          cfg.kText,
        )}
      >
        K
      </span>
    </div>
  );
};

/**
 * BrandWordmark: Syne Variable "Book keeper"，Book 约 800 粗重，keeper 约 560 粗重且微斜切，letter-spacing 严格为 0。
 */
export const BrandWordmark: React.FC<BrandWordmarkProps> = ({
  size = "md",
  className,
  ...props
}) => {
  return (
    <span
      className={cn(
        "brand-wordmark inline-flex items-baseline font-brand leading-none text-ink select-none whitespace-nowrap",
        wordmarkSizeMap[size],
        className,
      )}
      {...props}
    >
      <span className="brand-wordmark-book font-extrabold">Book</span>
      <span className="brand-wordmark-space">&nbsp;</span>
      <span className="brand-wordmark-keeper font-medium italic">keeper</span>
    </span>
  );
};

/**
 * BrandLockup: 徽标与字标的组合排版组件
 */
export const BrandLockup: React.FC<BrandLockupProps> = ({
  size = "md",
  collapsed = false,
  className,
  ...props
}) => {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-3",
        collapsed && "justify-center gap-0",
        className,
      )}
      role="img"
      aria-label="Book keeper"
      {...props}
    >
      <BrandMark size={size} />
      {!collapsed && (
        <div className="min-w-0 overflow-hidden">
          <BrandWordmark size={size} />
        </div>
      )}
    </div>
  );
};
