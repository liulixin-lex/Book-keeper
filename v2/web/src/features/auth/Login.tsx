import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError, setCsrfToken } from "@/api/client";
import { keys } from "@/api/queries";
import { Mark } from "@/app/Shell";
import { Button, Field, Input } from "@/components/ui";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const qc = useQueryClient();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<{ csrf_token: string }>("/auth/login", { email, password });
      setCsrfToken(res.data.csrf_token);
      await qc.invalidateQueries({ queryKey: keys.me });
      navigate("/overview", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "登录失败：无法连接服务。请检查网络后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-ground px-4">
      <div className="w-full max-w-[400px] rounded-card bg-card p-8 shadow-card max-sm:p-6">
        <div className="mb-8 grid justify-items-start gap-4">
          <Mark className="size-11" />
          <div>
            <h1 className="text-xl font-semibold tracking-[-0.02em]">登录账本</h1>
            <p className="mt-1 text-sm text-ink-2">中转站的收入、成本和利润，都在这里。</p>
          </div>
        </div>
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <Field label="邮箱">{(id) => <Input id={id} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />}</Field>
          <Field label="密码" error={error ?? undefined}>
            {(id, note) => (
              <Input id={id} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} aria-invalid={!!error} aria-describedby={note} required />
            )}
          </Field>
          <Button type="submit" variant="primary" size="lg" loading={busy} disabled={!email || !password} className="mt-1">
            登录
          </Button>
        </form>
      </div>
    </main>
  );
}
