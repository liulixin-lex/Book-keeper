import React, { useEffect, useState } from "react";
import { UserCircle } from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Button, Input } from "../components/ui/core";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import type { User } from "../types/api";

export const ProfileView: React.FC = () => {
  const { user, refreshUser } = useAuth();
  const { success, error: toastError } = useToast();
  const [username, setUsername] = useState(user?.username || "");
  const [email, setEmail] = useState(user?.email || "");
  const [emailPassword, setEmailPassword] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState<string | null>(null);

  useEffect(() => {
    setUsername(user?.username || "");
    setEmail(user?.email || "");
  }, [user]);

  const update = async (kind: string, payload: Record<string, string>) => {
    setSubmitting(kind);
    try {
      await apiRequest<User>("/auth/profile", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      await refreshUser();
      success("个人资料已更新");
      setEmailPassword("");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (error) {
      toastError(error instanceof Error ? error.message : "更新失败");
    } finally {
      setSubmitting(null);
    }
  };

  const updatePassword = (event: React.FormEvent) => {
    event.preventDefault();
    if (newPassword !== confirmPassword) {
      toastError("两次输入的新密码不一致");
      return;
    }
    void update("password", {
      current_password: currentPassword,
      new_password: newPassword,
    });
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <section className="instrument-panel-raised flex items-center gap-4 p-5">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <UserCircle size={28} weight="duotone" />
        </div>
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold text-ink">
            {user?.username}
          </h2>
          <p className="mt-1 truncate text-xs text-muted">{user?.email}</p>
        </div>
      </section>

      <section className="instrument-panel overflow-hidden">
        <form
          className="flex flex-col gap-4 p-5 sm:flex-row sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void update("username", { username });
          }}
        >
          <div className="flex-1">
            <Input
              label="用户名"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </div>
          <Button type="submit" size="sm" isLoading={submitting === "username"}>
            保存用户名
          </Button>
        </form>

        <form
          className="grid gap-4 border-t border-border p-5 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            void update("email", { email, current_password: emailPassword });
          }}
        >
          <Input
            label="邮箱"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
          <Input
            label="当前密码"
            type="password"
            autoComplete="current-password"
            value={emailPassword}
            onChange={(event) => setEmailPassword(event.target.value)}
            required
          />
          <div className="sm:col-span-2 sm:flex sm:justify-end">
            <Button type="submit" size="sm" isLoading={submitting === "email"}>
              保存邮箱
            </Button>
          </div>
        </form>

        <form
          className="grid gap-4 border-t border-border p-5 sm:grid-cols-2"
          onSubmit={updatePassword}
        >
          <Input
            label="当前密码"
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            required
          />
          <div className="hidden sm:block" />
          <Input
            label="新密码"
            type="password"
            autoComplete="new-password"
            minLength={12}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            required
          />
          <Input
            label="确认新密码"
            type="password"
            autoComplete="new-password"
            minLength={12}
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            required
          />
          <div className="sm:col-span-2 sm:flex sm:justify-end">
            <Button
              type="submit"
              size="sm"
              isLoading={submitting === "password"}
            >
              更新密码
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
};
