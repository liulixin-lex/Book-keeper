/**
 * 设置: the reference data behind every entry, and access to the book. Desktop shows the section list beside the
 * content; on a phone the list is its own screen and each section opens from it.
 */
import { Navigate, NavLink, useParams } from "react-router";
import { clsx } from "clsx";
import { ArrowLeft, CaretRight, ClockCounterClockwise, CurrencyCircleDollar, Funnel, Percent, Plug, Sparkle, Storefront, Tag, Tray, UserCircle, UsersThree, type Icon } from "@phosphor-icons/react";
import { useBook } from "@/api/queries";
import type { BookRef } from "@/api/types";
import { Card } from "@/components/ui";
import { Categories, Channels, Counterparties, Currencies } from "./business";
import { FeeRules, Rules, Sources } from "./rules";
import { Account, Activity, AiAccess } from "./access";
import { AiModels } from "./ai";

interface Section {
  key: string;
  label: string;
  hint: string;
  icon: Icon;
  render: () => React.ReactNode;
  /** Who sees it; everyone when absent. */
  roles?: BookRef["role"][];
}

const GROUPS: { title: string; sections: Section[] }[] = [
  {
    title: "业务数据",
    sections: [
      { key: "counterparties", label: "往来方", hint: "上游站点、服务商与平台", icon: UsersThree, render: () => <Counterparties /> },
      { key: "channels", label: "渠道", hint: "链动、云猫、Stripe…", icon: Storefront, render: () => <Channels /> },
      { key: "categories", label: "收支分类", hint: "成本与费用的分类", icon: Tag, render: () => <Categories /> },
      { key: "fee-rules", label: "手续费规则", hint: "按渠道和往来方计算手续费", icon: Percent, render: () => <FeeRules /> },
      { key: "rules", label: "分类规则", hint: "导入时自动分类", icon: Funnel, render: () => <Rules /> },
      { key: "sources", label: "导入来源", hint: "账单格式与默认分类", icon: Tray, render: () => <Sources /> },
      { key: "currencies", label: "币种与汇率", hint: "CNY、USD、GBP、额度单位", icon: CurrencyCircleDollar, render: () => <Currencies /> },
    ],
  },
  {
    title: "接入与账户",
    sections: [
      { key: "ai", label: "AI 接入", hint: "MCP 地址与 API 令牌", icon: Plug, render: () => <AiAccess /> },
      { key: "ai-models", label: "AI 模型", hint: "提供商、任务分配与用量", icon: Sparkle, render: () => <AiModels />, roles: ["owner", "admin", "accountant"] },
      { key: "activity", label: "操作记录", hint: "每次写入，可整次撤销", icon: ClockCounterClockwise, render: () => <Activity /> },
      { key: "data", label: "账户与数据", hint: "外观、导出、数据检查、密码", icon: UserCircle, render: () => <Account /> },
    ],
  },
];

export default function Settings() {
  const { section } = useParams();
  const book = useBook();
  const role = book.data?.role;
  // Sections depend on the role, so wait for it: a deep link to /settings/ai-models must not bounce to the first section.
  if (book.isPending) return null;
  const groups = GROUPS.map((g) => ({ ...g, sections: g.sections.filter((s) => !s.roles || (role && s.roles.includes(role))) }));
  const ALL = groups.flatMap((g) => g.sections);
  const current = ALL.find((s) => s.key === section);
  // Desktop shows list and content side by side, so it always opens on a section; phones start from the list.
  if (!current && window.matchMedia("(min-width: 1024px)").matches) return <Navigate to={`/settings/${ALL[0]!.key}`} replace />;

  return (
    <div className="lg:grid lg:grid-cols-[260px_minmax(0,1fr)] lg:gap-8">
      <nav aria-label="设置" className={clsx("lg:sticky lg:top-5 lg:self-start", current && "max-lg:hidden")}>
        <h1 className="mb-6 flex min-h-10 items-center text-xl font-semibold tracking-[-0.02em] max-lg:mb-5">设置</h1>
        <div className="grid gap-6">
          {groups.map((g) => (
            <div key={g.title}>
              <h2 className="mb-2 px-3 text-sm font-medium text-ink-3">{g.title}</h2>
              <Card as="div" className="p-1.5 lg:bg-transparent lg:p-0 lg:shadow-none">
                {g.sections.map((s) => (
                  <NavLink
                    key={s.key}
                    to={`/settings/${s.key}`}
                    className={({ isActive }) =>
                      clsx(
                        "flex items-center gap-3 rounded-[14px] px-3 py-2.5 transition-colors duration-150 lg:rounded-full lg:py-2",
                        isActive ? "bg-card font-semibold text-ink lg:shadow-lift" : "text-ink-2 hover:bg-well hover:text-ink",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <s.icon size={19} weight={isActive ? "fill" : "regular"} className="shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium text-ink lg:font-[inherit] lg:text-[inherit]">{s.label}</span>
                          <span className="block truncate text-sm text-ink-3 lg:hidden">{s.hint}</span>
                        </span>
                        <CaretRight size={14} className="shrink-0 text-ink-3 lg:hidden" />
                      </>
                    )}
                  </NavLink>
                ))}
              </Card>
            </div>
          ))}
        </div>
      </nav>

      <div className={clsx("min-w-0", !current && "max-lg:hidden")}>
        {current ? (
          <>
            <NavLink to="/settings" className="-ml-1 mb-3 inline-flex items-center gap-1 rounded-full px-1 text-sm font-medium text-ink-2 hover:text-ink lg:hidden">
              <ArrowLeft size={14} />
              设置
            </NavLink>
            <header className="mb-6 flex min-h-10 flex-wrap items-baseline gap-x-3 gap-y-1 pt-[3px] max-lg:mb-5">
              <h2 className="text-xl font-semibold tracking-[-0.02em]">{current.label}</h2>
              <p className="text-sm text-ink-3">{current.hint}</p>
            </header>
            {current.render()}
          </>
        ) : null}
      </div>
    </div>
  );
}
