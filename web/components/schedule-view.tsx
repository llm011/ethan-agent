"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ScheduleJob, ScheduleCategory, fetchSchedules, deleteSchedule, patchSchedule, renameSchedule, updateSchedulePrompt,
  fetchSessions, SessionInfo,
  fetchTimelineStatus, syncTimelines, timelineLifecycle, TimelineStatus,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@ethan/shared/ui/card";
import { Badge } from "@ethan/shared/ui/badge";
import { Button } from "@ethan/shared/ui/button";
import { ScrollArea } from "@ethan/shared/ui/scroll-area";
import { Loader2, RefreshCw, Play, Pause, Trash2, Clock, TerminalSquare, Hash, MessageSquare, ChevronDown, ChevronRight, Pencil, Calendar, Zap, RotateCw, SkipForward, Settings2 } from "lucide-react";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";
import { formatTrigger, formatNextRun } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@ethan/shared/ui/dialog";
import { Input } from "@ethan/shared/ui/input";
import { Textarea } from "@ethan/shared/ui/textarea";

const CATEGORY_META: Record<ScheduleCategory, { label: string; icon: typeof Zap; emptyHint: string }> = {
  one_off: { label: "一次性", icon: Zap, emptyHint: "暂无一次性任务" },
  recurring: { label: "周期性", icon: RotateCw, emptyHint: "暂无周期性任务" },
  timeline: { label: "时间线", icon: Calendar, emptyHint: "暂无时间线任务" },
};

export function ScheduleView() {
  const router = useRouter();
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ScheduleCategory>("one_off");
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [scheduledSessions, setScheduledSessions] = useState<SessionInfo[]>([]);
  const [sessionsExpanded, setSessionsExpanded] = useState(false);
  const [heartbeatSessions, setHeartbeatSessions] = useState<SessionInfo[]>([]);
  const [heartbeatExpanded, setHeartbeatExpanded] = useState(false);
  const [renameDialog, setRenameDialog] = useState<{ open: boolean; id: string; currentName: string }>({ open: false, id: "", currentName: "" });
  const [promptDialog, setPromptDialog] = useState<{ open: boolean; id: string; currentPrompt: string }>({ open: false, id: "", currentPrompt: "" });
  const [timelineStatuses, setTimelineStatuses] = useState<TimelineStatus[]>([]);
  const [syncing, setSyncing] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [data, tls] = await Promise.all([fetchSchedules(), fetchTimelineStatus().catch(() => [])]);
      setJobs(data);
      setTimelineStatuses(tls);
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
      setHeartbeatSessions(all.filter(s => s.title.startsWith("[心跳]")));
    }).catch(e => console.error("Failed to load scheduled sessions", e));
  }, [loadData]);

  const toggleStatus = async (job: ScheduleJob) => {
    const newState = job.status === "active" ? "paused" : "active";
    setJobs(prev => prev.map(j => j.id === job.id ? { ...j, status: newState } : j));
    try {
      await patchSchedule(job.id, newState);
      await loadData();
    } catch {
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

  const openRename = (job: ScheduleJob) => {
    setRenameDialog({ open: true, id: job.id, currentName: job.name });
  };

  const doRename = async (newName: string) => {
    const id = renameDialog.id;
    setRenameDialog({ open: false, id: "", currentName: "" });
    setJobs(prev => prev.map(j => j.id === id ? { ...j, name: newName } : j));
    try {
      await renameSchedule(id, newName);
    } catch {
      await loadData();
    }
  };

  const openEditPrompt = (job: ScheduleJob) => {
    setPromptDialog({ open: true, id: job.id, currentPrompt: job.prompt });
  };

  const doEditPrompt = async (newPrompt: string) => {
    const id = promptDialog.id;
    setPromptDialog({ open: false, id: "", currentPrompt: "" });
    setJobs(prev => prev.map(j => j.id === id ? { ...j, prompt: newPrompt } : j));
    try {
      await updateSchedulePrompt(id, newPrompt);
    } catch {
      await loadData();
    }
  };

  const doSyncTimelines = async () => {
    setSyncing(true);
    try {
      await syncTimelines();
      await loadData();
    } catch (e) {
      console.error("Failed to sync timelines", e);
    } finally {
      setSyncing(false);
    }
  };

  const doTimelineAction = async (timelineId: string, action: "skip_phase" | "advance_phase" | "pause" | "resume" | "cleanup") => {
    try {
      await timelineLifecycle(timelineId, action);
      await loadData();
    } catch (e) {
      console.error("Timeline action failed", e);
    }
  };

  // 按 category 分组
  const grouped: Record<ScheduleCategory, ScheduleJob[]> = {
    one_off: [],
    recurring: [],
    timeline: [],
  };
  for (const j of jobs) {
    const cat = (j.category || "recurring") as ScheduleCategory;
    if (grouped[cat]) grouped[cat].push(j);
    else grouped.recurring.push(j);
  }

  const visibleJobs = grouped[activeTab];
  const tabCounts = {
    one_off: grouped.one_off.length,
    recurring: grouped.recurring.length,
    timeline: grouped.timeline.length,
  };

  function RenameDialog({ open, currentName, onConfirm, onCancel }: {
    open: boolean; currentName: string; onConfirm: (name: string) => void; onCancel: () => void
  }) {
    const [inputValue, setInputValue] = useState(currentName);
    useEffect(() => {
      if (open) setInputValue(currentName);
    }, [open, currentName]);
    return (
      <Dialog open={open} onOpenChange={(o: boolean) => !o && onCancel()}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>重命名定时任务</DialogTitle>
            <DialogDescription className="mt-1">将 &ldquo;{currentName}&rdquo; 改为：</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="输入新名称"
              onKeyDown={(e) => e.key === "Enter" && inputValue.trim() && onConfirm(inputValue.trim())}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onCancel}>取消</Button>
            <Button onClick={() => inputValue.trim() && onConfirm(inputValue.trim())} disabled={!inputValue.trim()}>确认</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  function EditPromptDialog({ open, currentPrompt, onConfirm, onCancel }: {
    open: boolean; currentPrompt: string; onConfirm: (prompt: string) => void; onCancel: () => void
  }) {
    const [inputValue, setInputValue] = useState(currentPrompt);
    useEffect(() => {
      if (open) setInputValue(currentPrompt);
    }, [open, currentPrompt]);
    return (
      <Dialog open={open} onOpenChange={(o: boolean) => !o && onCancel()}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>编辑任务内容</DialogTitle>
            <DialogDescription className="mt-1">修改定时任务执行时发送的 prompt：</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="输入任务内容"
              rows={5}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={onCancel}>取消</Button>
            <Button onClick={() => inputValue.trim() && onConfirm(inputValue.trim())} disabled={!inputValue.trim()}>确认</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

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
      <RenameDialog
        open={renameDialog.open}
        currentName={renameDialog.currentName}
        onConfirm={doRename}
        onCancel={() => setRenameDialog({ open: false, id: "", currentName: "" })}
      />
      <EditPromptDialog
        open={promptDialog.open}
        currentPrompt={promptDialog.currentPrompt}
        onConfirm={doEditPrompt}
        onCancel={() => setPromptDialog({ open: false, id: "", currentPrompt: "" })}
      />
      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <h1 className="font-semibold text-lg">定时任务 (Schedules)</h1>
        <div className="flex items-center gap-2">
          {activeTab === "timeline" && (
            <Button variant="outline" size="sm" onClick={doSyncTimelines} disabled={syncing}>
              <RefreshCw className={`h-3.5 w-3.5 mr-1 ${syncing ? "animate-spin" : ""}`} />
              同步时间线
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={loadData} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </header>

      {/* Tabs */}
      <div className="border-b border-border px-4 flex gap-1 shrink-0">
        {(Object.keys(CATEGORY_META) as ScheduleCategory[]).map((cat) => {
          const meta = CATEGORY_META[cat];
          const Icon = meta.icon;
          const active = activeTab === cat;
          const count = tabCounts[cat];
          return (
            <button
              key={cat}
              onClick={() => setActiveTab(cat)}
              className={`flex items-center gap-2 px-3 py-2 text-sm border-b-2 -mb-px transition-colors ${
                active
                  ? "border-primary text-foreground font-medium"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {meta.label}
              <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
              }`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <ScrollArea className="flex-1 p-6">
        {activeTab === "timeline" && timelineStatuses.length > 0 && (
          <div className="mb-6 space-y-3">
            <h2 className="text-sm font-semibold text-muted-foreground">时间线状态</h2>
            {timelineStatuses.map(tl => (
              <Card key={tl.id} className="border-border/60 bg-muted/5">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Calendar className="h-4 w-4 text-primary" />
                      <CardTitle className="text-sm">{tl.name}</CardTitle>
                      <Badge variant="outline" className="text-[10px]">{tl.scene}</Badge>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => doTimelineAction(tl.id, "skip_phase")} title="跳过当前阶段">
                        <SkipForward className="h-3 w-3 mr-1" /> 跳过
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => doTimelineAction(tl.id, "advance_phase")} title="立即触发下一阶段">
                        <Play className="h-3 w-3 mr-1" /> 推进
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => doTimelineAction(tl.id, "pause")} title="暂停该时间线">
                        <Pause className="h-3 w-3" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => doTimelineAction(tl.id, "resume")} title="恢复该时间线">
                        <Play className="h-3 w-3" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => doTimelineAction(tl.id, "cleanup")} title="清理所有任务">
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                  <CardDescription className="text-xs mt-1">
                    {tl.current_phase ? (
                      <span>当前阶段：<span className="text-foreground">{tl.current_phase}</span>
                        {tl.phase_start && tl.phase_end && (
                          <span className="text-muted-foreground ml-2">({tl.phase_start} ~ {tl.phase_end})</span>
                        )}
                      </span>
                    ) : (
                      <span>休眠中 · 下一阶段：{tl.next_phase || "无"} · 下个周期锚点：{tl.next_anchor}</span>
                    )}
                  </CardDescription>
                </CardHeader>
                {tl.tasks.length > 0 && (
                  <CardContent className="pt-0 pb-3">
                    <div className="text-xs text-muted-foreground space-y-1 mt-1">
                      {tl.tasks.map((t, i) => (
                        <div key={t.job_id || i} className={`flex items-start gap-2 ${t.passed ? "opacity-50" : ""}`}>
                          <span className="shrink-0">
                            {t.kind === "once" ? <Zap className="h-3 w-3" /> : <RotateCw className="h-3 w-3" />}
                          </span>
                          <span className="flex-1 line-clamp-2">
                            <span className="text-foreground/80">[{t.source_phase}]</span> {t.message}
                          </span>
                          <span className="shrink-0 text-muted-foreground">
                            {t.kind === "once" && t.fire_at ? t.fire_at : t.cron || ""}
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                )}
              </Card>
            ))}
          </div>
        )}

        {loading && visibleJobs.length === 0 ? (
          <div className="flex items-center justify-center h-full pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : visibleJobs.length === 0 ? (
          <div className="text-center text-muted-foreground pt-10">
            {CATEGORY_META[activeTab].emptyHint}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 p-0.5">
            {visibleJobs.map(job => (
              <Card key={job.id} className="flex flex-col shadow-sm border-border/60 bg-muted/10">
                <CardHeader className="pb-3 border-b border-border/30">
                  <div className="flex justify-between items-start">
                    <CardTitle className="text-base font-semibold leading-tight line-clamp-2 pr-2">
                      {job.name}
                    </CardTitle>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Badge variant={job.status === "active" ? "default" : "secondary"} className="text-[10px]">
                        {job.status === "active" ? "运行中" : "已暂停"}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => openRename(job)}
                        title="重命名"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                  <CardDescription className="flex items-center gap-1.5 mt-2 text-xs flex-wrap">
                    <Clock className="h-3 w-3" />
                    {job.next_run_time ? formatNextRun(job.next_run_time) : "暂无下次执行时间"}
                    {job.source_phase && (
                      <Badge variant="outline" className="text-[10px] ml-1">{job.source_phase}</Badge>
                    )}
                  </CardDescription>
                </CardHeader>

                <CardContent className="pt-4 pb-2 flex-1">
                  <div className="space-y-3">
                    <div className="flex items-start gap-2 text-sm">
                      <TerminalSquare className="h-4 w-4 shrink-0 text-muted-foreground mt-0.5" />
                      <p className="text-muted-foreground line-clamp-3 leading-relaxed flex-1">
                        {job.prompt}
                      </p>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 shrink-0"
                        onClick={() => openEditPrompt(job)}
                        title="编辑内容"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
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
            定时任务对话记录 ({scheduledSessions.length})
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

        {/* Heartbeat sessions */}
        <div className="mt-4 border border-border/40 rounded-lg overflow-hidden">
          <button
            className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium bg-muted/20 hover:bg-muted/40 transition-colors text-left"
            onClick={() => setHeartbeatExpanded(v => !v)}
          >
            {heartbeatExpanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )}
            心跳对话记录 ({heartbeatSessions.length})
          </button>
          {heartbeatExpanded && (
            <div className="divide-y divide-border/30">
              {heartbeatSessions.length === 0 ? (
                <div className="px-4 py-3 text-sm text-muted-foreground">暂无心跳对话记录</div>
              ) : (
                heartbeatSessions.map(s => {
                  const displayTitle = s.title.startsWith("[心跳] ")
                    ? s.title.slice("[心跳] ".length)
                    : s.title.slice("[心跳]".length);
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
