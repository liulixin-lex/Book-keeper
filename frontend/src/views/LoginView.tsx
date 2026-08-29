import React, { useEffect, useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import {
  ArrowsLeftRight,
  BookOpenText,
  Monitor,
  Moon,
  ShieldCheck,
  Sun,
} from "@phosphor-icons/react";
import { BrandLockup } from "../components/brand/Brand";
import gsap from "gsap";
import { apiRequest } from "../api/client";
import { Button, Input, cn } from "../components/ui/core";
import { useAuth } from "../context/AuthContext";
import { useTheme, type ThemePreference } from "../context/ThemeContext";
import { useToast } from "../context/ToastContext";

type AuthMode = "login" | "register" | "bootstrap";

export const LoginView: React.FC = () => {
  const containerRef = useRef<HTMLDivElement>(null);
  const { login, bootstrap, register } = useAuth();
  const { theme, setTheme } = useTheme();
  const { error: toastError, success } = useToast();

  const [mode, setMode] = useState<AuthMode>("login");
  const [isChecking, setIsChecking] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [identifier, setIdentifier] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteToken, setInviteToken] = useState("");
  const [workspaceName, setWorkspaceName] = useState("默认账本工作区");

  useEffect(() => {
    apiRequest<{ initialized: boolean }>("/auth/status")
      .then(({ initialized }) => setMode(initialized ? "login" : "bootstrap"))
      .catch(() => setMode("login"))
      .finally(() => setIsChecking(false));
  }, []);

  useGSAP(
    () => {
      if (
        isChecking ||
        window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ) {
        return;
      }
      gsap.fromTo(
        containerRef.current,
        { opacity: 0, y: 10 },
        { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" },
      );
    },
    { scope: containerRef, dependencies: [isChecking] },
  );

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsLoading(true);
    try {
      if (mode === "login") {
        await login({ identifier, password });
        success("登录成功");
      } else if (mode === "register") {
        await register({
          username,
          email,
          password,
          token: inviteToken.trim(),
        });
        success("注册成功");
      } else {
        await bootstrap({
          username,
          email,
          password,
          workspace_name: workspaceName,
        });
        success("系统初始化完成");
      }
    } catch (error) {
      toastError(error instanceof Error ? error.message : "操作失败");
    } finally {
      setIsLoading(false);
    }
  };

  if (isChecking) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-bg p-4">
        <div className="instrument-panel skeleton-sheen h-96 w-full max-w-sm" />
      </div>
    );
  }

  const isBootstrap = mode === "bootstrap";
  const title = isBootstrap
    ? "初始化系统总账本"
    : mode === "register"
      ? "使用邀请令牌注册"
      : "登录 Book keeper";

  const themeOptions: Array<{
    value: ThemePreference;
    label: string;
    icon: React.ElementType;
  }> = [
    { value: "light", label: "亮色模式", icon: Sun },
    { value: "system", label: "跟随系统", icon: Monitor },
    { value: "dark", label: "暗色模式", icon: Moon },
  ];

  return (
    <div className="flex min-h-[100dvh] w-full items-center justify-center bg-bg p-4 md:p-6 lg:p-8">
      <div
        ref={containerRef}
        className="app-shell w-full max-w-[1120px] overflow-hidden"
      >
        {/* Top bar: Theme switcher */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3 md:px-7">
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-primary" />
            <span className="text-xs font-medium text-muted">安全访问</span>
          </div>

          <div
            role="group"
            aria-label="主题切换"
            className="instrument-inset flex items-center p-0.5"
          >
            {themeOptions.map(({ value, label, icon: Icon }) => {
              const isSelected = theme === value;
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={isSelected}
                  aria-label={label}
                  title={label}
                  onClick={() => setTheme(value)}
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-md text-xs font-medium transition-colors cursor-pointer",
                    isSelected
                      ? "bg-primary text-primary-ink shadow-[inset_0_1px_0_rgb(255_255_255_/_0.4)]"
                      : "text-muted hover:text-ink",
                  )}
                >
                  <Icon size={14} weight={isSelected ? "bold" : "regular"} />
                </button>
              );
            })}
          </div>
        </div>

        {/* Main 2-column layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12">
          {/* Left column: Structural terminal overview (approx 5:4 ratio -> 7:5) */}
          <div className="flex flex-col justify-between border-b border-border bg-surface-raised p-6 md:p-8 lg:col-span-7 lg:border-b-0 lg:border-r">
            <div className="space-y-6">
              <div className="space-y-3">
                <BrandLockup size="lg" />
                <p className="text-xs text-muted leading-relaxed max-w-md">
                  统一管理收入、支出、汇率与审批，让经营与现金口径保持清楚可追溯。
                </p>
              </div>

              <div className="divide-y divide-border border-y border-border">
                <div className="flex items-start gap-3 py-4">
                  <div className="instrument-inset mt-0.5 flex size-7 shrink-0 items-center justify-center text-ink">
                    <BookOpenText size={16} weight="bold" />
                  </div>
                  <div>
                    <h2 className="text-xs font-semibold text-ink">
                      总账统一口径
                    </h2>
                    <p className="mt-0.5 text-xs text-muted leading-relaxed">
                      收入、支出与凭证由同一总账计算，金额来源始终一致。
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3 py-4">
                  <div className="instrument-inset mt-0.5 flex size-7 shrink-0 items-center justify-center text-ink">
                    <ArrowsLeftRight size={16} weight="bold" />
                  </div>
                  <div>
                    <h2 className="text-xs font-semibold text-ink">
                      经营与现金并列
                    </h2>
                    <p className="mt-0.5 text-xs text-muted leading-relaxed">
                      经营结果与实际资金变化并列呈现，口径清楚不混用。
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3 py-4">
                  <div className="instrument-inset mt-0.5 flex size-7 shrink-0 items-center justify-center text-ink">
                    <ShieldCheck size={16} weight="bold" />
                  </div>
                  <div>
                    <h2 className="text-xs font-semibold text-ink">
                      操作全程可追溯
                    </h2>
                    <p className="mt-0.5 text-xs text-muted leading-relaxed">
                      记录、审批与 AI 操作保留来源和结果，便于复核。
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-8 border-t border-border pt-4 text-xs text-muted">
              以人民币为本位币
            </div>
          </div>

          {/* Right column: Form Instrument Panel */}
          <div className="flex flex-col justify-center bg-surface p-6 md:p-8 lg:col-span-5">
            <div className="mx-auto w-full max-w-sm space-y-6">
              <div className="space-y-1.5 text-left">
                <h2 className="text-lg font-semibold text-ink">{title}</h2>
                <p className="text-xs leading-relaxed text-muted">
                  {isBootstrap
                    ? "首次部署时创建管理员和工作区"
                    : mode === "register"
                      ? "填写账号资料和管理员提供的一次性令牌"
                      : "使用用户名或邮箱登录"}
                </p>
              </div>

              {!isBootstrap && (
                <div
                  className="instrument-inset flex p-1"
                  aria-label="账户操作"
                >
                  {(["login", "register"] as const).map((item) => (
                    <button
                      key={item}
                      type="button"
                      aria-pressed={mode === item}
                      onClick={() => setMode(item)}
                      className={cn(
                        "h-8 flex-1 rounded-md text-xs font-medium transition-colors cursor-pointer",
                        mode === item
                          ? "bg-surface text-ink shadow-[var(--shadow-panel)]"
                          : "text-muted hover:text-ink",
                      )}
                    >
                      {item === "login" ? "登录" : "注册"}
                    </button>
                  ))}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                {isBootstrap && (
                  <Input
                    label="工作区名称"
                    value={workspaceName}
                    onChange={(event) => setWorkspaceName(event.target.value)}
                    required
                  />
                )}

                {mode === "login" ? (
                  <Input
                    label="用户名或邮箱"
                    autoComplete="username"
                    placeholder="输入用户名或邮箱"
                    value={identifier}
                    onChange={(event) => setIdentifier(event.target.value)}
                    required
                  />
                ) : (
                  <>
                    <Input
                      label="用户名"
                      autoComplete="username"
                      placeholder="用于登录和记账人显示"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      required
                    />
                    <Input
                      label="邮箱"
                      type="email"
                      autoComplete="email"
                      placeholder="name@example.com"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      required
                    />
                    {mode === "register" && (
                      <Input
                        label="邀请令牌"
                        autoComplete="off"
                        placeholder="输入管理员提供的令牌"
                        value={inviteToken}
                        onChange={(event) => setInviteToken(event.target.value)}
                        required
                      />
                    )}
                  </>
                )}

                <Input
                  label="密码"
                  type="password"
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                  placeholder={mode === "login" ? "输入密码" : "至少 12 个字符"}
                  minLength={mode === "login" ? 1 : 12}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />

                <Button type="submit" className="w-full" isLoading={isLoading}>
                  {mode === "login"
                    ? "登录"
                    : mode === "register"
                      ? "注册并登录"
                      : "完成初始化"}
                </Button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
