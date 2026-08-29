import React, { useState, useEffect } from "react";
import { apiRequest } from "../api/client";
import { AuditEvent, AuditPageRead } from "../types/api";
import { Button } from "../components/ui/core";
import { Drawer } from "../components/ui/modals";
import {
  TableSkeleton,
  ErrorState,
  EmptyState,
} from "../components/ui/feedback";
import {
  CaretLeft,
  CaretRight,
  Scroll,
  Robot,
  User,
} from "@phosphor-icons/react";

export const AuditView: React.FC = () => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);

  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);

  const fetchAuditEvents = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const query = new URLSearchParams({
        limit: String(pageSize),
        offset: String((page - 1) * pageSize),
      });
      const res = await apiRequest<AuditPageRead>(`/audit?${query.toString()}`);
      setEvents(res.items);
      setTotal(res.total);
    } catch (err: any) {
      setError(err.message || "加载审计日志失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditEvents();
  }, [page, pageSize]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="instrument-panel flex items-center justify-between p-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            全量不可篡改审计日志 (Audit Trail)
          </h3>
          <p className="text-xs text-muted">
            记录所有凭证生成、冲正、AI
            自动化写入、主数据变动及审批决策的变更快照与操作人。
          </p>
        </div>
      </div>

      {/* Audit Table */}
      <div className="data-table-shell">
        {isLoading ? (
          <TableSkeleton rows={8} cols={5} />
        ) : error ? (
          <ErrorState message={error} onRetry={fetchAuditEvents} />
        ) : events.length === 0 ? (
          <EmptyState
            title="暂无审计事件"
            description="系统中的每一笔操作都会被记录在只追加的审计表中"
            icon={
              <Scroll size={40} weight="duotone" className="text-primary" />
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[780px] text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-surface-inset text-muted border-b border-border">
                    <th className="py-3 px-4 font-medium">发生时间</th>
                    <th className="py-3 px-4 font-medium">主体类型</th>
                    <th className="py-3 px-4 font-medium">操作类型 (Action)</th>
                    <th className="py-3 px-4 font-medium">影响实体类型</th>
                    <th className="py-3 px-4 font-medium">实体 ID</th>
                    <th className="py-3 px-4 font-medium text-center">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {events.map((e) => (
                    <tr
                      key={e.id}
                      onClick={() => setSelectedEvent(e)}
                      className="hover:bg-surface-strong/50 transition-colors cursor-pointer"
                    >
                      <td className="py-3 px-4 text-muted whitespace-nowrap">
                        {new Date(e.created_at).toLocaleString()}
                      </td>
                      <td className="py-3 px-4 whitespace-nowrap">
                        <div className="flex items-center gap-1.5">
                          {e.actor_type === "ai" ? (
                            <Robot size={15} className="text-primary" />
                          ) : (
                            <User size={15} className="text-muted" />
                          )}
                          <span className="capitalize">{e.actor_type}</span>
                        </div>
                      </td>
                      <td className="py-3 px-4 font-mono font-medium text-ink">
                        {e.action}
                      </td>
                      <td className="py-3 px-4 text-muted">{e.entity_type}</td>
                      <td className="py-3 px-4 font-mono text-[11px] text-muted max-w-[140px] truncate">
                        {e.entity_id}
                      </td>
                      <td className="py-3 px-4 text-center whitespace-nowrap">
                        <button
                          onClick={(ev) => {
                            ev.stopPropagation();
                            setSelectedEvent(e);
                          }}
                          className="text-primary hover:underline text-xs"
                        >
                          对比快照
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex flex-col gap-3 border-t border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <label className="flex items-center gap-2 text-xs text-muted">
                每页
                <select
                  value={pageSize}
                  onChange={(event) => {
                    setPageSize(Number(event.target.value));
                    setPage(1);
                  }}
                  className="h-8 rounded-lg border border-border bg-surface-inset shadow-control-inset px-2 text-xs text-ink focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {[20, 50, 100, 200].map((size) => (
                    <option key={size} value={size}>
                      {size} 条
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex items-center justify-end gap-2">
                <span className="mr-1 text-xs text-muted">
                  共 {total} 条，第 {page} / {totalPages} 页
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label="审计日志上一页"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                >
                  <CaretLeft size={15} />
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label="审计日志下一页"
                  disabled={page >= totalPages}
                  onClick={() =>
                    setPage((current) => Math.min(totalPages, current + 1))
                  }
                >
                  <CaretRight size={15} />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Event Details Drawer */}
      <Drawer
        isOpen={!!selectedEvent}
        onClose={() => setSelectedEvent(null)}
        title="审计快照比对"
      >
        {selectedEvent && (
          <div className="space-y-4 text-xs">
            <div className="p-3 bg-surface-strong/50 rounded-lg space-y-1">
              <div className="text-muted">事件 ID: {selectedEvent.id}</div>
              <div className="text-muted">操作: {selectedEvent.action}</div>
              <div className="text-muted">
                执行者: {selectedEvent.actor_type} (
                {selectedEvent.actor_id || "System"})
              </div>
              {selectedEvent.ai_run_id && (
                <div className="text-primary font-mono text-[11px]">
                  关联 AI 运行 ID: {selectedEvent.ai_run_id}
                </div>
              )}
            </div>

            <div>
              <label className="text-muted block mb-1 font-medium">
                变更前快照 (Before)
              </label>
              <pre className="bg-surface-strong/70 p-3 rounded-lg text-[11px] font-mono text-muted overflow-x-auto border border-border">
                {JSON.stringify(selectedEvent.before_json, null, 2) ||
                  "null (新建实体)"}
              </pre>
            </div>

            <div>
              <label className="text-muted block mb-1 font-medium">
                变更后快照 (After)
              </label>
              <pre className="bg-surface-strong/70 p-3 rounded-lg text-[11px] font-mono text-ink overflow-x-auto border border-border">
                {JSON.stringify(selectedEvent.after_json, null, 2) ||
                  "null (删除实体)"}
              </pre>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
};
