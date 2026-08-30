import React, { useEffect, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  CloudArrowUp,
  CloudCheck,
  Database,
  DownloadSimple,
  FloppyDisk,
  HardDrives,
  Trash,
  WarningCircle,
} from "@phosphor-icons/react";
import { apiRequest } from "../api/client";
import { Badge, Button, Input } from "../components/ui/core";
import { ErrorState } from "../components/ui/feedback";
import { useToast } from "../context/ToastContext";
import {
  BackupRun,
  BackupScheduleConfig,
  BackupStorageConfig,
  BackupStorageType,
} from "../types/api";

interface StorageForm {
  storage_type: BackupStorageType;
  endpoint_url: string;
  region: string;
  bucket: string;
  access_key_id: string;
  secret_access_key: string;
  prefix: string;
  force_path_style: boolean;
}

interface ScheduleForm {
  enabled: boolean;
  cron_expression: string;
  retain_days: number;
  retain_count: number;
}

const initialStorage: StorageForm = {
  storage_type: "s3",
  endpoint_url: "",
  region: "us-east-1",
  bucket: "",
  access_key_id: "",
  secret_access_key: "",
  prefix: "backups",
  force_path_style: false,
};

const initialSchedule: ScheduleForm = {
  enabled: false,
  cron_expression: "0 2 * * *",
  retain_days: 14,
  retain_count: 10,
};

function formatBytes(value: number | null): string {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusBadge(status: BackupRun["status"]) {
  if (status === "completed") return <Badge variant="success">已完成</Badge>;
  if (status === "failed") return <Badge variant="danger">失败</Badge>;
  return <Badge variant="info">执行中</Badge>;
}

export const BackupSettingsView: React.FC = () => {
  const { success, error: toastError } = useToast();
  const [storage, setStorage] = useState<StorageForm>(initialStorage);
  const [schedule, setSchedule] = useState<ScheduleForm>(initialSchedule);
  const [storageMeta, setStorageMeta] = useState<BackupStorageConfig | null>(
    null,
  );
  const [scheduleMeta, setScheduleMeta] = useState<BackupScheduleConfig | null>(
    null,
  );
  const [runs, setRuns] = useState<BackupRun[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSavingStorage, setIsSavingStorage] = useState(false);
  const [isTestingStorage, setIsTestingStorage] = useState(false);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      const [storageResult, scheduleResult, runResult] = await Promise.all([
        apiRequest<BackupStorageConfig>("/backups/storage"),
        apiRequest<BackupScheduleConfig>("/backups/schedule"),
        apiRequest<{ items: BackupRun[] }>("/backups"),
      ]);
      setStorageMeta(storageResult);
      setStorage({
        storage_type: storageResult.storage_type,
        endpoint_url: storageResult.endpoint_url || "",
        region: storageResult.region,
        bucket: storageResult.bucket,
        access_key_id: storageResult.access_key_id,
        secret_access_key: "",
        prefix: storageResult.prefix || "backups",
        force_path_style: storageResult.force_path_style,
      });
      setScheduleMeta(scheduleResult);
      setSchedule({
        enabled: scheduleResult.enabled,
        cron_expression: scheduleResult.cron_expression,
        retain_days: scheduleResult.retain_days,
        retain_count: scheduleResult.retain_count,
      });
      setRuns(runResult.items);
    } catch (error) {
      setLoadError((error as Error).message || "加载备份配置失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const storagePayload = () => ({
    storage_type: storage.storage_type,
    endpoint_url: storage.endpoint_url.trim() || null,
    region: storage.region.trim(),
    bucket: storage.bucket.trim(),
    access_key_id: storage.access_key_id.trim(),
    ...(storage.secret_access_key
      ? { secret_access_key: storage.secret_access_key }
      : {}),
    prefix: storage.prefix.trim(),
    force_path_style: storage.force_path_style,
  });

  const saveStorage = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSavingStorage(true);
    try {
      const result = await apiRequest<BackupStorageConfig>("/backups/storage", {
        method: "PUT",
        body: JSON.stringify(storagePayload()),
      });
      setStorageMeta(result);
      setStorage((current) => ({ ...current, secret_access_key: "" }));
      success("对象存储配置已保存");
    } catch (error) {
      toastError((error as Error).message || "保存对象存储配置失败");
    } finally {
      setIsSavingStorage(false);
    }
  };

  const testStorage = async () => {
    setIsTestingStorage(true);
    try {
      await apiRequest("/backups/storage/test", {
        method: "POST",
        body: JSON.stringify(storagePayload()),
      });
      success("对象存储连接成功");
    } catch (error) {
      toastError((error as Error).message || "对象存储连接失败");
    } finally {
      setIsTestingStorage(false);
    }
  };

  const saveSchedule = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSavingSchedule(true);
    try {
      const result = await apiRequest<BackupScheduleConfig>(
        "/backups/schedule",
        {
          method: "PUT",
          body: JSON.stringify(schedule),
        },
      );
      setScheduleMeta(result);
      success("定时备份计划已保存");
    } catch (error) {
      toastError((error as Error).message || "保存定时备份计划失败");
    } finally {
      setIsSavingSchedule(false);
    }
  };

  const runBackup = async () => {
    setIsRunning(true);
    try {
      const result = await apiRequest<BackupRun>("/backups/run", {
        method: "POST",
      });
      setRuns((current) => [
        result,
        ...current.filter((item) => item.id !== result.id),
      ]);
      success("远程备份已完成");
    } catch (error) {
      toastError((error as Error).message || "远程备份失败");
    } finally {
      setIsRunning(false);
    }
  };

  const downloadBackup = async (run: BackupRun) => {
    try {
      const result = await apiRequest<{ url: string }>(
        `/backups/${run.id}/download`,
      );
      const link = document.createElement("a");
      link.href = result.url;
      link.rel = "noopener";
      link.click();
    } catch (error) {
      toastError((error as Error).message || "生成下载链接失败");
    }
  };

  const deleteBackup = async (run: BackupRun) => {
    if (!window.confirm(`确认删除备份 ${run.file_name}？`)) return;
    setDeletingId(run.id);
    try {
      await apiRequest(`/backups/${run.id}`, { method: "DELETE" });
      setRuns((current) => current.filter((item) => item.id !== run.id));
      success("备份已删除");
    } catch (error) {
      toastError((error as Error).message || "删除备份失败");
    } finally {
      setDeletingId(null);
    }
  };

  const selectStorageType = (storageType: BackupStorageType) => {
    setStorage((current) => ({
      ...current,
      storage_type: storageType,
      endpoint_url: storageType === "s3" ? "" : current.endpoint_url,
      region:
        storageType === "r2"
          ? "auto"
          : current.region === "auto"
            ? "us-east-1"
            : current.region,
      force_path_style: storageType === "r2" ? false : current.force_path_style,
    }));
  };

  if (isLoading) {
    return (
      <div className="space-y-4" aria-label="备份配置加载中">
        <div className="instrument-strip skeleton-sheen h-16" />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="instrument-panel skeleton-sheen h-[460px]" />
          <div className="instrument-panel skeleton-sheen h-[360px]" />
        </div>
        <div className="instrument-panel skeleton-sheen h-72" />
      </div>
    );
  }

  if (loadError) {
    return <ErrorState message={loadError} onRetry={() => void load()} />;
  }

  const storageReady = Boolean(
    storageMeta?.secret_configured && storageMeta.bucket,
  );

  return (
    <div className="space-y-4">
      <div className="instrument-strip flex flex-col gap-3 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <span className="icon-module shrink-0 text-primary">
            <CloudArrowUp size={19} weight="duotone" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-ink">远程数据库备份</h3>
              <Badge variant={storageReady ? "success" : "warning"}>
                {storageReady ? "已配置" : "待配置"}
              </Badge>
            </div>
            <p className="mt-0.5 truncate text-xs text-muted">
              {storageReady
                ? `${storageMeta?.storage_type === "r2" ? "Cloudflare R2" : "AWS S3"} / ${storageMeta?.bucket}`
                : "选择存储并填写访问凭据"}
            </p>
          </div>
        </div>
        <Button
          type="button"
          size="sm"
          onClick={() => void runBackup()}
          isLoading={isRunning}
          disabled={!storageReady}
          className="shrink-0"
        >
          <Database size={15} weight="duotone" />
          立即备份
        </Button>
      </div>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <form className="instrument-panel p-4 sm:p-5" onSubmit={saveStorage}>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-ink">对象存储</h3>
              <p className="mt-1 text-xs text-muted">S3 兼容访问配置</p>
            </div>
            {storageMeta?.secret_configured && (
              <span className="flex items-center gap-1.5 text-xs text-success">
                <CheckCircle size={15} weight="fill" />
                密钥已保存
              </span>
            )}
          </div>

          <div
            className="mb-4 grid grid-cols-2 rounded-lg border border-border bg-surface-inset p-1 shadow-[var(--shadow-inset)]"
            aria-label="存储类型"
          >
            {(["s3", "r2"] as const).map((storageType) => {
              const selected = storage.storage_type === storageType;
              return (
                <button
                  key={storageType}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => selectStorageType(storageType)}
                  className={`flex h-8 items-center justify-center gap-2 rounded-md text-xs font-medium transition-colors ${
                    selected
                      ? "bg-surface-raised text-ink shadow-[var(--shadow-panel)]"
                      : "text-muted hover:text-ink"
                  }`}
                >
                  {storageType === "s3" ? (
                    <HardDrives size={15} />
                  ) : (
                    <CloudCheck size={15} />
                  )}
                  {storageType === "s3" ? "AWS S3" : "Cloudflare R2"}
                </button>
              );
            })}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Input
                label="Endpoint"
                type="url"
                value={storage.endpoint_url}
                onChange={(event) =>
                  setStorage((current) => ({
                    ...current,
                    endpoint_url: event.target.value,
                  }))
                }
                placeholder={
                  storage.storage_type === "r2"
                    ? "https://<account-id>.r2.cloudflarestorage.com"
                    : "AWS S3 可留空"
                }
                required={storage.storage_type === "r2"}
              />
            </div>
            <Input
              label="Region"
              value={storage.region}
              onChange={(event) =>
                setStorage((current) => ({
                  ...current,
                  region: event.target.value,
                }))
              }
              required
            />
            <Input
              label="Bucket"
              value={storage.bucket}
              onChange={(event) =>
                setStorage((current) => ({
                  ...current,
                  bucket: event.target.value,
                }))
              }
              required
            />
            <Input
              label="Access Key ID"
              value={storage.access_key_id}
              onChange={(event) =>
                setStorage((current) => ({
                  ...current,
                  access_key_id: event.target.value,
                }))
              }
              autoComplete="off"
              required
            />
            <Input
              label="Secret Access Key"
              type="password"
              value={storage.secret_access_key}
              onChange={(event) =>
                setStorage((current) => ({
                  ...current,
                  secret_access_key: event.target.value,
                }))
              }
              placeholder={
                storageMeta?.secret_configured ? "留空则保持当前密钥" : ""
              }
              autoComplete="new-password"
              required={!storageMeta?.secret_configured}
            />
            <div className="sm:col-span-2">
              <Input
                label="对象前缀"
                value={storage.prefix}
                onChange={(event) =>
                  setStorage((current) => ({
                    ...current,
                    prefix: event.target.value,
                  }))
                }
                placeholder="backups"
              />
            </div>
          </div>

          <label className="mt-4 flex cursor-pointer items-center gap-2 text-xs text-muted">
            <input
              type="checkbox"
              checked={storage.force_path_style}
              onChange={(event) =>
                setStorage((current) => ({
                  ...current,
                  force_path_style: event.target.checked,
                }))
              }
              className="size-4 accent-primary"
            />
            使用 Path Style 地址
          </label>

          <div className="mt-5 flex flex-wrap justify-end gap-2 border-t border-border pt-4">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              isLoading={isTestingStorage}
              onClick={() => void testStorage()}
            >
              <ArrowClockwise size={15} />
              测试连接
            </Button>
            <Button type="submit" size="sm" isLoading={isSavingStorage}>
              <FloppyDisk size={15} />
              保存配置
            </Button>
          </div>
        </form>

        <form className="instrument-panel p-4 sm:p-5" onSubmit={saveSchedule}>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold text-ink">定时计划</h3>
              <p className="mt-1 text-xs text-muted">
                时区 {scheduleMeta?.timezone || "Asia/Shanghai"}
              </p>
            </div>
            <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-muted">
              <input
                type="checkbox"
                checked={schedule.enabled}
                onChange={(event) =>
                  setSchedule((current) => ({
                    ...current,
                    enabled: event.target.checked,
                  }))
                }
                className="size-4 accent-primary"
              />
              启用
            </label>
          </div>

          <div className="space-y-3">
            <Input
              label="Cron 表达式"
              value={schedule.cron_expression}
              onChange={(event) =>
                setSchedule((current) => ({
                  ...current,
                  cron_expression: event.target.value,
                }))
              }
              placeholder="0 2 * * *"
              title="标准 5 段 Cron 表达式"
              required
            />
            <div className="grid grid-cols-2 gap-3">
              <Input
                label="保留天数"
                type="number"
                min="0"
                max="3650"
                value={schedule.retain_days}
                onChange={(event) =>
                  setSchedule((current) => ({
                    ...current,
                    retain_days: Number(event.target.value),
                  }))
                }
                required
              />
              <Input
                label="保留份数"
                type="number"
                min="0"
                max="1000"
                value={schedule.retain_count}
                onChange={(event) =>
                  setSchedule((current) => ({
                    ...current,
                    retain_count: Number(event.target.value),
                  }))
                }
                required
              />
            </div>
          </div>

          <div className="mt-4 min-h-10 border-t border-border pt-3 text-xs text-muted">
            {scheduleMeta?.enabled && scheduleMeta.next_run_at ? (
              <span>下次执行 {formatDate(scheduleMeta.next_run_at)}</span>
            ) : (
              <span>当前未启用定时备份</span>
            )}
          </div>

          <div className="mt-3 flex justify-end">
            <Button type="submit" size="sm" isLoading={isSavingSchedule}>
              <FloppyDisk size={15} />
              保存计划
            </Button>
          </div>
        </form>
      </div>

      <section className="data-table-shell">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold text-ink">备份记录</h3>
            <p className="mt-0.5 text-xs text-muted">最近 {runs.length} 份</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void load()}
          >
            <ArrowClockwise size={15} />
            刷新
          </Button>
        </div>

        {runs.length === 0 ? (
          <div className="flex min-h-48 flex-col items-center justify-center px-4 text-center">
            <Database
              size={30}
              className="mb-2 text-muted/60"
              weight="duotone"
            />
            <div className="text-sm font-medium text-ink">暂无远程备份</div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-xs">
              <thead className="bg-surface-inset text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">文件</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">触发方式</th>
                  <th className="px-4 py-3 text-right font-medium">大小</th>
                  <th className="px-4 py-3 font-medium">开始时间</th>
                  <th className="px-4 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {runs.map((run) => (
                  <tr key={run.id} className="hover:bg-surface-strong/50">
                    <td className="max-w-72 px-4 py-3">
                      <div className="truncate font-medium text-ink">
                        {run.file_name}
                      </div>
                      {run.error_message && (
                        <div className="mt-1 flex items-center gap-1 truncate text-danger">
                          <WarningCircle size={13} />
                          {run.error_message}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">{statusBadge(run.status)}</td>
                    <td className="px-4 py-3 text-muted">
                      {run.trigger === "scheduled" ? "定时" : "手动"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-ink">
                      {formatBytes(run.size_bytes)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-muted">
                      {formatDate(run.started_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          title="下载"
                          aria-label={`下载 ${run.file_name}`}
                          disabled={run.status !== "completed"}
                          onClick={() => void downloadBackup(run)}
                          className="w-8 px-0"
                        >
                          <DownloadSimple size={15} />
                        </Button>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          title="删除"
                          aria-label={`删除 ${run.file_name}`}
                          disabled={run.status === "running"}
                          isLoading={deletingId === run.id}
                          onClick={() => void deleteBackup(run)}
                          className="w-8 px-0 text-danger"
                        >
                          {deletingId !== run.id && <Trash size={15} />}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};
