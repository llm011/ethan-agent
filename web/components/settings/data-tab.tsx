"use client";

// 设置 → 数据管理：旧会话归档（备份 + 从主库移除）。
// 归档文件按「sessions.{起}~{止}.db」时间范围命名，列表里直接展示
// 「这是多久前的备份」；后续恢复功能复用 /sessions/archives 的同一份列表。

import { useCallback, useEffect, useState } from "react";
import { Button } from "@ethan/shared/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@ethan/shared/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@ethan/shared/ui/select";
import { Archive, Database } from "lucide-react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { previewArchive, runArchive, listArchives, type ArchivePreview, type ArchiveEntry } from "@/lib/api";

const DAY_OPTIONS = [
  { days: 30, label: "1 个月前" },
  { days: 90, label: "3 个月前" },
  { days: 180, label: "半年前" },
];

function daysLabel(days: number): string {
  return DAY_OPTIONS.find((o) => o.days === days)?.label ?? `${days} 天前`;
}

function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
}

export function DataTab() {
  const [days, setDays] = useState(90);
  const [preview, setPreview] = useState<ArchivePreview | null>(null);
  const [previewing, setPreviewing] = useState(true);
  const [archives, setArchives] = useState<ArchiveEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const loadArchives = useCallback(async () => {
    try {
      const { archives } = await listArchives();
      setArchives(archives);
    } catch {
      // 列表加载失败不打断页面，保持空态即可
    }
  }, []);

  useEffect(() => {
    loadArchives();
  }, [loadArchives]);

  useEffect(() => {
    let cancelled = false;
    setPreviewing(true);
    previewArchive(days)
      .then((p) => !cancelled && setPreview(p))
      .catch(() => !cancelled && setPreview(null))
      .finally(() => !cancelled && setPreviewing(false));
    return () => {
      cancelled = true;
    };
  }, [days]);

  const run = async () => {
    setConfirmOpen(false);
    setRunning(true);
    setMessage(null);
    try {
      const r = await runArchive(days);
      if (r.archived_sessions === 0) {
        setMessage({ type: "success", text: "没有需要归档的旧会话" });
      } else {
        setMessage({
          type: "success",
          text: `已备份 ${r.archived_sessions} 个会话（${r.archived_messages} 条消息）到 ${r.archive_file}`,
        });
      }
      await loadArchives();
      setPreview(await previewArchive(days));
    } catch {
      setMessage({ type: "error", text: "归档失败，请重试" });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Archive className="h-4 w-4" />
            归档旧会话
          </CardTitle>
          <CardDescription>
            把选定时间之前的对话备份成独立文件（存放在 ethan 数据目录的 archive/ 下），并从主库中移除，为主库瘦身。
            备份文件名自带时间范围，之后可以从备份中恢复。置顶的会话不会被归档。
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
              <SelectTrigger className="w-[160px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DAY_OPTIONS.map((o) => (
                  <SelectItem key={o.days} value={String(o.days)}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button disabled={running || previewing || !preview || preview.session_count === 0} onClick={() => setConfirmOpen(true)}>
              {running ? "归档中..." : "备份并清理"}
            </Button>
          </div>

          <div className="text-sm text-muted-foreground rounded-md border border-border/60 bg-muted/20 px-3 py-2">
            {previewing ? (
              "统计中..."
            ) : preview && preview.session_count > 0 ? (
              <>
                将备份 <span className="text-foreground font-medium">{preview.session_count}</span> 个会话
                （{preview.message_count} 条消息），时间范围{" "}
                <span className="text-foreground font-medium">
                  {preview.oldest_date} ~ {preview.newest_date}
                </span>
                ，即 {daysLabel(days)}之前的对话。
              </>
            ) : (
              `${daysLabel(days)}没有可归档的旧会话。`
            )}
          </div>

          {message && (
            <div className={`text-sm ${message.type === "success" ? "text-green-600" : "text-red-500"}`}>{message.text}</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            已有备份
          </CardTitle>
          <CardDescription>每个文件是一段时间范围内的对话备份，恢复功能将在这里选择文件找回。</CardDescription>
        </CardHeader>
        <CardContent>
          {archives.length === 0 ? (
            <div className="text-sm text-muted-foreground py-4 text-center">暂无备份</div>
          ) : (
            <div className="rounded-md border border-border/60 divide-y divide-border/40">
              {archives.map((a) => (
                <div key={a.file} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <Archive className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  <span className="font-medium">
                    {a.start_date} ~ {a.end_date}
                  </span>
                  <span className="text-xs text-muted-foreground truncate font-mono">{a.file}</span>
                  <span className="ml-auto text-xs text-muted-foreground shrink-0">{formatBytes(a.size_bytes)}</span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        title="确认归档"
        description={`将把 ${daysLabel(days)}的 ${preview?.session_count ?? 0} 个会话备份成文件并从对话列表移除（置顶会话保留）。备份文件保留在 archive/ 目录，之后可以恢复。`}
        confirmLabel="备份并清理"
        onConfirm={run}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
