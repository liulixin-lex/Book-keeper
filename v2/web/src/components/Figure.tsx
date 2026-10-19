/**
 * Rolling figures, the app's signature move: when a money figure changes (period switch, after a write) every digit
 * rolls to its new value (GSAP, ~600 ms, exponential ease-out, a small stagger from the leading digit).
 * Columns are keyed from the right, so cents stay put and new leading digits slide in. Screen readers get the plain text.
 */
import { useLayoutEffect, useRef } from "react";
import { clsx } from "clsx";
import gsap from "gsap";
import { reducedMotion } from "./ui";

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

function Digit({ value, order, arrive }: { value: number; order: number; arrive: boolean }) {
  const strip = useRef<HTMLSpanElement>(null);
  const first = useRef(true);

  useLayoutEffect(() => {
    const el = strip.current;
    if (!el) return;
    const target = -value * 10;
    if (first.current) {
      first.current = false;
      if (!arrive || reducedMotion()) {
        gsap.set(el, { yPercent: target });
        return;
      }
      gsap.fromTo(el, { yPercent: 0 }, { yPercent: target, duration: 0.9, ease: "expo.out", delay: 0.05 + order * 0.035 });
      return;
    }
    if (reducedMotion()) gsap.set(el, { yPercent: target });
    else gsap.to(el, { yPercent: target, duration: 0.62, ease: "expo.out", delay: order * 0.03, overwrite: true });
  }, [value, order, arrive]);

  return (
    <span className="relative inline-block h-[1.12em] overflow-hidden align-top">
      <span ref={strip} className="flex flex-col">
        {DIGITS.map((d) => (
          <span key={d} className="h-[1.12em] leading-[1.12em]">
            {d}
          </span>
        ))}
      </span>
    </span>
  );
}

/** A rolling copy of `text` (an already formatted figure such as "−¥1,234.56"). */
export function RollingText({ text, className, arrive = false, quiet = false }: { text: string; className?: string; arrive?: boolean; quiet?: boolean }) {
  const chars = [...text];
  let order = 0;
  return (
    <span className={clsx(quiet ? "num" : "figure", "inline-flex items-start leading-[1.12em] whitespace-nowrap", className)}>
      <span className="sr-only">{text}</span>
      <span aria-hidden className="inline-flex">
        {chars.map((c, i) => {
          const fromRight = chars.length - i;
          if (/\d/.test(c)) return <Digit key={`d${fromRight}`} value={Number(c)} order={order++} arrive={arrive} />;
          return (
            <span key={`s${fromRight}-${c}`} className="h-[1.12em]">
              {c}
            </span>
          );
        })}
      </span>
    </span>
  );
}
