import { useState, useEffect, useRef } from "react";
import { Pencil, Check, X, Sun, Moon, RefreshCw, Link2 } from "lucide-react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Clock, Calendar } from "lucide-react";
import { Button } from "@ethan/shared/ui/button";
import { renameSession, regenSessionTitle } from "@/lib/api";
import { getApiUrl } from "@/lib/api-base";
import { fmtTokens } from "@/lib/utils";
import { formatTrigger, formatNextRun } from "@/lib/utils";
import { useTheme } from "./use-theme";
import type { Usage } from "@ethan/shared/chat/types";
import { ServerStatusBadge } from "@/components/server-status-badge";

interface ChatHeaderProps {
  sessionId: string | null;
  title: string;
  source: string;
  usage: Usage;
  schedules: any[];
  onTitleChange: (title: string) => void;
}

const SOURCE_LABEL: Record<string, string> = { lark: "飞书", repl: "命令行", web: "Web", desktop: "桌面端", heartbeat: "心跳" };
const SOURCE_COLOR: Record<string, string> = {
  lark: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
  repl: "bg-purple-500/15 text-purple-600 dark:text-purple-400",
  web: "bg-green-500/15 text-green-600 dark:text-green-400",
  desktop: "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400",
  heartbeat: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
};

export function ChatHeader({ sessionId, title, source, usage, schedules, onTitleChange }: ChatHeaderProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [editingTitle, setEditingTitle] = useState("");
  const [copied, setCopied] = useState(false);
  const { theme, toggle: toggleTheme } = useTheme();

  // 窗口拖拽：整个 header 区域可拖拽移动窗口（用 Tauri JS API，不依赖 data-tauri-drag-region）
  // 注意：必须排除交互元素，否则 startDragging() 会抢占 mousedown 导致按钮 click 永不触发
  const headerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const onMouseDown = (e: MouseEvent) => {
      // 点击在交互元素上时不发起拖拽，让按钮/输入框正常响应
      const target = e.target as HTMLElement;
      if (target.closest('button, a, input, select, textarea, [role="button"], [data-slot="button"]')) return;
      if (e.buttons === 1) {
        // 双击最大化，单击拖拽
        e.detail === 2
          ? getCurrentWindow().toggleMaximize()
          : getCurrentWindow().startDragging();
      }
    };
    el.addEventListener("mousedown", onMouseDown);
    return () => el.removeEventListener("mousedown", onMouseDown);
  }, []);

  const startEdit = () => {
    setEditingTitle(title);
    setIsEditing(true);
  };

  const commitRename = async () => {
    const trimmed = editingTitle.trim();
    if (trimmed && sessionId) {
      await renameSession(sessionId, trimmed);
      onTitleChange(trimmed);
    }
    setIsEditing(false);
  };

  const cancelEdit = () => setIsEditing(false);

  const scheduleBanner = title.startsWith("[定时]") ? (() => {
    const jobId = title.replace("[定时] ", "").trim();
    const job = schedules.find(j => j.id === jobId || j.name === jobId);
    if (!job) return null;
    return (
      <div className="mt-2 text-xs bg-muted/50 rounded-md p-2 flex items-center gap-4 text-muted-foreground border border-border/50">
        <div className="flex items-center gap-1"><Clock className="h-3 w-3" /> <span>{formatTrigger(job.trigger)}</span></div>
        <div className="flex items-center gap-1"><Calendar className="h-3 w-3" /> <span>下次执行: {formatNextRun(job.next_run_time)}</span></div>
      </div>
    );
  })() : null;

  return (
    <header ref={headerRef} className="h-auto min-h-[42px] flex flex-col justify-center px-4 py-2 shrink-0 bg-sidebar cursor-grab active:cursor-grabbing">
      <div className="flex items-center gap-3 w-full">
        {sessionId && title && (
          isEditing ? (
            <div className="flex items-center gap-1 flex-1 min-w-0">
              <input
                autoFocus
                value={editingTitle}
                onChange={(e) => setEditingTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") cancelEdit(); }}
                className="flex-1 min-w-0 bg-transparent outline-none border-b border-primary text-lg font-semibold"
              />
              <button onClick={commitRename} className="text-primary hover:opacity-70"><Check className="h-4 w-4" /></button>
              <button onClick={cancelEdit} className="text-muted-foreground hover:opacity-70"><X className="h-4 w-4" /></button>
            </div>
          ) : (
            <div className="flex items-center gap-1 group min-w-0 flex-1">
              <button
                className="flex items-center gap-1.5 text-lg font-semibold truncate hover:text-primary"
                onClick={startEdit}
                title="Click to rename"
              >
                <span key={title} className="truncate animate-in fade-in slide-in-from-bottom-1 duration-300">{title}</span>
                <Pencil className="h-3 w-3 opacity-0 group-hover:opacity-50 shrink-0" />
              </button>
              <button
                className="opacity-0 group-hover:opacity-50 hover:!opacity-100 shrink-0 text-muted-foreground hover:text-primary"
                onClick={async (e) => {
                  e.stopPropagation();
                  if (!sessionId) return;
                  setRegenerating(true);
                  const newTitle = await regenSessionTitle(sessionId);
                  setRegenerating(false);
                  if (newTitle) {
                    onTitleChange(newTitle);
                  } else {
                    alert("标题重新生成失败");
                  }
                }}
                title="AI 重新生成标题"
              >
                <RefreshCw className={`h-3 w-3 ${regenerating ? "animate-spin" : ""}`} />
              </button>
            </div>
          )
        )}

        {sessionId && source && (
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium shrink-0 ${SOURCE_COLOR[source] || "bg-muted text-muted-foreground"}`}>
            {SOURCE_LABEL[source] || source}
          </span>
        )}

        {(usage.input > 0 || usage.output > 0) && (
          <span className="text-xs text-muted-foreground ml-auto" title={`本次对话累计：↑${usage.input.toLocaleString()} ↓${usage.output.toLocaleString()}${usage.cache > 0 ? ` ⚡${usage.cache.toLocaleString()}` : ""}`}>
            ↑{fmtTokens(usage.input)} ↓{fmtTokens(usage.output)}{usage.cache > 0 ? ` ⚡${fmtTokens(usage.cache)}` : ""}
          </span>
        )}

        {sessionId && (
          <div className="relative">
            <Button
              variant="ghost"
              size="icon"
              className={usage.input > 0 ? "ml-2" : "ml-auto"}
              onClick={async () => {
                try {
                  const url = `${getApiUrl().replace(/\/api\/?$/, "")}/chat/${sessionId}/`;
                  await navigator.clipboard.writeText(url);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                } catch (e) {
                  alert("复制失败: " + (e as Error).message);
                }
              }}
              title="复制 Web 地址"
            >
              <Link2 className="h-4 w-4" />
            </Button>
            {copied && (
              <div className="absolute right-0 top-full mt-1 z-50 px-2 py-1 rounded-md bg-foreground text-background text-xs whitespace-nowrap shadow-md animate-in fade-in slide-in-from-top-1 duration-150">
                已复制 ✓
              </div>
            )}
          </div>
        )}
        <ServerStatusBadge
          variant="full"
          className={usage.input > 0 ? "ml-2" : (sessionId ? "ml-2" : "ml-auto")}
        />
        <Button
          variant="ghost"
          size="icon"
          className="ml-2"
          onClick={toggleTheme}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>

      {scheduleBanner}
    </header>
  );
}
