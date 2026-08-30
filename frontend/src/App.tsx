import React, { lazy, Suspense, useState, useTransition } from "react";
import { BrandMark, BrandWordmark } from "./components/brand/Brand";
import { useAuth } from "./context/AuthContext";
import { Layout, NavItemKey } from "./components/layout/Layout";
import { LoginView } from "./views/LoginView";

const OverviewView = lazy(() =>
  import("./views/OverviewView").then((module) => ({
    default: module.OverviewView,
  })),
);
const IncomeRecordsView = lazy(() =>
  import("./views/RecordsView").then((module) => ({
    default: module.IncomeRecordsView,
  })),
);
const ExpenseRecordsView = lazy(() =>
  import("./views/RecordsView").then((module) => ({
    default: module.ExpenseRecordsView,
  })),
);
const AIChatView = lazy(() =>
  import("./views/AIChatView").then((module) => ({
    default: module.AIChatView,
  })),
);
const AIProvidersView = lazy(() =>
  import("./views/AIProvidersView").then((module) => ({
    default: module.AIProvidersView,
  })),
);
const AIWorkspaceView = lazy(() =>
  import("./views/AIWorkspaceView").then((module) => ({
    default: module.AIWorkspaceView,
  })),
);
const ApprovalsView = lazy(() =>
  import("./views/ApprovalsView").then((module) => ({
    default: module.ApprovalsView,
  })),
);
const SubscriptionsView = lazy(() =>
  import("./views/SubscriptionsView").then((module) => ({
    default: module.SubscriptionsView,
  })),
);
const CatalogView = lazy(() =>
  import("./views/CatalogView").then((module) => ({
    default: module.CatalogView,
  })),
);
const UsersView = lazy(() =>
  import("./views/UsersView").then((module) => ({ default: module.UsersView })),
);
const ProfileView = lazy(() =>
  import("./views/ProfileView").then((module) => ({
    default: module.ProfileView,
  })),
);
const AuditView = lazy(() =>
  import("./views/AuditView").then((module) => ({ default: module.AuditView })),
);
const BackupSettingsView = lazy(() =>
  import("./views/BackupSettingsView").then((module) => ({
    default: module.BackupSettingsView,
  })),
);

const views: Record<
  NavItemKey,
  React.LazyExoticComponent<React.ComponentType>
> = {
  overview: OverviewView,
  "income-records": IncomeRecordsView,
  "expense-records": ExpenseRecordsView,
  "ai-chat": AIChatView,
  "ai-providers": AIProvidersView,
  "ai-workspace": AIWorkspaceView,
  approvals: ApprovalsView,
  subscriptions: SubscriptionsView,
  catalog: CatalogView,
  users: UsersView,
  profile: ProfileView,
  audit: AuditView,
  backups: BackupSettingsView,
};

export const App: React.FC = () => {
  const { user, isLoading } = useAuth();
  const [currentTab, setCurrentTab] = useState<NavItemKey>("overview");
  const [, startTransition] = useTransition();

  const handleSelectTab = (tab: NavItemKey) => {
    startTransition(() => {
      setCurrentTab(tab);
    });
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[100dvh] w-full items-center justify-center bg-bg p-6 text-ink">
        <div className="instrument-panel flex w-full max-w-sm flex-col items-center gap-4 p-6 text-center">
          <BrandMark size="lg" />
          <div className="space-y-1">
            <div className="flex items-center justify-center">
              <BrandWordmark size="sm" />
            </div>
            <div className="text-xs text-muted">正在加载工作区数据</div>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-inset shadow-[var(--shadow-inset)]">
            <div className="h-full w-2/5 rounded-full bg-gradient-to-r from-primary to-secondary motion-safe:animate-[loading-track_1.4s_infinite_ease-in-out]" />
          </div>
        </div>
      </div>
    );
  }

  if (!user) {
    return <LoginView />;
  }

  const CurrentView = views[currentTab] ?? OverviewView;

  return (
    <Layout currentTab={currentTab} onSelectTab={handleSelectTab}>
      <Suspense
        fallback={
          <div className="space-y-3 p-1" aria-label="页面加载中">
            <div className="instrument-strip flex items-center justify-between p-3">
              <div className="skeleton-sheen h-4 w-32" />
              <div className="skeleton-sheen h-4 w-20" />
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <div className="instrument-panel skeleton-sheen h-28" />
              <div className="instrument-panel skeleton-sheen h-28" />
              <div className="instrument-panel skeleton-sheen h-28" />
            </div>
            <div className="instrument-panel skeleton-sheen h-72" />
          </div>
        }
      >
        <CurrentView />
      </Suspense>
    </Layout>
  );
};
