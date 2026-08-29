import React, { useState, useEffect } from "react";
import { apiRequest } from "../api/client";
import { User, UserRole } from "../types/api";
import { Button, Select, Badge, Input } from "../components/ui/core";
import { Modal } from "../components/ui/modals";
import { TableSkeleton, ErrorState } from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import {
  UserPlus,
  Key,
  Copy,
  CheckCircle,
  PencilSimple,
  Trash,
} from "@phosphor-icons/react";

interface Invitation {
  id: string;
  email?: string | null;
  role: UserRole;
  invited_by_id: string;
  expires_at: string;
  accepted_at: string | null;
  status: "pending" | "accepted" | "expired";
}

interface InvitationCreated extends Invitation {
  token: string;
}

export const UsersView: React.FC = () => {
  const { user: currentUser } = useAuth();
  const { success, error: toastError } = useToast();

  const [users, setUsers] = useState<User[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isInviteModalOpen, setIsInviteModalOpen] = useState(false);
  const [inviteRole, setInviteRole] = useState<UserRole>("bookkeeper");
  const [createdInvitation, setCreatedInvitation] =
    useState<InvitationCreated | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [editUsername, setEditUsername] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editRole, setEditRole] = useState<UserRole>("bookkeeper");
  const [editIsActive, setEditIsActive] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<
    | { type: "user"; id: string; label: string }
    | { type: "invitation"; id: string; label: string }
    | null
  >(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [uRes, iRes] = await Promise.all([
        apiRequest<User[]>("/users"),
        apiRequest<Invitation[]>("/users/invitations"),
      ]);
      setUsers(uRes);
      setInvitations(iRes);
    } catch (err: any) {
      setError(err.message || "加载用户成员失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleCreateInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      const res = await apiRequest<InvitationCreated>("/users/invitations", {
        method: "POST",
        body: JSON.stringify({
          role: inviteRole,
        }),
      });
      setCreatedInvitation(res);
      success("邀请已生成，请妥善发送一次性邀请令牌");
      fetchData();
    } catch (err: any) {
      toastError(err.message || "发送邀请失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const openInvitationModal = () => {
    setCreatedInvitation(null);
    setIsInviteModalOpen(true);
  };

  const copyInvitationToken = async () => {
    if (!createdInvitation) return;
    await navigator.clipboard.writeText(createdInvitation.token);
    success("邀请令牌已复制");
  };

  const openEditModal = (targetUser: User) => {
    setEditingUser(targetUser);
    setEditUsername(targetUser.username);
    setEditEmail(targetUser.email);
    setEditRole(targetUser.role);
    setEditIsActive(targetUser.is_active);
  };

  const handleUpdateUser = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!editingUser) return;
    setIsSubmitting(true);
    try {
      const payload: Record<string, string | boolean> = {
        username: editUsername.trim(),
        email: editEmail.trim(),
      };
      if (editRole !== editingUser.role) payload.role = editRole;
      if (editIsActive !== editingUser.is_active)
        payload.is_active = editIsActive;
      const result = await apiRequest<any>(`/users/${editingUser.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      if (result?.status === "pending") {
        success("账户资料已保存，权限变更已提交审批");
      } else {
        success("账户信息已更新");
      }
      setEditingUser(null);
      await fetchData();
    } catch (err: any) {
      toastError(err.message || "更新账户信息失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setIsDeleting(true);
    try {
      const path =
        deleteTarget.type === "user"
          ? `/users/${deleteTarget.id}`
          : `/users/invitations/${deleteTarget.id}`;
      await apiRequest(path, { method: "DELETE" });
      success(deleteTarget.type === "user" ? "账户已删除" : "邀请链接已删除");
      setDeleteTarget(null);
      await fetchData();
    } catch (err: any) {
      toastError(err.message || "删除失败");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="instrument-panel flex flex-col items-start gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-ink">团队成员与角色权限</h3>
          <p className="text-xs text-muted">
            管理工作区内管理员（Admin）、记账员（Bookkeeper）与只读查账（Viewer）身份权限。
          </p>
        </div>

        {currentUser?.role === "admin" && (
          <Button size="sm" className="shrink-0" onClick={openInvitationModal}>
            <UserPlus size={16} />
            <span>邀请新成员</span>
          </Button>
        )}
      </div>

      {/* Users Table */}
      <div className="data-table-shell space-y-2">
        <div className="p-4 border-b border-border/80 bg-surface-strong/40">
          <h4 className="text-xs font-semibold text-ink">
            正式成员列表 ({users.length})
          </h4>
        </div>

        {isLoading ? (
          <TableSkeleton rows={4} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchData} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs border-collapse">
              <thead>
                <tr className="bg-surface-inset text-muted border-b border-border">
                  <th className="py-3 px-4 font-medium">用户名</th>
                  <th className="py-3 px-4 font-medium">邮箱</th>
                  <th className="py-3 px-4 font-medium">角色权限</th>
                  <th className="py-3 px-4 font-medium">加入时间</th>
                  <th className="py-3 px-4 font-medium">状态</th>
                  <th className="py-3 px-4 font-medium text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {users.map((u) => (
                  <tr
                    key={u.id}
                    className="hover:bg-surface-strong/50 transition-colors"
                  >
                    <td className="py-3 px-4 font-medium text-ink flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-primary/20 text-primary flex items-center justify-center text-[10px] font-bold">
                        {u.username.slice(0, 1)}
                      </div>
                      <span>{u.username}</span>
                    </td>
                    <td className="py-3 px-4 text-muted">{u.email}</td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <Badge
                        variant={
                          u.role === "admin"
                            ? "info"
                            : u.role === "bookkeeper"
                              ? "success"
                              : "default"
                        }
                      >
                        {u.role === "admin"
                          ? "系统管理员"
                          : u.role === "bookkeeper"
                            ? "记账员"
                            : "只读审计"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-muted whitespace-nowrap">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <Badge variant={u.is_active ? "success" : "danger"}>
                        {u.is_active ? "正常" : "已停用"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-center whitespace-nowrap">
                      {currentUser?.role === "admin" &&
                        (u.role === "bookkeeper" || u.role === "viewer") && (
                          <div className="flex items-center justify-center gap-1">
                            <button
                              type="button"
                              onClick={() => openEditModal(u)}
                              aria-label={`编辑账户 ${u.username}`}
                              title="编辑账户"
                              className="flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-strong hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                            >
                              <PencilSimple size={16} />
                            </button>
                            <button
                              type="button"
                              onClick={() =>
                                setDeleteTarget({
                                  type: "user",
                                  id: u.id,
                                  label: u.username,
                                })
                              }
                              aria-label={`删除账户 ${u.username}`}
                              title="删除账户"
                              className="flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-danger/10 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
                            >
                              <Trash size={16} />
                            </button>
                          </div>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Invitations Table */}
      {invitations.length > 0 && (
        <div className="data-table-shell">
          <div className="p-4 border-b border-border/80 bg-surface-strong/40">
            <h4 className="text-xs font-semibold text-ink">
              待加入的邀请链接 ({invitations.length})
            </h4>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-xs border-collapse">
              <thead>
                <tr className="bg-surface-inset text-muted border-b border-border">
                  <th className="py-3 px-4 font-medium">类型</th>
                  <th className="py-3 px-4 font-medium">指定角色</th>
                  <th className="py-3 px-4 font-medium">状态</th>
                  <th className="py-3 px-4 font-medium">过期时间</th>
                  <th className="py-3 px-4 font-medium text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {invitations.map((inv) => (
                  <tr
                    key={inv.id}
                    className="hover:bg-surface-strong/50 transition-colors"
                  >
                    <td className="py-3 px-4 font-medium text-ink flex items-center gap-2">
                      <Key size={15} className="text-muted" />
                      <span>一次性邀请令牌</span>
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <Badge variant="default">
                        {inv.role === "bookkeeper" ? "记账员" : "只读用户"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4">
                      <Badge
                        variant={
                          inv.status === "accepted"
                            ? "success"
                            : inv.status === "expired"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {inv.status === "accepted"
                          ? "已接受"
                          : inv.status === "expired"
                            ? "已过期"
                            : "待加入"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-muted whitespace-nowrap">
                      {new Date(inv.expires_at).toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-center whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() =>
                          setDeleteTarget({
                            type: "invitation",
                            id: inv.id,
                            label: "一次性邀请令牌",
                          })
                        }
                        aria-label="删除邀请链接"
                        title="删除邀请链接"
                        className="inline-flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-danger/10 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
                      >
                        <Trash size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Invite Modal */}
      <Modal
        isOpen={isInviteModalOpen}
        onClose={() => setIsInviteModalOpen(false)}
        title="邀请团队成员"
        maxWidth="md"
      >
        {createdInvitation ? (
          <div className="space-y-4 text-xs">
            <div className="flex items-center gap-2 text-success">
              <CheckCircle size={18} weight="fill" />
              <span className="font-medium">邀请已生成</span>
            </div>
            <p className="text-muted leading-relaxed">
              此令牌只在创建时返回。请通过可信渠道发送给新成员。
            </p>
            <div className="instrument-inset p-3">
              <p className="break-all font-mono text-[11px] text-ink select-all">
                {createdInvitation.token}
              </p>
            </div>
            <div className="flex justify-end gap-2 border-t border-border pt-4">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={copyInvitationToken}
              >
                <Copy size={15} />
                复制令牌
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => setIsInviteModalOpen(false)}
              >
                完成
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleCreateInvitation} className="space-y-4 text-xs">
            <Select
              label="赋予角色 *"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as UserRole)}
            >
              <option value="bookkeeper">
                记账员 (可手动录入、执行 AI 记账)
              </option>
              <option value="viewer">只读用户 (仅查看报表与AI只读提问)</option>
            </Select>

            <p className="text-muted leading-relaxed">
              注意：出于总账安全控制，管理员角色（Admin）只能通过系统授权升级，不可通过直接邮件邀请直接赋予。
            </p>

            <div className="flex justify-end gap-2 pt-4 border-t border-border">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setIsInviteModalOpen(false)}
              >
                取消
              </Button>
              <Button type="submit" size="sm" isLoading={isSubmitting}>
                生成邀请
              </Button>
            </div>
          </form>
        )}
      </Modal>

      <Modal
        isOpen={!!editingUser}
        onClose={() => !isSubmitting && setEditingUser(null)}
        title="编辑账户信息"
        maxWidth="md"
      >
        <form onSubmit={handleUpdateUser} className="space-y-4 text-xs">
          <Input
            label="用户名 *"
            value={editUsername}
            maxLength={120}
            required
            onChange={(event) => setEditUsername(event.target.value)}
          />
          <Input
            label="邮箱 *"
            type="email"
            value={editEmail}
            required
            onChange={(event) => setEditEmail(event.target.value)}
          />
          <Select
            label="角色权限 *"
            value={editRole}
            onChange={(event) => setEditRole(event.target.value as UserRole)}
          >
            <option value="bookkeeper">记账员</option>
            <option value="viewer">只读用户</option>
          </Select>
          <Select
            label="账户状态 *"
            value={editIsActive ? "active" : "inactive"}
            onChange={(event) =>
              setEditIsActive(event.target.value === "active")
            }
          >
            <option value="active">正常</option>
            <option value="inactive">停用</option>
          </Select>
          <p className="text-muted leading-relaxed">
            角色或账户状态变更需要审批，用户名和邮箱会随审批一起生效。
          </p>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={isSubmitting}
              onClick={() => setEditingUser(null)}
            >
              取消
            </Button>
            <Button type="submit" size="sm" isLoading={isSubmitting}>
              保存修改
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        isOpen={!!deleteTarget}
        onClose={() => !isDeleting && setDeleteTarget(null)}
        title={deleteTarget?.type === "user" ? "删除账户" : "删除邀请链接"}
        maxWidth="sm"
      >
        <div className="space-y-4 text-xs">
          <p className="text-ink leading-relaxed">
            {deleteTarget?.type === "user"
              ? `确定删除账户「${deleteTarget.label}」吗？该成员将立即无法登录，历史账务记录仍会保留。`
              : "确定删除这条邀请链接吗？删除后该令牌将立即失效。"}
          </p>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={isDeleting}
              onClick={() => setDeleteTarget(null)}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="danger"
              size="sm"
              isLoading={isDeleting}
              onClick={handleDelete}
            >
              确认删除
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
