import { Loader2, CheckCircle2, XCircle, CircleSlash, ArrowRight } from "lucide-react";

/**
 * 后台任务条 —— 主会话顶部常驻，展示本进程内正在跑 / 刚跑完的后台任务。
 *
 * 背景：background_task 会为每个长任务建一条独立会话。这些会话不参与侧边栏和
 * 「全部会话」列表（否则一次 deep-review 扇出的多条任务会把正常对话挤没），
 * 入口收敛到：① 侧边栏「后台任务」页；② 主会话顶部的这条任务条。
 *
 * 纯展示组件：由 web / desktop 各自取数后传入（两端 API 层不同），
 * 无 "use client" 指令，无副作用。
 */
export interface BackgroundTaskItem {
  id: string;
  title: string;
  status: "running" | "done" | "error" | "stopped";
  elapsed_seconds: number;
}

const ICONS: Record<BackgroundTaskItem["status"], React.ReactNode> = {
  running: <Loader2 className="h-3.5 w-3.5 animate-spin text-sky-500" />,
  done: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
  error: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  stopped: <CircleSlash className="h-3.5 w-3.5 text-muted-foreground" />,
};

export function fmtBgElapsed(sec: number): string {
  if (sec < 60) return `${sec} 秒`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} 分钟`;
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`;
}

interface BackgroundTaskBarProps {
  /** 要展示的后台任务（调用方已按 running 优先截断）。空数组时不渲染。 */
  tasks: BackgroundTaskItem[];
  /** 点击某条任务 → 打开它的会话。 */
  onOpen: (id: string) => void;
  /** 点「全部」→ 进入任务中心页。不传则不显示该按钮。 */
  onOpenCenter?: () => void;
}

export function BackgroundTaskBar({ tasks, onOpen, onOpenCenter }: BackgroundTaskBarProps) {
  if (tasks.length === 0) return null;

  return (
    <div className="border-b border-border/60 bg-muted/20 shrink-0">
      <div className="flex items-center gap-3 px-4 py-2 overflow-x-auto">
        <span className="text-xs text-muted-foreground shrink-0">后台任务</span>
        <div className="flex items-center gap-2 min-w-0">
          {tasks.map((t) => (
            <button
              key={t.id}
              onClick={() => onOpen(t.id)}
              title={`${t.title}（${fmtBgElapsed(t.elapsed_seconds)}）`}
              className="shrink-0 max-w-[220px] flex items-center gap-1.5 rounded-full border border-border/60 bg-background/60 px-2.5 py-1 text-xs text-foreground/90 hover:bg-accent transition-colors"
            >
              {ICONS[t.status]}
              <span className="truncate">{t.title}</span>
              <span className="text-muted-foreground tabular-nums">{fmtBgElapsed(t.elapsed_seconds)}</span>
            </button>
          ))}
        </div>
        {onOpenCenter && (
          <button
            onClick={onOpenCenter}
            className="ml-auto shrink-0 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            全部 <ArrowRight className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}
