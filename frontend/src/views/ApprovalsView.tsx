import React, { useState, useEffect } from "react";
import { apiRequest } from "../api/client";
import { ApprovalRequest } from "../types/api";
import { Button, Badge } from "../components/ui/core";
import { Drawer, Modal } from "../components/ui/modals";
import {
  TableSkeleton,
  ErrorState,
  EmptyState,
} from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import { Check, X, ShieldCheck } from "@phosphor-icons/react";

export const ApprovalsView: React.FC = () => {
  const { user } = useAuth();
  const { success, error: toastError } = useToast();

  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedApproval, setSelectedApproval] =
    useState<ApprovalRequest | null>(null);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchApprovals = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiRequest<ApprovalRequest[]>("/approvals");
      setApprovals(res);
    } catch (err: any) {
      setError(err.message || "加载审批流失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchApprovals();
  }, []);

  const handleApprove = async (approval: ApprovalRequest) => {
    setIsSubmitting(true);
    try {
      await apiRequest(`/approvals/${approval.id}/approve`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      success("审批通过并已执行系统变更");
      fetchApprovals();
      setSelectedApproval(null);
    } catch (err: any) {
      toastError(err.message || "审批处理失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!selectedApproval) return;
    setIsSubmitting(true);
    try {
      await apiRequest(`/approvals/${selectedApproval.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: rejectReason || "拒绝审批" }),
      });
      success("已驳回该审批申请");
      setRejectModalOpen(false);
      setSelectedApproval(null);
      fetchApprovals();
    } catch (err: any) {
      toastError(err.message || "操作失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="instrument-panel flex items-center justify-between p-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            敏感操作与配置审批中心
          </h3>
          <p className="text-xs text-muted">
            保护账本安全，涉及系统配置、AI
            供应商变更、凭证冲正等敏感操作需在此复核。
          </p>
        </div>
      </div>

      {/* Approvals Table */}
      <div className="data-table-shell">
        {isLoading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchApprovals} />
        ) : approvals.length === 0 ? (
          <EmptyState
            title="暂无待审批或历史审批事项"
            description="当产生敏感配置或账单变更申请时将在此汇总"
            icon={
              <ShieldCheck
                size={40}
                weight="duotone"
                className="text-primary"
              />
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="bg-surface-inset text-muted border-b border-border">
                  <th className="py-3 px-4 font-medium">申请时间</th>
                  <th className="py-3 px-4 font-medium">审批类型</th>
                  <th className="py-3 px-4 font-medium">发起人/发起AI</th>
                  <th className="py-3 px-4 font-medium">状态</th>
                  <th className="py-3 px-4 font-medium text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {approvals.map((appr) => (
                  <tr
                    key={appr.id}
                    onClick={() => setSelectedApproval(appr)}
                    className="hover:bg-surface-strong/50 transition-colors cursor-pointer"
                  >
                    <td className="py-3 px-4 text-muted whitespace-nowrap">
                      {new Date(appr.created_at).toLocaleString()}
                    </td>
                    <td className="py-3 px-4 font-mono font-medium text-ink">
                      {appr.kind}
                    </td>
                    <td className="py-3 px-4 text-muted">
                      {appr.requested_by_user_id
                        ? "用户操作"
                        : appr.requested_by_ai_run_id
                          ? "AI 工具发起"
                          : "系统"}
                    </td>
                    <td className="py-3 px-4 whitespace-nowrap">
                      <Badge
                        variant={
                          appr.status === "approved"
                            ? "success"
                            : appr.status === "rejected"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {appr.status === "approved" && "已通过"}
                        {appr.status === "rejected" && "已驳回"}
                        {appr.status === "pending" && "待审批"}
                      </Badge>
                    </td>
                    <td className="py-3 px-4 text-center whitespace-nowrap">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedApproval(appr);
                        }}
                        className="text-primary hover:underline text-xs"
                      >
                        查看明细
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Drawer */}
      <Drawer
        isOpen={!!selectedApproval && !rejectModalOpen}
        onClose={() => setSelectedApproval(null)}
        title="审批详情与变更载荷"
      >
        {selectedApproval && (
          <div className="space-y-4 text-xs">
            <div className="p-3 bg-surface-strong/50 rounded-lg space-y-1">
              <div className="text-muted">审批编号: {selectedApproval.id}</div>
              <div className="text-muted">
                操作类型: {selectedApproval.kind}
              </div>
              <div className="text-muted">
                当前状态: {selectedApproval.status}
              </div>
            </div>

            <div>
              <label className="text-muted block mb-1 font-medium">
                变更内容载荷 (Payload)
              </label>
              <pre className="bg-surface-strong/70 p-3 rounded-lg text-[11px] font-mono text-ink overflow-x-auto border border-border">
                {JSON.stringify(selectedApproval.payload, null, 2)}
              </pre>
            </div>

            {selectedApproval.reason && (
              <div>
                <label className="text-muted block mb-1">审批/驳回备注</label>
                <div className="bg-surface p-2.5 rounded-lg border border-border text-ink">
                  {selectedApproval.reason}
                </div>
              </div>
            )}

            {selectedApproval.status === "pending" &&
              user?.role === "admin" && (
                <div className="pt-4 border-t border-border flex items-center justify-end gap-2">
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setRejectModalOpen(true)}
                    disabled={isSubmitting}
                  >
                    <X size={16} />
                    <span>驳回</span>
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    onClick={() => handleApprove(selectedApproval)}
                    isLoading={isSubmitting}
                  >
                    <Check size={16} />
                    <span>批准通过</span>
                  </Button>
                </div>
              )}
          </div>
        )}
      </Drawer>

      {/* Reject Reason Modal */}
      <Modal
        isOpen={rejectModalOpen}
        onClose={() => setRejectModalOpen(false)}
        title="驳回审批申请"
        maxWidth="sm"
      >
        <div className="space-y-4 text-xs">
          <p className="text-muted">请填写驳回原因，便于发起人知悉：</p>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows={4}
            className="w-full bg-surface-inset shadow-control-inset p-3 rounded-lg border border-border text-ink focus:outline-none focus:border-primary text-xs"
            placeholder="例如：科目配置不合规..."
          />
          <div className="flex justify-end gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setRejectModalOpen(false)}
            >
              取消
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={handleReject}
              isLoading={isSubmitting}
            >
              确认驳回
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};
