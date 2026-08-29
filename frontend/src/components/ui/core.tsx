import React from "react";
import { CircleNotch } from "@phosphor-icons/react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  isLoading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      isLoading,
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    const baseStyles =
      "inline-flex items-center justify-center rounded-lg border font-medium transition-[background-color,border-color,color,transform,box-shadow] duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-45 select-none cursor-pointer active:translate-y-px active:scale-[0.98]";

    const variants = {
      primary:
        "border-primary/50 bg-gradient-to-r from-primary to-[color-mix(in_oklch,var(--primary)_85%,var(--secondary))] text-primary-ink shadow-[inset_0_1px_0_rgb(255_255_255_/_0.4),0_6px_16px_-8px_color-mix(in_oklch,var(--primary)_60%,transparent)] hover:brightness-105",
      secondary:
        "border-border bg-surface-strong/80 text-ink shadow-[var(--shadow-panel)] backdrop-blur-xs hover:border-border-strong hover:bg-surface-raised",
      outline:
        "border-border-strong bg-surface/70 text-ink backdrop-blur-xs hover:bg-surface-strong/90",
      danger:
        "border-danger/60 bg-danger text-[oklch(0.98_0.01_25)] shadow-[0_4px_14px_-6px_color-mix(in_oklch,var(--danger)_60%,transparent)] hover:brightness-105",
      ghost:
        "border-transparent bg-transparent text-muted shadow-none hover:bg-surface-strong/60 hover:text-ink",
    };

    const sizes = {
      sm: "h-8 px-3 text-xs gap-1.5",
      md: "h-9 px-4 text-sm gap-2",
      lg: "h-10 px-5 text-sm gap-2.5",
    };

    return (
      <button
        ref={ref}
        aria-busy={isLoading || undefined}
        disabled={disabled || isLoading}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        {...props}
      >
        {isLoading && (
          <CircleNotch
            size={size === "sm" ? 13 : size === "lg" ? 17 : 15}
            weight="bold"
            className="-ml-0.5 shrink-0 animate-spin"
          />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, helperText, id, ...props }, ref) => {
    const inputId =
      id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

    return (
      <div className="w-full space-y-1.5 text-left">
        {label && (
          <label
            htmlFor={inputId}
            className="block text-xs font-medium text-muted"
          >
            {label}
          </label>
        )}
        <input
          id={inputId}
          ref={ref}
          className={cn(
            "flex h-9 w-full rounded-lg border border-border bg-surface-inset px-3 py-1.5 text-sm text-ink shadow-[var(--shadow-inset)] placeholder:text-muted focus:border-primary focus:bg-surface focus:outline-none focus-visible:ring-1 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:bg-surface-strong disabled:opacity-50 transition-colors",
            error &&
              "border-danger focus:border-danger focus-visible:ring-danger/30",
            className,
          )}
          {...props}
        />
        {error && <p className="text-xs text-danger">{error}</p>}
        {helperText && !error && (
          <p className="text-xs text-muted">{helperText}</p>
        )}
      </div>
    );
  },
);
Input.displayName = "Input";

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, label, error, children, id, ...props }, ref) => {
    const selectId =
      id || (label ? label.toLowerCase().replace(/\s+/g, "-") : undefined);

    return (
      <div className="w-full space-y-1.5 text-left">
        {label && (
          <label
            htmlFor={selectId}
            className="block text-xs font-medium text-muted"
          >
            {label}
          </label>
        )}
        <select
          id={selectId}
          ref={ref}
          className={cn(
            "flex h-9 w-full rounded-lg border border-border bg-surface-inset px-3 py-1.5 text-sm text-ink shadow-[var(--shadow-inset)] focus:border-primary focus:bg-surface focus:outline-none focus-visible:ring-1 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:bg-surface-strong disabled:opacity-50 transition-colors",
            error &&
              "border-danger focus:border-danger focus-visible:ring-danger/30",
            className,
          )}
          {...props}
        >
          {children}
        </select>
        {error && <p className="text-xs text-danger">{error}</p>}
      </div>
    );
  },
);
Select.displayName = "Select";

export const Badge: React.FC<{
  children: React.ReactNode;
  variant?: "default" | "success" | "warning" | "danger" | "info";
  className?: string;
  title?: string;
}> = ({ children, variant = "default", className, title }) => {
  const styles = {
    default: "bg-surface-strong text-muted border-border",
    success: "bg-success/10 text-success border-success/30",
    warning: "bg-warning/15 text-warning border-warning/35",
    danger: "bg-danger/10 text-danger border-danger/30",
    info: "bg-primary/20 text-ink border-primary/40",
  };

  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border",
        styles[variant],
        className,
      )}
    >
      {children}
    </span>
  );
};
