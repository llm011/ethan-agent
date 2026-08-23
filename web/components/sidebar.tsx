"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import Image from "next/image";
import { Plus, Trash2, Search, Settings, Book, BookOpen, Pencil, Check, X, List, Wrench, RefreshCw, Loader2, Pin, PinOff } from "lucide-react";
import { Clock, Database, CalendarDays } from "lucide-react";
import { Ellipsis, CircleCheck } from "lucide-react";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@ethan/shared/ui/dropdown-menu";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@ethan/shared/ui/tooltip";
import { useSidebar } from "@/app/layout-shell";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";
import { Separator } from "@ethan/shared/ui/separator";
import {
  SessionInfo,
  fetchSessions,
  fetchSchedules,
  fetchPoll,
  deleteSession,
  renameSession,
  regenSessionTitle,
  createSession,
  fetchHealth,
  fetchModes,
  pinSession,
  unpinSession,
  fetchPinnedSessions,
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
  const [pinnedSessions, setPinnedSessions] = useState<SessionInfo[]>([]);
  const [scheduleGroupSessions, setScheduleGroupSessions] = useState<SessionInfo[]>([]);
  const [heartbeatGroupSessions, setHeartbeatGroupSessions] = useState<SessionInfo[]>([]);
  const [extensionSessions, setExtensionSessions] = useState<SessionInfo[]>([]);
  const [activeSessions, setActiveSessions] = useState<Set<string>>(new Set());

  // 监听 ChatView 广播的标题更新事件，立即同步左侧列表（不等下次轮询）
  useEffect(() => {
    const handler = (e: Event) => {
      const { sessionId, title } = (e as CustomEvent).detail || {};
      if (!sessionId || !title) return;
      setSessions(prev => prev.map(s => s.id === sessionId ? { ...s, title } : s));
    };
    window.addEventListener("session:title-updated", handler);
    return () => window.removeEventListener("session:title-updated", handler);
  }, []);

  useEffect(() => {
    const handler = () => {
      fetchSessions(50, 0, undefined, undefined, undefined, true, true)
        .then(setSessions).catch(() => {});
      fetchPinnedSessions().then(setPinnedSessions).catch(() => {});
    };
    window.addEventListener("sessions:refresh", handler);
    return () => window.removeEventListener("sessions:refresh", handler);
  }, []);
  const [sessionSearch, setSessionSearch] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [regeneratingId, setRegeneratingId] = useState<string | null>(null);
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [normalExpanded, setNormalExpanded] = useState(true);
  const [scheduleExpanded, setScheduleExpanded] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("ethan_sidebar_schedule_expanded") === "1";
  });
  const [heartbeatExpanded, setHeartbeatExpanded] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("ethan_sidebar_heartbeat_expanded") === "1";
  });
  const [extensionExpanded, setExtensionExpanded] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("ethan_sidebar_extension_expanded") !== "0";
  });
  const [schedules, setSchedules] = useState<any[]>([]);
  const [health, setHealth] = useState<{version: string | null; agent_name: string | null}>({version: null, agent_name: null});
  const [modes, setModes] = useState<ModeEntry[]>([]);
  const [lastSeenSchedule, setLastSeenSchedule] = useState(0);
  // 客户端挂载后再读 localStorage，避免 SSR/CSR 初始值不一致导致 hydration mismatch
  useEffect(() => {
    setLastSeenSchedule(Number(localStorage.getItem("ethan_last_seen_schedule") || "0"));
  }, []);

  // Derive active session id from pathname: /chat/[id]
  const activeSessionId = pathname.match(/^\/chat\/(.+)$/)?.[1] ?? null;

  // Derive active view from pathname
  const activeView = pathname === "/" || pathname.startsWith("/chat")
    ? "chat"
    : pathname.slice(1).replace(/\/$/, ""); // "memory", "knowledge", etc.

  // 主列表请求已 hide 心跳/定时（否则高频心跳会话会挤爆前 50，把普通会话顶出去）；
  // 定时/心跳两个分组改用 title_prefixes 独立拉取，互不影响。
  const pinnedIds = new Set(pinnedSessions.map((s) => s.id));
  const normalSessions = sessions.filter((s) => !s.title.startsWith("✅") && !s.title.startsWith("[定时]") && !s.title.startsWith("[心跳]") && s.source !== "browser-extension" && !pinnedIds.has(s.id));
  const scheduleSessions = scheduleGroupSessions;
  const heartbeatSessions = heartbeatGroupSessions;
  const scheduleUnreadCount = scheduleSessions.filter(
    (s) => s.updated_at > lastSeenSchedule
  ).length;

  // Re-fetch sessions on pathname change
  useEffect(() => {
    const q = sessionSearch.trim();
    const timer = setTimeout(() => {
      setSearchLoading(true);
      fetchSessions(50, 0, q || undefined, undefined, undefined, true, true)
        .then(setSessions)
        .catch(() => {})
        .finally(() => setSearchLoading(false));
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionSearch, pathname]);

  // 定时/心跳/浏览器插件三个分组：各拉前 5 条，30s 低频轮询（不参与 3s 主 poll）
  useEffect(() => {
    const fetchGroups = () => {
      fetchSessions(5, 0, undefined, undefined, undefined, false, false, "[定时]")
        .then(setScheduleGroupSessions)
        .catch(() => {});
      fetchSessions(5, 0, undefined, undefined, undefined, false, false, "[心跳]")
        .then(setHeartbeatGroupSessions)
        .catch(() => {});
      fetchSessions(5, 0, undefined, "browser-extension")
        .then(setExtensionSessions)
        .catch(() => {});
      fetchPinnedSessions()
        .then(setPinnedSessions)
        .catch(() => {});
    };
    fetchGroups();
    const interval = setInterval(fetchGroups, 30000);
    return () => clearInterval(interval);
  }, [pathname]);

  useEffect(() => {
    fetchSchedules().then(setSchedules).catch(() => {});
  }, [pathname]);

  // 获取版本号 + agent_name（挂载时一次）
  useEffect(() => {
    fetchHealth().then(setHealth);
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
        const data = await fetchPoll(true, true);
        setSessions(prev => {
          const incoming = data.sessions as SessionInfo[];
          const changed = incoming.length !== prev.length ||
            incoming.some((s, i) => s.updated_at !== prev[i]?.updated_at || s.title !== prev[i]?.title);
          return changed ? incoming : prev;
        });
        if (data.active_sessions) {
          setActiveSessions(new Set(data.active_sessions));
        }
      } catch {}
    }, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionSearch]);

  const handleNewSession = () => {
    router.push("/chat/new");
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

  const handleRegenTitle = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRegeneratingId(id);
    const newTitle = await regenSessionTitle(id);
    setRegeneratingId(null);
    if (newTitle) {
      setSessions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, title: newTitle } : s))
      );
    } else {
      alert("标题重新生成失败");
    }
  };

  const handleTogglePin = async (id: string, isPinned: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    if (isPinned) {
      await unpinSession(id);
      setPinnedSessions((prev) => prev.filter((s) => s.id !== id));
    } else {
      await pinSession(id);
      fetchPinnedSessions().then(setPinnedSessions).catch(() => {});
    }
  };

  // 完成/取消完成：在标题前加/去 ✅ 前缀（复用 rename 接口改 title）
  const handleToggleDone = async (id: string, title: string, e: React.MouseEvent) => {
    e.stopPropagation();
    // 兜底：标题恰好只剩 "✅" 时去掉前缀会变空串（后端 400），回退为默认标题
    const newTitle = title.startsWith("✅")
      ? title.replace(/^✅\s*/, "") || "新对话"
      : `✅ ${title}`;
    try {
      await renameSession(id, newTitle);
    } catch {
      alert("操作失败，请稍后重试");
      return;
    }
    const patch = (list: SessionInfo[]) =>
      list.map((s) => (s.id === id ? { ...s, title: newTitle } : s));
    setSessions(patch);
    setPinnedSessions(patch);
  };

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
        {/* Loading indicator for active sessions */}
        {activeSessions.has(s.id) && (
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-primary" />
        )}
        {/* 对话模式标识：hover 时变为 pin 图标（可点击置顶/取消置顶） */}
        {editingSessionId !== s.id && (() => {
          const m = s.mode ? modes.find((x) => x.key === s.mode) : null;
          const isPinned = !!(s.pinned_at && s.pinned_at > 0) || pinnedSessions.some((p) => p.id === s.id);
          const modeIcon = m ? (
            <span title={m.label} className="shrink-0 text-xs">{m.icon}</span>
          ) : (
            <span title="工作助手模式" className="shrink-0 text-xs opacity-60">🛠️</span>
          );
          return (
            <span className="shrink-0 relative">
              <span className="group-hover:hidden">{isPinned ? <Pin className="h-3.5 w-3.5 text-primary fill-primary" /> : modeIcon}</span>
              <button
                className="hidden group-hover:block"
                onClick={(e) => handleTogglePin(s.id, isPinned, e)}
                title={isPinned ? "取消置顶" : "置顶"}
              >
                {isPinned ? <PinOff className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" /> : <Pin className="h-3.5 w-3.5 text-muted-foreground hover:text-primary" />}
              </button>
            </span>
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
          <div className="flex gap-1 shrink-0">
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
          <div className="hidden group-hover:flex shrink-0 items-center gap-0.5">
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={(e) => handleToggleDone(s.id, s.title, e)}
                  />
                }
              >
                <CircleCheck className={`h-3 w-3 ${s.title.startsWith("✅") ? "text-primary" : "text-muted-foreground"}`} />
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-52 flex-col items-start gap-0.5 text-left">
                <span className="font-medium">{s.title.startsWith("✅") ? "取消完成标记" : "标记完成"}</span>
                <span className="opacity-80">仅标识标题，会话仍可继续聊</span>
              </TooltipContent>
            </Tooltip>
            <DropdownMenu>
              <DropdownMenuTrigger
                className="shrink-0 w-5 h-5 flex items-center justify-center rounded hover:bg-muted transition-colors text-muted-foreground"
                title="更多操作"
                onClick={(e) => e.stopPropagation()}
              >
                <Ellipsis className="h-3 w-3" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                <DropdownMenuItem onClick={(e) => handleRegenTitle(s.id, e)}>
                  <RefreshCw className={`h-3 w-3 ${regeneratingId === s.id ? "animate-spin" : ""}`} />
                  更新标题
                </DropdownMenuItem>
                <DropdownMenuItem onClick={(e) => startEdit(s.id, s.title, e)}>
                  <Pencil className="h-3 w-3" />
                  重命名
                </DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={(e) => handleDeleteSession(s.id, e)}>
                  <Trash2 className="h-3 w-3" />
                  删除
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
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
    <TooltipProvider delay={0}>
    <ConfirmDialog
      open={confirmState.open}
      title="删除对话"
      description="确定要删除这个对话吗？此操作无法撤销。"
      confirmLabel="删除"
      onConfirm={doDeleteSession}
      onCancel={() => setConfirmState({ open: false, id: "" })}
    />
    <aside className="w-full h-full border-r border-border flex flex-col bg-sidebar">
      <div className="p-4 flex items-center justify-between gap-2">
        <h1
          className="text-lg font-semibold flex items-center gap-2 cursor-pointer hover:opacity-80 transition-opacity min-w-0 flex-1"
          onClick={() => { navigate("/chat"); if (window.innerWidth < 768) setSidebarOpen(false); }}
        >
          <Image src={`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/logo-sidebar.png`} alt={health.agent_name || "Ethan"} width={28} height={28} className="rounded-full shrink-0" />
          <span className="whitespace-nowrap">{health.agent_name || "Ethan"}</span>
          {health.version && (
            <span
              className="text-[9px] font-mono text-muted-foreground/60 bg-muted border border-border/60 rounded-full px-1.5 py-0.5 leading-none shrink-0"
              title={`ethan-agent v${health.version}`}
            >
              v{health.version}
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
        {/* Mobile close button */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 md:hidden hover:bg-background"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
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
                {pinnedSessions.length > 0 && (
                  <>
                    <div className="flex items-center justify-between py-1 mt-1 text-muted-foreground">
                      <span className="text-sm font-semibold flex items-center gap-1">
                        <Pin className="h-3 w-3" />置顶
                      </span>
                    </div>
                    {pinnedSessions.map(renderSession)}
                  </>
                )}
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

                {extensionSessions.length > 0 && (
                  <>
                    <div
                      className="flex items-center justify-between py-1 mt-2 cursor-pointer text-muted-foreground hover:text-foreground"
                      onClick={() => setExtensionExpanded(prev => {
                        const next = !prev;
                        try { localStorage.setItem("ethan_sidebar_extension_expanded", next ? "1" : "0"); } catch {}
                        return next;
                      })}
                    >
                      <span className="text-sm font-semibold">浏览器插件</span>
                      <span className="text-[10px]">
                        {extensionExpanded ? "▼" : "▶"}
                      </span>
                    </div>
                    {extensionExpanded && extensionSessions.slice(0, 5).map(renderSession)}
                  </>
                )}

                <div
                  className="flex items-center justify-between py-1 mt-2 cursor-pointer text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setScheduleExpanded(prev => {
                      const next = !prev;
                      try { localStorage.setItem("ethan_sidebar_schedule_expanded", next ? "1" : "0"); } catch {}
                      return next;
                    });
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

                <div
                  className="flex items-center justify-between py-1 mt-2 cursor-pointer text-muted-foreground hover:text-foreground"
                  onClick={() => setHeartbeatExpanded(prev => {
                    const next = !prev;
                    try { localStorage.setItem("ethan_sidebar_heartbeat_expanded", next ? "1" : "0"); } catch {}
                    return next;
                  })}
                >
                  <span className="text-sm font-semibold">心跳(对话)</span>
                  <span className="text-[10px]">
                    {heartbeatExpanded ? "▼" : "▶"}
                  </span>
                </div>
                {heartbeatExpanded &&
                  heartbeatSessions.slice(0, 5).map(renderSession)}
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
            pathname === "/agenda"
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground"
          }`}
          onClick={() => navigate("/agenda")}
        >
          <CalendarDays className="h-4 w-4 mr-2" /> 日程 (Agenda)
        </Button>
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
          className="w-full justify-start h-9 px-3 text-muted-foreground"
          onClick={() => window.open("https://llm011.github.io/ethan-agent/", "_blank")}
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
    </TooltipProvider>
  );
}
