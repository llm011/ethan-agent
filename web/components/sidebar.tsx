"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import Image from "next/image";
import { Plus, Trash2, Search, Settings, Book, BookOpen, Pencil, Check, X, List, Wrench } from "lucide-react";
import { Clock, Database, Layers } from "lucide-react";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useSidebar } from "@/app/layout-shell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  SessionInfo,
  fetchSessions,
  fetchSchedules,
  fetchPoll,
  deleteSession,
  renameSession,
  createSession,
  fetchVersion,
  fetchModes,
  type ModeEntry,
} from "@/lib/api";

export function Sidebar() {
  const router = useRouter();
  const pathname = usePathname();
  const { setSidebarOpen } = useSidebar();

  // Close sidebar on mobile after navigating
  const navigate = (path: string) => {
    router.push(path);
    if (window.innerWidth < 768) setSidebarOpen(false);
  };

  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [sessionSearch, setSessionSearch] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [normalExpanded, setNormalExpanded] = useState(true);
  const [scheduleExpanded, setScheduleExpanded] = useState(false);
  const [schedules, setSchedules] = useState<any[]>([]);
  const [version, setVersion] = useState<string | null>(null);
  const [modes, setModes] = useState<ModeEntry[]>([]);
  const [lastSeenSchedule, setLastSeenSchedule] = useState(() => {
    if (typeof window !== "undefined") {
      return Number(localStorage.getItem("ethan_last_seen_schedule") || "0");
    }
    return 0;
  });

  // Derive active session id from pathname: /chat/[id]
  const activeSessionId = pathname.match(/^\/chat\/(.+)$/)?.[1] ?? null;

  // Derive active view from pathname
  const activeView = pathname === "/" || pathname.startsWith("/chat")
    ? "chat"
    : pathname.slice(1).replace(/\/$/, ""); // "memory", "knowledge", etc.

  const normalSessions = sessions.filter((s) => !s.title.startsWith("[定时]"));
  const scheduleSessions = sessions.filter((s) => s.title.startsWith("[定时]"));
  const scheduleUnreadCount = scheduleSessions.filter(
    (s) => s.updated_at > lastSeenSchedule
  ).length;

  // Re-fetch sessions on pathname change
  useEffect(() => {
    const q = sessionSearch.trim();
    const timer = setTimeout(() => {
      setSearchLoading(true);
      fetchSessions(50, 0, q || undefined)
        .then(setSessions)
        .catch(() => {})
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionSearch, pathname]);

  useEffect(() => {
    fetchSchedules().then(setSchedules).catch(() => {});
  }, [pathname]);

  // 获取版本号（挂载时一次）
  useEffect(() => {
    fetchVersion().then(setVersion);
  }, []);

  // 获取对话模式表（挂载时一次），用于左栏会话的模式标识
  useEffect(() => {
    fetchModes().then(setModes).catch(() => {});
  }, []);

  // Poll every 3s — skip if user is actively searching
  useEffect(() => {
    const interval = setInterval(async () => {
      if (sessionSearch.trim()) return; // don't interfere while searching
      try {
        const data = await fetchPoll();
        setSessions(prev => {
          const incoming = data.sessions as SessionInfo[];
          const changed = incoming.length !== prev.length ||
            incoming.some((s, i) => s.updated_at !== prev[i]?.updated_at || s.title !== prev[i]?.title);
          return changed ? incoming : prev;
        });
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionSearch]);

  const handleNewSession = () => {
    router.push("/chat");
  };

  const handleSelectSession = (id: string) => {
    if (editingSessionId !== id) {
      router.push(`/chat/${id}`);
    }
  };

  const handleDeleteSession = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmState({ open: true, id });
  };

  const doDeleteSession = async () => {
    const id = confirmState.id;
    setConfirmState({ open: false, id: "" });
    await deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeSessionId === id) {
      router.push("/chat");
    }
  };

  const startEdit = (id: string, title: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(id);
    setEditingTitle(title);
  };

  const commitRename = async (id: string) => {
    const title = editingTitle.trim();
    if (title) {
      await renameSession(id, title);
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title } : s))
      );
    }
    setEditingSessionId(null);
  };

  const cancelEdit = () => setEditingSessionId(null);

  const renderSession = (s: SessionInfo) => (
    <div
      key={s.id}
      className={`group flex flex-col px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
        activeSessionId === s.id
          ? "bg-accent text-accent-foreground"
          : "hover:bg-muted"
      }`}
      onClick={() => handleSelectSession(s.id)}
    >
      <div className="flex items-center gap-2">
        {/* 对话模式标识：由 /modes 表驱动；匹配到非默认模式则显示其图标，否则工作助手 🛠️ */}
        {editingSessionId !== s.id && (() => {
          const m = s.mode ? modes.find((x) => x.key === s.mode) : null;
          return m ? (
            <span title={m.label} className="shrink-0 text-xs">{m.icon}</span>
          ) : (
            <span title="工作助手模式" className="shrink-0 text-xs opacity-60">🛠️</span>
          );
        })()}
        {editingSessionId === s.id ? (
          <input
            autoFocus
            value={editingTitle}
            onChange={(e) => setEditingTitle(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") commitRename(s.id);
              if (e.key === "Escape") cancelEdit();
            }}
            onClick={(e) => e.stopPropagation()}
            className="flex-1 bg-transparent outline-none border-b border-primary"
          />
        ) : (
          <span
            className="truncate flex-1 font-medium"
            dangerouslySetInnerHTML={{
              __html: sessionSearch
                ? s.title.replace(
                    new RegExp(sessionSearch, "gi"),
                    (match) =>
                      `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`
                  )
                : s.title,
            }}
          />
        )}
        {editingSessionId === s.id ? (
          <div className="flex gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                commitRename(s.id);
              }}
              className="text-primary hover:opacity-70"
            >
              <Check className="h-3 w-3" />
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                cancelEdit();
              }}
              className="text-muted-foreground hover:opacity-70"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : (
          <div className="flex opacity-0 group-hover:opacity-100 transition-opacity">
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={(e) => startEdit(s.id, s.title, e)}
            >
              <Pencil className="h-3 w-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={(e) => handleDeleteSession(s.id, e)}
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        )}
      </div>
      {sessionSearch && s.snippet && (
        <div
          className="mt-1 text-muted-foreground line-clamp-2 leading-relaxed"
          dangerouslySetInnerHTML={{
            __html: s.snippet.replace(
              new RegExp(sessionSearch, "gi"),
              (match) =>
                `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`
            ),
          }}
        />
      )}
    </div>
  );

  return (
    <>
    <ConfirmDialog
      open={confirmState.open}
      title="删除对话"
      description="确定要删除这个对话吗？此操作无法撤销。"
      confirmLabel="删除"
      onConfirm={doDeleteSession}
      onCancel={() => setConfirmState({ open: false, id: "" })}
    />
    <aside className="w-full h-full border-r border-border flex flex-col bg-muted/30">
      <div className="p-4 flex items-center justify-between">
        <h1
          className="text-lg font-semibold flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity"
          onClick={() => { navigate("/chat"); if (window.innerWidth < 768) setSidebarOpen(false); }}
        >
          <Image src="/logo-sidebar.png" alt="Ethan Agent" width={28} height={28} className="rounded-full" />
          Ethan Agent
          {version && (
            <span
              className="text-[9px] font-mono text-muted-foreground/60 bg-muted border border-border/60 rounded-full px-1.5 py-0.5 leading-none"
              title={`ethan-agent v${version}`}
            >
              v{version}
            </span>
          )}
        </h1>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 hover:bg-background"
          onClick={() => { handleNewSession(); if (window.innerWidth < 768) setSidebarOpen(false); }}
          title="New chat"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 p-2 flex flex-col gap-2 overflow-y-auto">
        <div className="flex flex-col">
          {/* Search */}
          <div className="px-3 py-2">
            <div className="relative">
              <Search
                className={`absolute left-2.5 top-2.5 h-3.5 w-3.5 ${
                  searchLoading
                    ? "text-primary animate-pulse"
                    : "text-muted-foreground"
                }`}
              />
              <Input
                placeholder="搜索历史..."
                value={sessionSearch}
                onChange={(e) => setSessionSearch(e.target.value)}
                className="h-8 pl-8 text-xs bg-background"
              />
            </div>
          </div>

          {/* All Sessions button */}
          <Button
            variant="ghost"
            className={`w-full justify-start h-9 px-3 ${
              pathname === "/sessions"
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground"
            }`}
            onClick={() => navigate("/sessions")}
          >
            <List className="h-4 w-4 mr-2" /> 全部对话 (All Sessions)
          </Button>

          {/* Session list */}
          <div className="pl-6 pr-1 flex flex-col gap-1">
            {!sessionSearch && (
              <>
                <div
                  className="flex items-center justify-between py-1 mt-1 cursor-pointer text-muted-foreground hover:text-foreground"
                  onClick={() => setNormalExpanded(!normalExpanded)}
                >
                  <span className="text-sm font-semibold">最新对话</span>
                  <span className="text-[10px]">
                    {normalExpanded ? "▼" : "▶"}
                  </span>
                </div>
                {normalExpanded && normalSessions.slice(0, 5).map(renderSession)}

                <div
                  className="flex items-center justify-between py-1 mt-2 cursor-pointer text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setScheduleExpanded(!scheduleExpanded);
                    if (!scheduleExpanded && scheduleSessions.length > 0) {
                      const maxUpdated = Math.max(
                        ...scheduleSessions.map((s) => s.updated_at)
                      );
                      if (maxUpdated > lastSeenSchedule) {
                        setLastSeenSchedule(maxUpdated);
                        localStorage.setItem(
                          "ethan_last_seen_schedule",
                          String(maxUpdated)
                        );
                      }
                    }
                  }}
                >
                  <span className="text-sm font-semibold flex items-center gap-1">
                    定时任务(对话)
                    {scheduleUnreadCount > 0 && !scheduleExpanded && (
                      <span className="bg-red-500 text-white text-[9px] px-1.5 py-0.2 rounded-full">
                        {scheduleUnreadCount}
                      </span>
                    )}
                  </span>
                  <span className="text-[10px]">
                    {scheduleExpanded ? "▼" : "▶"}
                  </span>
                </div>
                {scheduleExpanded &&
                  scheduleSessions.slice(0, 5).map(renderSession)}
              </>
            )}
            {sessionSearch && sessions.map(renderSession)}
          </div>
        </div>

        <Separator className="my-2 opacity-40" />

        {/* Other nav items */}
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname === "/memory"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/memory")}
        >
          <Database className="h-4 w-4 mr-2" /> 记忆 (Memory)
        </Button>
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname === "/knowledge"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/knowledge")}
        >
          <Book className="h-4 w-4 mr-2" /> 知识库 (Knowledge)
        </Button>
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname === "/skills"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/skills")}
        >
          <Wrench className="h-4 w-4 mr-2" /> 技能 (Skills)
        </Button>
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname === "/schedule"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/schedule")}
        >
          <Clock className="h-4 w-4 mr-2" /> 定时任务 (Schedule)
        </Button>
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname === "/tool-tiers"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/tool-tiers")}
        >
          <Layers className="h-4 w-4 mr-2" /> 模式工具集 (Tool Tiers)
        </Button>
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname.startsWith("/docs")
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/docs")}
        >
          <BookOpen className="h-4 w-4 mr-2" /> 文档 (Docs)
        </Button>
      </div>

      {/* Bottom: Settings */}
      <div className="p-2 border-t border-border">
        <Button
          variant="ghost"
          className={`w-full justify-start h-9 px-3 ${
            pathname === "/settings"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/settings")}
        >
          <Settings className="h-4 w-4 mr-2" /> 设置 (Settings)
        </Button>
      </div>
    </aside>
    </>
  );
}
