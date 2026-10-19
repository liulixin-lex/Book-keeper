/**
 * UI kit. Capsules for controls, 12px fields, 20px cards and sheets; lime only on the primary action and the current selection.
 * Every control has hover, focus, pressed, disabled and loading states.
 */
import {
  createContext,
  forwardRef,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import gsap from "gsap";
import { CalendarBlank, CaretDown, CaretRight, CircleNotch, X } from "@phosphor-icons/react";

export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- buttons ---------- */

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const BUTTON: Record<Variant, string> = {
  primary: "bg-lime text-lime-ink font-semibold hover:bg-lime-hover",
  secondary: "bg-well text-ink font-medium hover:bg-well-2",
  ghost: "bg-transparent text-ink-2 font-medium hover:bg-well hover:text-ink",
  danger: "bg-transparent text-neg font-medium hover:bg-neg-wash",
};

const SIZE: Record<Size, string> = {
  sm: "h-8 px-3.5 text-sm gap-1.5",
  md: "h-10 px-4.5 text-base gap-2",
  lg: "h-12 px-6 text-md gap-2",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
  kbd?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, kbd, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={clsx(
        "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-full transition-[background-color,color,transform,opacity] duration-150 active:scale-[0.97] disabled:opacity-45 disabled:active:scale-100",
        SIZE[size],
        BUTTON[variant],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <CircleNotch className="animate-spin" size={size === "sm" ? 14 : 16} /> : icon}
      {children}
      {kbd && <kbd className="ml-0.5 rounded-md bg-black/[0.06] px-1.5 font-sans text-xs leading-5 font-medium opacity-80">{kbd}</kbd>}
    </button>
  );
});

export function IconButton({ label, className, children, type = "button", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={clsx(
        "inline-grid size-9 shrink-0 place-items-center rounded-full text-ink-2 transition-[background-color,color,transform] duration-150 hover:bg-well hover:text-ink active:scale-95 disabled:opacity-40",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ---------- fields ---------- */

const CONTROL =
  "w-full rounded-field border border-line-strong bg-card px-3.5 text-base text-ink placeholder:text-ink-3 transition-[border-color,box-shadow,background-color] duration-150 hover:border-ink-3/60 focus:border-pos focus:shadow-[0_0_0_3px_var(--lime-wash)] focus:outline-none disabled:bg-well disabled:text-ink-3 aria-invalid:border-neg aria-invalid:focus:shadow-[0_0_0_3px_var(--neg-wash)]";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={clsx(CONTROL, "h-10", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={clsx(CONTROL, "min-h-20 py-2.5", className)} {...rest} />;
});

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...rest }, ref) {
  return (
    <span className={clsx("relative block", className)}>
      <select ref={ref} className={clsx(CONTROL, "h-10 appearance-none pr-9")} {...rest}>
        {children}
      </select>
      <CaretDown aria-hidden size={14} className="pointer-events-none absolute top-1/2 right-3.5 -translate-y-1/2 text-ink-3" />
    </span>
  );
});

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: (id: string, describedBy: string | undefined) => ReactNode;
  className?: string;
}

/** Label above, control, then hint or error below. */
export function Field({ label, hint, error, required, children, className }: FieldProps) {
  const id = useId();
  const note = error || hint ? `${id}-note` : undefined;
  return (
    <div className={clsx("grid content-start gap-1.5", className)}>
      <label htmlFor={id} className="text-sm font-medium text-ink-2">
        {label}
        {required && <span className="ml-0.5 text-neg">*</span>}
      </label>
      {children(id, note)}
      {(error || hint) && (
        <p id={note} className={clsx("text-sm", error ? "text-neg" : "text-ink-3")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

/* ---------- selection ---------- */

interface SegmentedProps<T extends string> {
  value: T;
  options: { value: T; label: ReactNode; count?: number }[];
  onChange: (v: T) => void;
  label: string;
  size?: "sm" | "md";
  className?: string;
}

/** Capsule segmented control; the white thumb slides to the chosen segment. */
export function Segmented<T extends string>({ value, options, onChange, label, size = "md", className }: SegmentedProps<T>) {
  const track = useRef<HTMLDivElement>(null);
  const thumb = useRef<HTMLSpanElement>(null);
  const placed = useRef(false);

  useLayoutEffect(() => {
    const t = track.current;
    const th = thumb.current;
    if (!t || !th) return;
    const place = () => {
      const btn = t.querySelector<HTMLElement>(`[data-value="${CSS.escape(value)}"]`);
      if (!btn) {
        th.style.opacity = "0";
        return;
      }
      th.style.opacity = "1";
      th.style.width = `${btn.offsetWidth}px`;
      th.style.transform = `translateX(${btn.offsetLeft}px)`;
    };
    if (!placed.current) {
      th.style.transition = "none";
      place();
      void th.offsetWidth;
      th.style.transition = "";
      placed.current = true;
    } else place();
    const ro = new ResizeObserver(place);
    ro.observe(t);
    return () => ro.disconnect();
  }, [value, options.length]);

  return (
    <div ref={track} role="radiogroup" aria-label={label} className={clsx("relative inline-flex rounded-full bg-well p-1", className)}>
      <span ref={thumb} aria-hidden className="absolute top-1 bottom-1 left-0 rounded-full bg-card shadow-lift transition-[transform,width] duration-300 ease-[var(--ease-out-expo)]" />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          data-value={o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "relative z-[1] inline-flex flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-full transition-colors duration-150",
            size === "md" ? "h-8 px-4 text-sm" : "h-7 px-3 text-sm",
            o.value === value ? "font-semibold text-ink" : "font-medium text-ink-2 hover:text-ink",
          )}
        >
          {o.label}
          {o.count !== undefined && o.count > 0 && <span className="num text-xs text-ink-3">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Filter or option capsule; on = lime. */
export function Chip({ on, onClick, children, className, ...rest }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={rest.role === "radio" ? undefined : on}
      onClick={onClick}
      className={clsx(
        "inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3.5 text-sm transition-[background-color,color,transform] duration-150 active:scale-[0.96]",
        on ? "bg-lime font-semibold text-lime-ink" : "bg-well font-medium text-ink-2 hover:bg-well-2 hover:text-ink",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

type Tone = "neutral" | "pos" | "neg" | "warn";
const TONE: Record<Tone, string> = {
  neutral: "bg-well text-ink-2",
  pos: "bg-pos-wash text-pos",
  neg: "bg-neg-wash text-neg",
  warn: "bg-warn-wash text-warn-text",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={clsx("inline-flex h-5.5 shrink-0 items-center whitespace-nowrap rounded-full px-2 text-xs font-medium", TONE[tone], className)}>{children}</span>;
}

/** iOS-style switch for on/off settings. */
export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx("relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors duration-200 disabled:opacity-45", checked ? "bg-lime" : "bg-well-2")}
    >
      <span className={clsx("absolute left-0.5 size-6 rounded-full bg-white shadow-lift transition-transform duration-300 ease-[var(--ease-out-expo)]", checked && "translate-x-5")} />
    </button>
  );
}

/* ---------- containers ---------- */

export function Card({
  children,
  className,
  as: As = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
  "aria-label"?: string;
  "aria-labelledby"?: string;
}) {
  return (
    <As className={clsx("min-w-0 rounded-card bg-card shadow-card", className)} {...rest}>
      {children}
    </As>
  );
}

export function CardHeader({ title, action, id, className }: { title: ReactNode; action?: ReactNode; id?: string; className?: string }) {
  return (
    <header className={clsx("flex min-h-8 items-center justify-between gap-3", className)}>
      <h2 id={id} className="text-md font-semibold">
        {title}
      </h2>
      {action}
    </header>
  );
}

export function PageHeader({ title, badge, children }: { title: string; badge?: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-6 flex min-h-10 flex-wrap items-center justify-between gap-x-4 gap-y-3 max-lg:mb-5">
      <div className="flex min-w-0 items-center gap-3">
        <h1 className="truncate text-xl font-semibold tracking-[-0.02em]">{title}</h1>
        {badge}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}

/** Settings-style row: label left, value right, optional chevron. */
export function Row({ label, children, onClick, className }: { label: ReactNode; children?: ReactNode; onClick?: () => void; className?: string }) {
  const body = (
    <>
      <span className="shrink-0 text-ink-2">{label}</span>
      <span className="min-w-0 flex-1 truncate text-right">{children}</span>
      {onClick && <CaretRight size={14} className="shrink-0 text-ink-3" />}
    </>
  );
  const cls = clsx("flex min-h-12 w-full items-center gap-4 py-3 text-left", className);
  return onClick ? (
    <button type="button" onClick={onClick} className={clsx(cls, "-mx-2 rounded-field px-2 transition-colors duration-150 hover:bg-well")}>
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** Progressive blur at a scroll edge (see .blur-edge in index.css); `on` fades it in only when content is under it. */
export function BlurEdge({ edge, on = true, className, tint }: { edge: "top" | "bottom"; on?: boolean; className?: string; tint?: string }) {
  return (
    <div aria-hidden data-edge={edge} data-on={on} className={clsx("blur-edge", className)} style={tint ? ({ "--edge-tint": tint } as React.CSSProperties) : undefined}>
      <i />
      <i />
      <i />
      <i />
      <i />
      <i />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden className={clsx("skeleton block rounded-[10px]", className)} />;
}

export function Empty({ icon, title, children, action, className }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={clsx("grid justify-items-center gap-2 px-6 py-12 text-center", className)}>
      {icon && <div className="mb-1 grid size-12 place-items-center rounded-full bg-well text-ink-2">{icon}</div>}
      <p className="text-md font-semibold">{title}</p>
      {/* Phrase-level wrapping: break at punctuation, never inside a word like 补全; balanced lines. */}
      {children && <p className="max-w-[40ch] text-sm text-balance break-keep wrap-anywhere text-ink-2">{children}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const message = error instanceof Error ? error.message : "加载失败：网络或服务暂时不可用。请稍后重试。";
  return (
    <div role="alert" className={clsx("flex items-center justify-between gap-3 rounded-field bg-neg-wash px-4 py-3 text-sm text-neg", className)}>
      <span>{message}</span>
      {onRetry && (
        <Button size="sm" variant="ghost" onClick={onRetry} className="text-neg">
          重试
        </Button>
      )}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="rounded-md bg-well px-1.5 font-sans text-xs leading-5 font-medium text-ink-2">{children}</kbd>;
}

/* ---------- overlays ---------- */

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatch(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  /** Accessible name when the title is not plain text. */
  label?: string;
  icon?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  width?: number;
}

const SheetFooterSlot = createContext<HTMLElement | null>(null);

/** Actions pinned to the bottom of the sheet, outside its scrolling body (rendered through a portal). */
export function SheetFooter({ children }: { children: ReactNode }) {
  const slot = useContext(SheetFooterSlot);
  return slot ? createPortal(children, slot) : null;
}

/**
 * The one overlay: a native <dialog> (focus trap, Esc, inert page) holding a floating card.
 * Desktop: slides in from the right. Phone: rises from the bottom. Content unmounts after the exit, so forms reset.
 */
export function Sheet({ open, onClose, title, label, icon, subtitle, children, width = 480 }: SheetProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(open);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  const measure = () => {
    const el = body.current;
    if (!el) return;
    const top = el.scrollTop > 2;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight > 2;
    setEdges((e) => (e.top === top && e.bottom === bottom ? e : { top, bottom }));
  };
  useEffect(() => {
    const el = body.current;
    if (!el || !mounted) return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    if (el.firstElementChild) ro.observe(el.firstElementChild);
    measure();
    return () => ro.disconnect();
  }, [mounted]); // eslint-disable-line react-hooks/exhaustive-deps
  const phone = useMedia("(max-width: 639px)");
  const titleId = useId();

  if (open && !mounted) setMounted(true);

  useLayoutEffect(() => {
    const d = dialog.current;
    const p = panel.current;
    if (!d || !p || !mounted) return;
    gsap.killTweensOf(p);
    if (open) {
      d.removeAttribute("data-closing");
      if (!d.open) d.showModal();
      if (reducedMotion()) gsap.set(p, { clearProps: "transform,opacity" });
      else
        gsap.fromTo(p, phone ? { yPercent: 100 } : { x: 48, opacity: 0, filter: "blur(6px)" }, {
          yPercent: 0,
          x: 0,
          opacity: 1,
          filter: "blur(0px)",
          duration: phone ? 0.5 : 0.45,
          ease: "expo.out",
          clearProps: "transform,opacity,filter",
        });
    } else if (d.open) {
      d.setAttribute("data-closing", "");
      const done = () => {
        d.close();
        setMounted(false);
      };
      if (reducedMotion()) done();
      else gsap.to(p, { ...(phone ? { yPercent: 100 } : { x: 36, opacity: 0 }), duration: 0.2, ease: "power2.in", onComplete: done });
    }
  }, [open, mounted, phone]);

  if (!mounted) return null;
  return (
    <dialog
      ref={dialog}
      aria-labelledby={label ? undefined : titleId}
      aria-label={label}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => e.target === dialog.current && onClose()}
      className="sheet fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-hidden bg-transparent p-0 text-ink"
    >
      <div
        ref={panel}
        className={clsx(
          "absolute flex flex-col overflow-hidden bg-card shadow-pop",
          phone ? "inset-x-0 bottom-0 max-h-[94dvh] rounded-t-[24px] pb-[env(safe-area-inset-bottom)]" : "top-3 right-3 bottom-3 rounded-card",
        )}
        style={phone ? undefined : { width: `min(${width}px, calc(100vw - 24px))` }}
      >
        {phone && <span aria-hidden className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-line-strong" />}
        <header className="flex shrink-0 items-start gap-3 px-6 pt-5 pb-3 max-sm:px-5 max-sm:pt-3">
          {icon}
          <div className="min-w-0 flex-1 self-center">
            <h2 id={titleId} className="truncate text-lg font-semibold tracking-[-0.01em]">
              {title}
            </h2>
            {subtitle && <div className="mt-0.5 text-sm text-ink-2">{subtitle}</div>}
          </div>
          <IconButton label="关闭" onClick={onClose} className="-mt-0.5 -mr-2 bg-well">
            <X size={16} weight="bold" />
          </IconButton>
        </header>
        <SheetFooterSlot.Provider value={slot}>
          <div className="relative min-h-0 flex-1">
            <div ref={body} onScroll={measure} className="h-full overflow-y-auto overscroll-contain px-6 pb-6 max-sm:px-5">
              {children}
            </div>
            <BlurEdge edge="top" on={edges.top} tint="color-mix(in oklch, var(--card) 85%, transparent)" className="absolute inset-x-0 top-0 h-6" />
            <BlurEdge edge="bottom" on={edges.bottom} tint="color-mix(in oklch, var(--card) 85%, transparent)" className="absolute inset-x-0 bottom-0 h-8" />
          </div>
        </SheetFooterSlot.Provider>
        <footer ref={setSlot} className="shrink-0 border-t border-line px-6 py-4 empty:hidden max-sm:px-5" />
      </div>
    </dialog>
  );
}

/* ---------- date & time ---------- */

type ValueEvent = { target: { value: string } };
type TextProps = Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value" | "type"> & { value: string; onChange: (e: ValueEvent) => void };

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Accepts 2026-10-19, 2026/10/19, 2026.10.19 or 20261019; returns YYYY-MM-DD or null. */
export function normalizeDate(input: string): string | null {
  const s = input
    .trim()
    .replace(/[/.年月]/g, "-")
    .replace(/日$/, "");
  const compact = /^(\d{4})(\d{2})(\d{2})$/.exec(s);
  const m = compact ?? /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
  if (!m) return null;
  const iso = `${m[1]}-${m[2]!.padStart(2, "0")}-${m[3]!.padStart(2, "0")}`;
  const d = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === iso ? iso : null;
}

/** Accepts 9:42, 0942 or 942; returns HH:mm (24-hour) or null. */
export function normalizeTime(input: string): string | null {
  const s = input.trim().replace("：", ":");
  const m = /^(\d{1,2}):?(\d{2})$/.exec(s);
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  return h < 24 && min < 60 ? `${String(h).padStart(2, "0")}:${m[2]}` : null;
}

/** Date field that always shows YYYY-MM-DD, with the native calendar one click away. */
export function DateInput({ value, onChange, className, ...rest }: TextProps) {
  const [draft, setDraft] = useState(value);
  const picker = useRef<HTMLInputElement>(null);
  useEffect(() => setDraft(value), [value]);
  const commit = (raw: string) => {
    const iso = raw.trim() ? normalizeDate(raw) : "";
    if (iso !== null) {
      setDraft(iso);
      if (iso !== value) onChange({ target: { value: iso } });
    }
  };
  return (
    <span className={clsx("relative block", className)}>
      <input
        {...rest}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder={rest.placeholder ?? "YYYY-MM-DD"}
        value={draft}
        aria-invalid={rest["aria-invalid"] ?? (draft !== "" && !ISO_DATE.test(draft) && normalizeDate(draft) === null)}
        onChange={(e) => {
          setDraft(e.target.value);
          const iso = normalizeDate(e.target.value);
          if (iso && iso !== value && e.target.value.length >= 8) onChange({ target: { value: iso } });
        }}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && commit((e.target as HTMLInputElement).value)}
        className={clsx(CONTROL, "num h-10 pr-11")}
      />
      <button
        type="button"
        tabIndex={-1}
        aria-label="打开日历"
        onClick={() => picker.current?.showPicker?.()}
        className="absolute top-1/2 right-1.5 grid size-8 -translate-y-1/2 place-items-center rounded-full text-ink-3 hover:bg-well hover:text-ink"
      >
        <CalendarBlank size={16} />
      </button>
      <input
        ref={picker}
        type="date"
        tabIndex={-1}
        aria-hidden
        value={ISO_DATE.test(value) ? value : ""}
        onChange={(e) => e.target.value && onChange({ target: { value: e.target.value } })}
        className="pointer-events-none absolute right-0 bottom-0 size-0 opacity-0"
      />
    </span>
  );
}

/** 24-hour HH:mm field; empty means “no time”. */
export function TimeInput({ value, onChange, className, ...rest }: TextProps) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = (raw: string) => {
    const t = raw.trim() ? normalizeTime(raw) : "";
    if (t !== null) {
      setDraft(t);
      if (t !== value) onChange({ target: { value: t } });
    }
  };
  return (
    <input
      {...rest}
      type="text"
      inputMode="numeric"
      autoComplete="off"
      placeholder={rest.placeholder ?? "如 09:42"}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={(e) => commit(e.target.value)}
      aria-invalid={draft !== "" && normalizeTime(draft) === null}
      className={clsx(CONTROL, "num h-10", className)}
    />
  );
}
