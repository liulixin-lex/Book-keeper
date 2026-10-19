/** App shell. Desktop: a 232px sidebar on the ground with the lime 记一笔 capsule and five modules. Phone: bottom tabs with a raised ＋. */
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { clsx } from "clsx";
import { ChartBar, DotsThreeCircle, GearSix, House, Monitor, Moon, Plus, Receipt, SignOut, Sun, Tray, type Icon } from "@phosphor-icons/react";
import { api } from "@/api/client";
import { queryClient, useImportBacklog, useMe } from "@/api/queries";
import { BlurEdge, IconButton } from "@/components/ui";
import { useEntry } from "@/features/entry/EntryProvider";
import { setThemePref, themePref, type ThemePref } from "./theme";

const NAV: { to: string; label: string; icon: Icon }[] = [
  { to: "/overview", label: "概览", icon: House },
  { to: "/transactions", label: "交易", icon: Receipt },
  { to: "/stats", label: "统计", icon: ChartBar },
  { to: "/imports", label: "导入", icon: Tray },
  { to: "/settings", label: "设置", icon: GearSix },
];

export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={className}>
      <rect width="32" height="32" rx="10" fill="var(--mark)" />
      <rect x="8" y="17" width="4" height="7" rx="2" fill="#fff" />
      <rect x="14" y="13" width="4" height="11" rx="2" fill="#fff" />
      <rect x="20" y="8" width="4" height="16" rx="2" fill="#fff" />
    </svg>
  );
}

export function ThemeSwitch() {
  const [pref, setPref] = useState<ThemePref>(themePref());
  const options: { value: ThemePref; label: string; icon: Icon }[] = [
    { value: "system", label: "跟随系统", icon: Monitor },
    { value: "light", label: "浅色", icon: Sun },
    { value: "dark", label: "深色", icon: Moon },
  ];
  return (
    <div role="radiogroup" aria-label="外观" className="inline-flex rounded-full bg-well p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={pref === o.value}
          title={o.label}
          aria-label={o.label}
          onClick={() => {
            setThemePref(o.value);
            setPref(o.value);
          }}
          className={clsx("grid size-7 place-items-center rounded-full transition-colors duration-150", pref === o.value ? "bg-card text-ink shadow-lift" : "text-ink-3 hover:text-ink")}
        >
          <o.icon size={15} weight={pref === o.value ? "fill" : "regular"} />
        </button>
      ))}
    </div>
  );
}

export async function signOut(navigate: (to: string, opts?: { replace?: boolean }) => void) {
  await api.post("/auth/logout").catch(() => undefined);
  queryClient.clear();
  navigate("/login", { replace: true });
}

/** True once the page has scrolled, so the top blur only appears when there is content under it. */
function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 4);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return scrolled;
}

export function Shell() {
  const me = useMe().data;
  const entry = useEntry();
  const navigate = useNavigate();
  const backlog = useImportBacklog().count;
  const scrolled = useScrolled();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.metaKey || e.ctrlKey || e.altKey || t.closest("input,textarea,select,[contenteditable],dialog")) return;
      if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        entry.open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [entry]);

  const name = me?.user.display_name ?? "";

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-dvh flex-col px-4 py-6 lg:flex">
        <div className="flex items-center gap-2.5 px-4">
          <Mark className="size-8" />
          <span className="text-md font-semibold tracking-[-0.01em]">账本</span>
        </div>

        <button
          type="button"
          onClick={() => entry.open()}
          className="mt-7 flex h-11 items-center justify-between rounded-full bg-lime pr-2.5 pl-4 font-semibold text-lime-ink transition-[background-color,transform] duration-150 hover:bg-lime-hover active:scale-[0.98]"
        >
          <span className="flex items-center gap-3">
            <Plus size={20} weight="bold" />
            记一笔
          </span>
          <kbd className="rounded-md bg-lime-ink/10 px-1.5 font-sans text-xs leading-5 font-semibold">N</kbd>
        </button>

        <nav aria-label="主导航" className="mt-6 grid gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                clsx(
                  "flex h-10 items-center gap-3 rounded-full px-4 text-base transition-[background-color,color] duration-150",
                  isActive ? "bg-card font-semibold text-ink shadow-lift" : "font-medium text-ink-2 hover:bg-well hover:text-ink",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <item.icon size={20} weight={isActive ? "fill" : "regular"} />
                  <span className="flex-1">{item.label}</span>
                  {item.to === "/imports" && backlog > 0 && (
                    <span className="num grid h-5 min-w-5 place-items-center rounded-full bg-warn-wash px-1.5 text-xs font-semibold text-warn-text" aria-label={`${backlog} 项待处理`}>
                      {backlog}
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto grid gap-4">
          <ThemeSwitch />
          <div className="flex items-center gap-3 pl-4">
            <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-full bg-well text-sm font-semibold text-ink-2">
              {name.slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0 flex-1 truncate text-sm text-ink-2">{name}</span>
            <IconButton label="退出登录" onClick={() => signOut(navigate)}>
              <SignOut size={17} />
            </IconButton>
          </div>
        </div>
      </aside>

      <main className="min-w-0 px-4 pt-5 pb-[calc(112px+env(safe-area-inset-bottom))] sm:px-6 lg:px-10 lg:pt-5 lg:pb-12">
        <div className="mx-auto max-w-[1200px]">
          <Outlet />
        </div>
      </main>

      <BlurEdge edge="top" on={scrolled} className="fixed top-0 right-0 left-0 z-30 h-[calc(3.5rem+env(safe-area-inset-top))] lg:left-[232px] lg:h-16" />
      <BlurEdge edge="bottom" className="fixed inset-x-0 bottom-0 z-30 h-[calc(6.5rem+env(safe-area-inset-bottom))] lg:hidden" />
      <TabBar backlog={backlog} onAdd={() => entry.open()} />
    </div>
  );
}

function TabBar({ backlog, onAdd }: { backlog: number; onAdd: () => void }) {
  const tabs: { to: string; label: string; icon: Icon }[] = [
    { to: "/overview", label: "概览", icon: House },
    { to: "/transactions", label: "交易", icon: Receipt },
    { to: "/stats", label: "统计", icon: ChartBar },
    { to: "/more", label: "更多", icon: DotsThreeCircle },
  ];
  const tab = (t: (typeof tabs)[number]) => (
    <NavLink
      key={t.to}
      to={t.to}
      className={({ isActive }) => clsx("relative grid h-14 content-center justify-items-center gap-0.5 text-xs", isActive ? "font-semibold text-ink" : "font-medium text-ink-3")}
    >
      {({ isActive }) => (
        <>
          <t.icon size={24} weight={isActive ? "fill" : "regular"} />
          {t.label}
          {t.to === "/more" && backlog > 0 && <span aria-label={`导入有 ${backlog} 项待处理`} className="absolute top-1.5 left-1/2 ml-2 size-2 rounded-full bg-warn" />}
        </>
      )}
    </NavLink>
  );
  return (
    <nav aria-label="主导航" className="frost fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 pb-[env(safe-area-inset-bottom)] lg:hidden">
      {tabs.slice(0, 2).map(tab)}
      <div className="grid place-items-center">
        <button
          type="button"
          aria-label="记一笔"
          onClick={onAdd}
          className="-mt-5 grid size-14 place-items-center rounded-full bg-lime text-lime-ink shadow-pop transition-transform duration-150 active:scale-95"
        >
          <Plus size={26} weight="bold" />
        </button>
      </div>
      {tabs.slice(2).map(tab)}
    </nav>
  );
}
