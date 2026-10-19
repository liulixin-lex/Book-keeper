import { StrictMode, Suspense, lazy, useEffect, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient, useMe } from "@/api/queries";
import { setCsrfToken, setUnauthorizedHandler } from "@/api/client";
import { BookContext, rememberBook, rememberedBook } from "@/app/book";
import { Shell } from "@/app/Shell";
import { applyTheme, watchSystemTheme } from "@/app/theme";
import { ToastProvider } from "@/components/toast";
import { Skeleton } from "@/components/ui";
import { EntryProvider } from "@/features/entry/EntryProvider";
import { Login } from "@/features/auth/Login";
import Overview from "@/features/overview/Overview";
import "@/styles/index.css";

const Transactions = lazy(() => import("@/features/transactions/Transactions"));
const Stats = lazy(() => import("@/features/stats/Stats"));
const Imports = lazy(() => import("@/features/imports/Imports"));
const Settings = lazy(() => import("@/features/settings/Settings"));
const More = lazy(() => import("@/features/more/More"));

function Page({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="grid gap-5" role="status" aria-label="加载中">
          <Skeleton className="h-9 w-40" />
          <Skeleton className="h-72 w-full rounded-[20px]" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

/** Signed-in area: resolves the session and the working book before any screen renders. */
function Authed() {
  const me = useMe();
  const navigate = useNavigate();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.clear();
      navigate("/login", { replace: true });
    });
  }, [navigate]);

  useEffect(() => {
    if (me.data?.csrf_token) setCsrfToken(me.data.csrf_token);
  }, [me.data?.csrf_token]);

  if (me.isPending)
    return (
      <div className="grid min-h-dvh place-items-center">
        <Skeleton className="h-10 w-48" />
      </div>
    );
  if (me.isError || !me.data) return <Navigate to="/login" replace />;

  const books = me.data.books;
  const remembered = rememberedBook();
  const bookId = books.find((b) => b.id === remembered)?.id ?? books[0]?.id;
  if (!bookId)
    return (
      <div className="grid min-h-dvh place-items-center px-6 text-center">
        <div className="grid gap-2">
          <p className="text-lg font-semibold">还没有可用的账套</p>
          <p className="text-sm text-ink-2">用 bookkeeper create-book 创建账套，或请所有者把你加为成员。</p>
        </div>
      </div>
    );
  if (bookId !== remembered) rememberBook(bookId);

  return (
    <BookContext.Provider value={bookId}>
      <EntryProvider>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/overview" element={<Overview />} />
            <Route
              path="/transactions"
              element={
                <Page>
                  <Transactions />
                </Page>
              }
            />
            <Route
              path="/stats"
              element={
                <Page>
                  <Stats />
                </Page>
              }
            />
            <Route
              path="/imports/*"
              element={
                <Page>
                  <Imports />
                </Page>
              }
            />
            <Route
              path="/settings/:section?"
              element={
                <Page>
                  <Settings />
                </Page>
              }
            />
            <Route
              path="/more"
              element={
                <Page>
                  <More />
                </Page>
              }
            />
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Route>
        </Routes>
      </EntryProvider>
    </BookContext.Provider>
  );
}

function App() {
  useEffect(() => {
    applyTheme();
    return watchSystemTheme();
  }, []);
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/*" element={<Authed />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
