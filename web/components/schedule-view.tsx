
"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ScheduleJob, fetchSchedules, deleteSchedule, patchSchedule, fetchSessions, SessionInfo } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2, RefreshCw, Play, Pause, Trash2, Clock, TerminalSquare, Hash, MessageSquare, ChevronDown, ChevronRight } from "lucide-react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { formatTrigger, formatNextRun } from "@/lib/utils";

export function ScheduleView() {
  const router = useRouter();
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [scheduledSessions, setScheduledSessions] = useState<SessionInfo[]>([]);
  const [sessionsExpanded, setSessionsExpanded] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchSchedules();
      setJobs(data);
    } catch (e) {
      console.error("Failed to load schedules", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    fetchSessions(100).then(all => {
      setScheduledSessions(all.filter(s => s.title.startsWith("[定时]")));
    }).catch(e => console.error("Failed to load scheduled sessions", e));
  }, [loadData]);

  const toggleStatus = async (job: ScheduleJob) => {
    const newState = job.status === "active" ? "paused" : "active";
    // Optimistic UI update
    setJobs(prev => prev.map(j => j.id === job.id ? { ...j, status: newState } : j));
    try {
      await patchSchedule(job.id, newState);
      await loadData();
    } catch {
      // Revert if failed
      await loadData();
    }
  };

  const removeJob = (id: string) => {
    setConfirmState({ open: true, id });
  };

  const doRemoveJob = async () => {
    const id = confirmState.id;
    setConfirmState({ open: false, id: "" });
    setJobs(prev => prev.filter(j => j.id !== id));
    try {
      await deleteSchedule(id);
    } catch {
      await loadData();
    }
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <ConfirmDialog
        open={confirmState.open}
        title="删除定时任务"
        description="确定要删除这个定时任务吗？此操作无法撤销。"
        confirmLabel="删除"
        onConfirm={doRemoveJob}
        onCancel={() => setConfirmState({ open: false, id: "" })}
      />
      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <h1 className="font-semibold text-lg">定时任务 (Schedules)</h1>
        <Button variant="ghost" size="icon" onClick={loadData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </header>

      <ScrollArea className="flex-1 p-6">
        {loading && jobs.length === 0 ? (
          <div className="flex items-center justify-center h-full pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center text-muted-foreground pt-10">
            暂无定时任务
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 p-0.5">
            {jobs.map(job => (
              <Card key={job.id} className="flex flex-col shadow-sm border-border/60 bg-muted/10">
                <CardHeader className="pb-3 border-b border-border/30">
                  <div className="flex justify-between items-start">
                    <CardTitle className="text-base font-semibold leading-tight line-clamp-2 pr-2">
                      {job.name}
                    </CardTitle>
                    <Badge variant={job.status === "active" ? "default" : "secondary"} className="shrink-0 text-[10px]">
                      {job.status === "active" ? "运行中" : "已暂停"}
                    </Badge>
                  </div>
                  <CardDescription className="flex items-center gap-1.5 mt-2 text-xs">
                    <Clock className="h-3 w-3" />
                    {job.next_run_time ? formatNextRun(job.next_run_time) : "暂无下次执行时间"}
                  </CardDescription>
                </CardHeader>

                <CardContent className="pt-4 pb-2 flex-1">
                  <div className="space-y-3">
                    <div className="flex items-start gap-2 text-sm">
                      <TerminalSquare className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
                      <p className="text-muted-foreground line-clamp-3 leading-relaxed">
                        {job.prompt}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground/80 bg-muted/30 p-2 rounded-md">
                      <Hash className="h-3.5 w-3.5" />
                      <span className="truncate">绑定的会话: {job.session_id}</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground/80 bg-muted/30 p-2 rounded-md">
                      <Clock className="h-3.5 w-3.5" />
                      <span>{formatTrigger(job.trigger)}</span>
                    </div>
                  </div>
                </CardContent>

                <CardFooter className="pt-3 pb-4 flex justify-end gap-2 border-t border-border/30 mt-auto">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => router.push(`/chat/${job.session_id}`)}
                  >
                    <MessageSquare className="h-3.5 w-3.5 mr-1" /> 查看对话 →
                  </Button>
                  <Button
                    variant={job.status === "active" ? "secondary" : "default"}
                    size="sm"
                    onClick={() => toggleStatus(job)}
                  >
                    {job.status === "active" ? <><Pause className="h-3.5 w-3.5 mr-1" /> 暂停</> : <><Play className="h-3.5 w-3.5 mr-1" /> 恢复</>}
                  </Button>
                  <Button variant="destructive" size="sm" onClick={() => removeJob(job.id)}>
                    <Trash2 className="h-3.5 w-3.5 mr-1" /> 删除
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        )}

        {/* Historical scheduled sessions */}
        <div className="mt-8 border border-border/40 rounded-lg overflow-hidden">
          <button
            className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium bg-muted/20 hover:bg-muted/40 transition-colors text-left"
            onClick={() => setSessionsExpanded(v => !v)}
          >
            {sessionsExpanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            历史对话记录 ({scheduledSessions.length})
          </button>
          {sessionsExpanded && (
            <div className="divide-y divide-border/30">
              {scheduledSessions.length === 0 ? (
                <div className="px-4 py-3 text-sm text-muted-foreground">暂无历史对话记录</div>
              ) : (
                scheduledSessions.map(s => {
                  const displayTitle = s.title.startsWith("[定时] ")
                    ? s.title.slice("[定时] ".length)
                    : s.title.slice("[定时]".length);
                  const date = new Date(s.updated_at * 1000).toLocaleString("zh-CN", {
                    year: "numeric", month: "2-digit", day: "2-digit",
                    hour: "2-digit", minute: "2-digit",
                  });
                  return (
                    <button
                      key={s.id}
                      className="w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-muted/30 transition-colors text-left"
                      onClick={() => router.push(`/chat/${s.id}`)}
                    >
                      <span className="truncate mr-4 text-foreground/90">{displayTitle}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{date}</span>
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
