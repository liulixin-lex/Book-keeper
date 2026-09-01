import React, { useEffect, useRef, useState } from "react";
import {
  ArrowCircleDown,
  ArrowCircleUp,
  ArrowClockwise,
  ChartLineUp,
  Check,
  CheckSquareOffset,
  CloudArrowUp,
  Folder,
  GearSix,
  List,
  Monitor,
  Moon,
  Robot,
  Scroll,
  SignOut,
  SlidersHorizontal,
  Sun,
  UserCircle,
  Users,
} from "@phosphor-icons/react";
import { BrandLockup, BrandMark } from "../brand/Brand";
import { useAuth } from "../../context/AuthContext";
import { type ThemePreference, useTheme } from "../../context/ThemeContext";

export type NavItemKey =
  | "overview"
  | "income-records"
  | "expense-records"
  | "ai-chat"
  | "ai-providers"
  | "ai-workspace"
  | "approvals"
  | "subscriptions"
  | "catalog"
  | "users"
  | "profile"
  | "audit"
  | "backups";

interface LayoutProps {
  currentTab: NavItemKey;
  onSelectTab: (tab: NavItemKey) => void;
  children: React.ReactNode;
}

interface NavGroupItem {
  key: NavItemKey;
  label: string;
  icon: React.ComponentType<{
    size?: number | string;
    weight?: "regular" | "bold";
    className?: string;
  }>;
  adminOnly?: boolean;
}

interface NavGroup {
  title: string;
  items: NavGroupItem[];
}

const pageTitles: Record<NavItemKey, string> = {
  overview: "经营与现金总览",
  "income-records": "收入明细",
  "expense-records": "支出明细",
  "ai-chat": "AI 记账与查询",
  "ai-providers": "AI 供应商管理",
  "ai-workspace": "工作区 AI 提示词与设置",
  approvals: "审批中心",
  subscriptions: "订阅扣费管理",
  catalog: "主数据配置",
  users: "用户与邀请",
  profile: "个人资料",
  audit: "审计日志",
  backups: "数据备份",
};

const themeOptions: Array<{
  value: ThemePreference;
  label: string;
  icon: React.ComponentType<{
    size?: number | string;
    weight?: "regular" | "bold";
    className?: string;
  }>;
}> = [
  { value: "light", label: "亮色模式", icon: Sun },
  { value: "dark", label: "暗色模式", icon: Moon },
  { value: "system", label: "跟随系统", icon: Monitor },
];

export const Layout: React.FC<LayoutProps> = ({
  currentTab,
  onSelectTab,
  children,
}) => {
  const { user, logout } = useAuth();
  const { theme, resolvedTheme, setTheme } = useTheme();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isThemeMenuOpen, setIsThemeMenuOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(min-width: 1024px)").matches
      : true,
  );
  const themeTriggerRef = useRef<HTMLButtonElement | null>(null);
  const themeMenuRef = useRef<HTMLDivElement | null>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const asideRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 1024px)");
    const handler = (e: MediaQueryListEvent) => {
      setIsDesktop(e.matches);
      if (e.matches) {
        setIsMobileMenuOpen(false);
      }
    };
    mediaQuery.addEventListener("change", handler);
    return () => mediaQuery.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    if (isDesktop || !isMobileMenuOpen) return;

    // Focus current navigation item or first button inside aside
    const activeItem = asideRef.current?.querySelector<HTMLElement>(
      'button[aria-current="page"]',
    );
    if (activeItem) {
      activeItem.focus();
    } else {
      const firstFocusable =
        asideRef.current?.querySelector<HTMLElement>("button");
      firstFocusable?.focus();
    }

    const FOCUSABLE_SELECTOR =
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsMobileMenuOpen(false);
        mobileMenuButtonRef.current?.focus();
        return;
      }

      if (event.key === "Tab" && asideRef.current) {
        const focusables =
          asideRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
        if (focusables.length === 0) {
          event.preventDefault();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];

        if (event.shiftKey) {
          if (
            document.activeElement === first ||
            !asideRef.current.contains(document.activeElement)
          ) {
            event.preventDefault();
            last.focus();
          }
        } else {
          if (
            document.activeElement === last ||
            !asideRef.current.contains(document.activeElement)
          ) {
            event.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isMobileMenuOpen, isDesktop]);

  const navGroups: NavGroup[] = [
    {
      title: "日常记账与分析",
      items: [
        { key: "overview", label: "经营总览", icon: ChartLineUp },
        { key: "income-records", label: "收入明细", icon: ArrowCircleDown },
        { key: "expense-records", label: "支出明细", icon: ArrowCircleUp },
        { key: "subscriptions", label: "订阅管理", icon: ArrowClockwise },
      ],
    },
    {
      title: "AI 智能工作台",
      items: [
        { key: "ai-chat", label: "AI 记账", icon: Robot },
        {
          key: "ai-providers",
          label: "AI 供应商配置",
          icon: SlidersHorizontal,
          adminOnly: true,
        },
        {
          key: "ai-workspace",
          label: "账本 AI 指令",
          icon: GearSix,
          adminOnly: true,
        },
      ],
    },
    {
      title: "管理与审计",
      items: [
        { key: "approvals", label: "审批中心", icon: CheckSquareOffset },
        { key: "catalog", label: "主数据管理", icon: Folder },
        { key: "profile", label: "个人资料", icon: UserCircle },
        { key: "users", label: "成员权限", icon: Users, adminOnly: true },
        {
          key: "backups",
          label: "数据备份",
          icon: CloudArrowUp,
          adminOnly: true,
        },
        { key: "audit", label: "审计日志", icon: Scroll, adminOnly: true },
      ],
    },
  ];

  useEffect(() => {
    if (!isThemeMenuOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node | null;
      if (
        themeMenuRef.current &&
        !themeMenuRef.current.contains(target) &&
        themeTriggerRef.current &&
        !themeTriggerRef.current.contains(target)
      ) {
        setIsThemeMenuOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsThemeMenuOpen(false);
        themeTriggerRef.current?.focus();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isThemeMenuOpen]);

  const handleNavClick = (key: NavItemKey) => {
    onSelectTab(key);
    if (isMobileMenuOpen) {
      setIsMobileMenuOpen(false);
      mobileMenuButtonRef.current?.focus();
    }
  };

  const userInitial = user?.username?.charAt(0) || "U";
  const roleText =
    user?.role === "admin"
      ? "管理员"
      : user?.role === "bookkeeper"
        ? "记账员"
        : "只读";

  return (
    <div className="min-h-[100dvh] bg-bg p-0 text-ink md:p-2">
      <div className="app-shell flex h-[100dvh] w-full overflow-hidden md:h-[calc(100dvh-16px)]">
        {isMobileMenuOpen && (
          <button
            type="button"
            aria-label="关闭导航菜单"
            className="fixed inset-0 z-40 bg-ink/25 backdrop-blur-xs lg:hidden"
            onClick={() => {
              setIsMobileMenuOpen(false);
              mobileMenuButtonRef.current?.focus();
            }}
          />
        )}

        <aside
          ref={asideRef}
          id="primary-navigation"
          aria-label="主导航"
          aria-hidden={!isDesktop && !isMobileMenuOpen ? true : undefined}
          inert={!isDesktop && !isMobileMenuOpen ? true : undefined}
          className={`fixed inset-y-0 left-0 z-50 flex w-[280px] shrink-0 flex-col border-r border-border bg-surface/80 backdrop-blur-md transition-transform duration-200 lg:static lg:w-[76px] lg:translate-x-0 xl:w-[248px] ${
            isMobileMenuOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex h-16 shrink-0 items-center border-b border-border/70 px-4 lg:justify-center xl:justify-start xl:px-5">
            <div className="hidden lg:block xl:hidden">
              <BrandMark size="md" />
            </div>
            <div className="block lg:hidden xl:block">
              <BrandLockup size="md" />
            </div>
          </div>

          <nav className="flex-1 space-y-5 overflow-y-auto px-2 py-4 xl:px-3">
            {navGroups.map((group) => {
              const filteredItems = group.items.filter(
                (item) => !item.adminOnly || user?.role !== "viewer",
              );
              if (!filteredItems.length) return null;

              return (
                <div key={group.title} className="space-y-1">
                  <div className="mb-2 hidden truncate px-3 text-[11px] font-medium text-muted xl:block">
                    {group.title}
                  </div>
                  {filteredItems.map((item) => {
                    const Icon = item.icon;
                    const isActive = currentTab === item.key;
                    return (
                      <button
                        key={item.key}
                        type="button"
                        title={item.label}
                        aria-current={isActive ? "page" : undefined}
                        onClick={() => handleNavClick(item.key)}
                        className={`group flex w-full cursor-pointer items-center justify-start gap-3 rounded-lg px-3 py-2 text-left text-xs font-medium transition-[background-color,color,box-shadow] duration-140 lg:justify-center xl:justify-start ${
                          isActive
                            ? "bg-gradient-to-r from-primary to-[color-mix(in_oklch,var(--primary)_80%,var(--secondary))] font-semibold text-primary-ink shadow-[inset_0_1px_0_rgb(255_255_255_/_0.4),0_4px_12px_-4px_color-mix(in_oklch,var(--primary)_40%,transparent)]"
                            : "text-muted hover:bg-surface-raised/80 hover:text-ink"
                        }`}
                      >
                        <Icon
                          size={18}
                          weight={isActive ? "bold" : "regular"}
                          className="nav-item-icon shrink-0"
                        />
                        <span className="truncate lg:hidden xl:inline">
                          {item.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </nav>

          <div className="shrink-0 border-t border-border/70 bg-surface-strong/30 p-3">
            <div className="flex items-center gap-2.5 lg:justify-center xl:justify-start">
              <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-raised text-xs font-semibold text-ink">
                {userInitial}
              </div>
              <div className="min-w-0 overflow-hidden text-left lg:hidden xl:block">
                <div className="truncate text-xs font-medium text-ink">
                  {user?.username || "未知用户"}
                </div>
                <div className="truncate text-[10px] text-muted">
                  {roleText}
                </div>
              </div>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <header className="z-30 flex h-16 shrink-0 items-center justify-between border-b border-border bg-surface/75 backdrop-blur-md px-3 sm:px-4 lg:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <button
                ref={mobileMenuButtonRef}
                type="button"
                onClick={() => setIsMobileMenuOpen(true)}
                aria-label="打开导航菜单"
                aria-controls="primary-navigation"
                aria-expanded={isMobileMenuOpen}
                className="instrument-control shrink-0 p-2 lg:hidden"
              >
                <List size={20} className="nav-item-icon" />
              </button>
              <h2 className="truncate text-sm font-semibold text-ink sm:text-base">
                {pageTitles[currentTab]}
              </h2>
            </div>

            <div className="flex shrink-0 items-center gap-2 sm:gap-3">
              <div className="hidden items-center gap-1.5 text-xs text-muted sm:flex">
                <span className="size-2 rounded-full bg-success shadow-[0_0_8px_var(--success)]" />
                <span>在线</span>
              </div>

              <div className="relative">
                <button
                  ref={themeTriggerRef}
                  type="button"
                  onClick={() => setIsThemeMenuOpen((current) => !current)}
                  aria-haspopup="menu"
                  aria-expanded={isThemeMenuOpen}
                  aria-label="切换主题偏好"
                  title="切换主题偏好"
                  className="instrument-control p-2"
                >
                  {resolvedTheme === "dark" ? (
                    <Moon size={18} className="nav-item-icon" />
                  ) : (
                    <Sun size={18} className="nav-item-icon" />
                  )}
                </button>

                {isThemeMenuOpen && (
                  <div
                    ref={themeMenuRef}
                    role="menu"
                    aria-label="外观设置"
                    className="instrument-panel-raised absolute right-0 top-full z-50 mt-2 w-36 p-1"
                  >
                    {themeOptions.map((option) => {
                      const Icon = option.icon;
                      const isSelected = theme === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          role="menuitemradio"
                          aria-checked={isSelected}
                          onClick={() => {
                            setTheme(option.value);
                            setIsThemeMenuOpen(false);
                            themeTriggerRef.current?.focus();
                          }}
                          className={`flex w-full items-center justify-between rounded-md px-2.5 py-2 text-left text-xs font-medium transition-colors ${
                            isSelected
                              ? "bg-primary text-primary-ink"
                              : "text-muted hover:bg-surface-strong hover:text-ink"
                          }`}
                        >
                          <span className="flex items-center gap-2">
                            <Icon size={16} />
                            {option.label}
                          </span>
                          {isSelected && <Check size={14} weight="bold" />}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="hidden min-w-0 items-center gap-2 border-l border-border/70 pl-3 md:flex">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-raised text-xs font-semibold text-ink">
                  {userInitial}
                </div>
                <div className="hidden min-w-0 lg:block">
                  <div className="max-w-28 truncate text-xs font-medium text-ink">
                    {user?.username}
                  </div>
                  <div className="text-[10px] text-muted">{roleText}</div>
                </div>
              </div>

              <button
                type="button"
                onClick={logout}
                title="退出登录"
                aria-label="退出登录"
                className="instrument-control p-2 hover:text-danger"
              >
                <SignOut size={18} className="nav-item-icon" />
              </button>
            </div>
          </header>

          <main className="flex-1 overflow-y-auto bg-transparent p-3 focus:outline-none sm:p-4 lg:p-5">
            <div className="mx-auto max-w-[1600px]">{children}</div>
          </main>
        </div>
      </div>
    </div>
  );
};
