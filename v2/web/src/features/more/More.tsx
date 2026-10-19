/** Phone “更多”: the modules that do not fit the tab bar, appearance and sign-out. */
import { Link, useNavigate } from "react-router";
import { CaretRight, GearSix, SignOut, Sparkle, Tray, type Icon } from "@phosphor-icons/react";
import { useImportBacklog, useMe } from "@/api/queries";
import { signOut, ThemeSwitch } from "@/app/Shell";
import { Card, PageHeader } from "@/components/ui";

export default function More() {
  const me = useMe().data;
  const navigate = useNavigate();
  const backlog = useImportBacklog().count;
  const items: { to: string; label: string; hint: string; icon: Icon; badge?: number }[] = [
    { to: "/imports", label: "导入", hint: backlog ? `${backlog} 条记录待入账` : "上传账单，补全后入账", icon: Tray, badge: backlog },
    { to: "/ai", label: "AI 助手", hint: "一句话让 AI 查账、记账、整理导入", icon: Sparkle },
    { to: "/settings", label: "设置", hint: "往来方、渠道、手续费规则、AI 接入", icon: GearSix },
  ];
  return (
    <>
      <PageHeader title="更多" />
      <div className="grid gap-5">
        <Card as="div" className="p-1.5">
          {items.map((i) => (
            <Link key={i.to} to={i.to} className="flex items-center gap-3.5 rounded-[14px] px-3 py-3 transition-colors duration-150 hover:bg-well">
              <span aria-hidden className="grid size-10 place-items-center rounded-full bg-well text-ink-2">
                <i.icon size={20} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{i.label}</span>
                <span className="block truncate text-sm text-ink-3">{i.hint}</span>
              </span>
              {!!i.badge && <span className="num grid h-6 min-w-6 place-items-center rounded-full bg-warn-wash px-2 text-sm font-semibold text-warn-text">{i.badge}</span>}
              <CaretRight size={14} className="text-ink-3" />
            </Link>
          ))}
        </Card>
        <Card as="div" className="flex items-center justify-between gap-4 p-5">
          <span className="font-medium">外观</span>
          <ThemeSwitch />
        </Card>
        <Card as="div" className="flex items-center gap-3 p-5">
          <span aria-hidden className="grid size-10 place-items-center rounded-full bg-well font-semibold text-ink-2">
            {me?.user.display_name.slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block font-medium">{me?.user.display_name}</span>
            <span className="block truncate text-sm text-ink-3">{me?.user.email}</span>
          </span>
          <button type="button" onClick={() => signOut(navigate)} className="inline-flex h-9 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium text-neg hover:bg-neg-wash">
            <SignOut size={16} />
            退出
          </button>
        </Card>
      </div>
    </>
  );
}
