"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  BackgroundTask,
  fetchBackgroundTasks,
  stopBackgroundTask,
  fetchSessions,
  SessionInfo,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@ethan/shared/ui/card";
import { Badge } from "@ethan/shared/ui/badge";
import { Button } from "@ethan/shared/ui/button";
import { ScrollArea } from "@ethan/shared/ui/scroll-area";
import { Loader2, RefreshCw, Square, MessageSquare, ChevronDown, ChevronRight, CheckCircle2, XCircle, CircleSlash, Loader } from "lucide-react";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";

const STATUS_META: Record<BackgroundTask["status"], { label: string; variant: "default" | "secondary" | "destructive"; icon: React.ReactNode }> = {
  running: { label: "运行中", variant: "default", icon: <Loader className="h-3 w-3 animate-spin" /> },
  done: { label: "已完成", variant: "secondary", icon: <CheckCircle2 className="h-3 w-3 text-emerald-500" /> },
  error: { label: "失败", variant: "destructive", icon: <XCircle className="h-3 w-3" /> },
  stopped: { label: "已停止", variant: "secondary", icon: <CircleSlash className="h-3 w-3 text-muted-foreground" /> },
};

function fmtElapsed(sec: number): string {
  if (sec < 60) return `${sec} 秒`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} 分钟`;
  const h = Math.floor(m / 60);
  return `${h} 小时 ${m % 60} 分`;
}

export function BackgroundTasksView() {
  const router = useRouter();
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string; title: string }>({ open: false, id: "", title: "" });
  const [bgSessions, setBgSessions] = useState<SessionInfo[]>([]);
  const [sessionsExpanded, setSessionsExpanded] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async () => {
    try {
      setTasks(await fetchBackgroundTasks());
    } catch (e) {
      console.error("Failed to load background tasks", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    fetchSessions(100).then(all => {
      setBgSessions(all.filter(s => s.title.startsWith("[后台]")));
    }).catch(e => console.error("Failed to load background sessions", e));
  }, [loadData]);

  // 轮询：有运行中任务时每 5s 刷新；全部结束则停轮询（ethan 无 WS 推送，轮询兜底）
  useEffect(() => {
    const anyRunning = tasks.some(t => t.status === "running");
    if (anyRunning && !pollRef.current) {
      pollRef.current = setInterval(loadData, 5000);
    } else if (!anyRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [tasks, loadData]);

  const doStop = async () => {
    const id = confirmState.id;
    setConfirmState({ open: false, id: "", title: "" });
    setTasks(prev => prev.map(t => t.id === id ? { ...t, status: "stopped" } : t));
    try {
      await stopBackgroundTask(id);
    } finally {
      await loadData();
    }
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <ConfirmDialog
        open={confirmState.open}
        title="终止后台任务"
        description={`确定终止「${confirmState.title}」吗？已完成的部分会保留。`}
        confirmLabel="终止"
        onConfirm={doStop}
        onCancel={() => setConfirmState({ open: false, id: "", title: "" })}
      />
      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <h1 className="font-semibold text-lg">后台任务 (Background Tasks)</h1>
        <Button variant="ghost" size="icon" onClick={loadData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </header>

      <ScrollArea className="flex-1 p-6">
        <p className="text-sm text-muted-foreground leading-relaxed mb-4 max-w-3xl">
          长任务在后台独立会话里异步执行，不阻塞当前对话。运行中每 5 秒自动刷新；完成后结果落在对应的后台会话，可点「查看对话」查看。
          （任务状态保存在服务进程内存中，重启 ethan 服务后列表清空。）
        </p>
        {loading && tasks.length === 0 ? (
          <div className="flex items-center justify-center pt-10">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center text-muted-foreground pt-10">暂无后台任务</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 p-0.5">
            {tasks.map(task => {
              const meta = STATUS_META[task.status];
              return (
                <Card key={task.id} className="flex flex-col shadow-sm border-border/60 bg-muted/10">
                  <CardHeader className="pb-3 border-b border-border/30">
                    <div className="flex justify-between items-start gap-2">
                      <CardTitle className="text-base font-semibold leading-tight line-clamp-2 pr-2">
                        {task.title}
                      </CardTitle>
                      <Badge variant={meta.variant} className="shrink-0 text-[10px] flex items-center gap-1">
                        {meta.icon} {meta.label}
                      </Badge>
                    </div>
                    <CardDescription className="mt-2 text-xs">
                      已运行 {fmtElapsed(task.elapsed_seconds)}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="pt-4 pb-2 flex-1">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground/80 bg-muted/30 p-2 rounded-md">
                      <span className="truncate">会话 ID: {task.id}</span>
                    </div>
                  </CardContent>

                  <CardFooter className="pt-3 pb-4 flex justify-end gap-2 border-t border-border/30 mt-auto">
                    <Button variant="outline" size="sm" onClick={() => router.push(`/chat/${task.id}`)}>
                      <MessageSquare className="h-3.5 w-3.5 mr-1" /> 查看对话 →
                    </Button>
                    {task.status === "running" && (
                      <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setConfirmState({ open: true, id: task.id, title: task.title })}
                      >
                        <Square className="h-3.5 w-3.5 mr-1" /> 终止
                      </Button>
                    )}
                  </CardFooter>
                </Card>
              );
            })}
          </div>
        )}

        {/* 历史后台会话（含已被进程清掉状态、但 session 仍在的） */}
        <div className="mt-8 border border-border/40 rounded-lg overflow-hidden">
          <button
            className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium bg-muted/20 hover:bg-muted/40 transition-colors text-left"
            onClick={() => setSessionsExpanded(v => !v)}
          >
            {sessionsExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
            历史后台会话 ({bgSessions.length})
          </button>
          {sessionsExpanded && (
            <div className="divide-y divide-border/30">
              {bgSessions.length === 0 ? (
                <div className="px-4 py-3 text-sm text-muted-foreground">暂无历史后台会话</div>
              ) : (
                bgSessions.map(s => {
                  const displayTitle = s.title.startsWith("[后台] ") ? s.title.slice("[后台] ".length) : s.title.slice("[后台]".length);
                  const date = new Date(s.updated_at * 1000).toLocaleString("zh-CN", {
                    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
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
