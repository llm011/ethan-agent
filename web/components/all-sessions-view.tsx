"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { format } from "date-fns";
import { zhCN } from "date-fns/locale";
import { SessionInfo, fetchSessions, fetchPoll, renameSession, deleteSession, fetchModes, type ModeEntry } from "@/lib/api";
import { Loader2, Search, Calendar, MessageSquare, ChevronLeft, ChevronRight, Pencil, Trash2, Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ConfirmDialog } from "@/components/confirm-dialog";

interface AllSessionsViewProps {
  onSelectSession: (id: string) => void;
}

export function AllSessionsView({ onSelectSession }: AllSessionsViewProps) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [confirmState, setConfirmState] = useState<{ open: boolean; id: string }>({ open: false, id: "" });
  const [modes, setModes] = useState<ModeEntry[]>([]);
  const [filterSource, setFilterSource] = useState<string>("");  // "" = 全部渠道
  const [filterMode, setFilterMode] = useState<string>("__all__"); // "__all__" = 全部模式
  const limit = 20;

  useEffect(() => {
    fetchModes().then(setModes).catch(() => {});
  }, []);

  const loadSessions = useCallback(async (pageNum: number, q: string, src: string, md: string) => {
    setLoading(true);
    try {
      const offset = (pageNum - 1) * limit;
      // "__all__" = 不筛模式；"__default__" = 默认模式（DB 里存空串）；其余 = mode key
      const modeParam = md === "__all__" ? undefined : (md === "__default__" ? "" : md);
      const data = await fetchSessions(limit, offset, q || undefined, src || undefined, modeParam);
      if (data.length < limit) {
        setHasMore(false);
      } else {
        setHasMore(true);
      }
      setSessions(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const q = search.trim();
    const timer = setTimeout(() => {
      setPage(1);
      loadSessions(1, q, filterSource, filterMode);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, filterSource, filterMode, loadSessions]);

  useEffect(() => {
    if (page > 1) {
      loadSessions(page, search.trim(), filterSource, filterMode);
    }
  }, [page, search, filterSource, filterMode, loadSessions]);

  // Poll for new sessions every 3s（搜索或筛选时暂停，避免轮询结果覆盖筛选视图）
  useEffect(() => {
    const interval = setInterval(async () => {
      if (search.trim() || filterSource || filterMode !== "__all__") return;
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
  }, [search, filterSource, filterMode]);

  const commitRename = async (id: string) => {
    const title = editingTitle.trim();
    if (title) {
      await renameSession(id, title);
      setSessions(prev => prev.map(s => s.id === id ? { ...s, title } : s));
    }
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    setConfirmState({ open: true, id });
  };

  const doDelete = async () => {
    const id = confirmState.id;
    setConfirmState({ open: false, id: "" });
    await deleteSession(id);
    setSessions(prev => prev.filter(s => s.id !== id));
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-background overflow-hidden">
      <ConfirmDialog
        open={confirmState.open}
        title="删除对话"
        description="确定要删除这个对话吗？此操作无法撤销。"
        confirmLabel="删除"
        onConfirm={doDelete}
        onCancel={() => setConfirmState({ open: false, id: "" })}
      />
      <div className="p-4 border-b border-border flex items-center justify-between gap-3 shrink-0 flex-wrap">
        <h1 className="text-lg font-semibold shrink-0">全部历史对话</h1>
        <div className="flex items-center gap-2 flex-wrap">
          {/* 渠道筛选 */}
          <Select value={filterSource || "__all__"} onValueChange={(v) => { if (v) setFilterSource(v === "__all__" ? "" : v); }}>
            <SelectTrigger className="h-8 text-xs w-auto min-w-[88px] gap-1">
              <SelectValue placeholder="渠道">
                {(v: string) => ({ __all__: "全部渠道", web: "Web", lark: "飞书", repl: "命令行", heartbeat: "心跳" }[v] ?? "渠道")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__" className="text-xs">全部渠道</SelectItem>
              <SelectItem value="web" className="text-xs">Web</SelectItem>
              <SelectItem value="lark" className="text-xs">飞书</SelectItem>
              <SelectItem value="repl" className="text-xs">命令行</SelectItem>
              <SelectItem value="heartbeat" className="text-xs">心跳</SelectItem>
            </SelectContent>
          </Select>
          {/* 模式筛选（数据驱动：默认 + 各对话模式） */}
          <Select value={filterMode} onValueChange={(v) => { if (v) setFilterMode(v); }}>
            <SelectTrigger className="h-8 text-xs w-auto min-w-[88px] gap-1">
              <SelectValue placeholder="模式">
                {(v: string) => {
                  if (v === "__all__") return "全部模式";
                  const cur = modes.find((m) => (m.key || "__default__") === v);
                  if (!cur) return "模式";
                  return (
                    <span className="inline-flex items-center gap-1">
                      {cur.icon && <span>{cur.icon}</span>}
                      <span>{cur.label}</span>
                    </span>
                  );
                }}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__" className="text-xs">全部模式</SelectItem>
              {modes.map((m) => (
                <SelectItem key={m.key || "__default__"} value={m.key || "__default__"} className="text-xs">
                  <span className="inline-flex items-center gap-1">
                    {m.icon && <span>{m.icon}</span>}
                    <span>{m.label}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative w-56">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="搜索对话..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-background h-8 text-sm"
            />
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {loading && sessions.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <MessageSquare className="h-12 w-12 mb-4 opacity-20" />
            <p>未找到相关对话</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {sessions.map((session) => {
              const sourceLabel: Record<string, string> = { lark: "飞书", repl: "命令行", web: "Web", heartbeat: "心跳" };
              const sourceColor: Record<string, string> = {
                lark: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
                repl: "bg-purple-500/15 text-purple-600 dark:text-purple-400",
                web: "bg-green-500/15 text-green-600 dark:text-green-400",
                heartbeat: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
              };
              const src = session.source || "web";
              // mode 分类的图标/配色（默认模式不展示徽标）
              const modeAccentRing: Record<string, string> = {
                blue: "ring-blue-500/30 bg-blue-500/10 text-blue-600 dark:text-blue-400",
                pink: "ring-pink-500/30 bg-pink-500/10 text-pink-600 dark:text-pink-400",
                neutral: "ring-border bg-muted text-muted-foreground",
              };
              const curMode = session.mode ? modes.find((m) => m.key === session.mode) : undefined;
              const modeRing = curMode ? (modeAccentRing[curMode.accent] ?? modeAccentRing.neutral) : "ring-border bg-muted/60 text-muted-foreground";
              return (
                <div
                  key={session.id}
                  onClick={() => onSelectSession(session.id)}
                  className="group relative p-4 rounded-2xl border border-border bg-card hover:border-primary/40 hover:shadow-lg hover:shadow-primary/5 hover:-translate-y-0.5 transition-all duration-200 cursor-pointer flex flex-col min-h-[112px]"
                >
                  <div className="flex items-start gap-2.5 mb-1">
                    {/* mode/会话 图标头像 */}
                    <div className={`shrink-0 h-9 w-9 rounded-xl ring-1 flex items-center justify-center text-base ${modeRing}`}>
                      {curMode?.icon || <MessageSquare className="h-4 w-4 opacity-60" />}
                    </div>
                    {editingId === session.id ? (
                      <div className="flex items-center gap-1 flex-1 min-w-0" onClick={e => e.stopPropagation()}>
                        <input
                          autoFocus
                          value={editingTitle}
                          onChange={e => setEditingTitle(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === "Enter") commitRename(session.id);
                            if (e.key === "Escape") setEditingId(null);
                          }}
                          className="flex-1 min-w-0 bg-transparent outline-none border-b border-primary text-sm font-medium"
                        />
                        <button onClick={e => { e.stopPropagation(); commitRename(session.id); }} className="text-primary shrink-0"><Check className="h-3.5 w-3.5" /></button>
                        <button onClick={e => { e.stopPropagation(); setEditingId(null); }} className="text-muted-foreground shrink-0"><X className="h-3.5 w-3.5" /></button>
                      </div>
                    ) : (
                      <h3
                        className="font-semibold text-sm text-card-foreground line-clamp-2 leading-snug group-hover:text-primary transition-colors flex-1 min-w-0 pt-0.5"
                        dangerouslySetInnerHTML={{
                          __html: search.trim()
                            ? session.title.replace(new RegExp(search.trim(), 'gi'), match => `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`)
                            : session.title
                        }}
                      />
                    )}
                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <button
                        onClick={e => { e.stopPropagation(); setEditingTitle(session.title); setEditingId(session.id); }}
                        className="p-1.5 hover:text-foreground hover:bg-muted text-muted-foreground rounded-lg"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(session.id); }}
                        className="p-1.5 hover:text-destructive hover:bg-destructive/10 text-muted-foreground rounded-lg"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {session.snippet && (
                    <p
                      className="text-xs text-muted-foreground/70 line-clamp-1 mb-2 pl-[46px]"
                      dangerouslySetInnerHTML={{
                        __html: search.trim()
                          ? session.snippet.slice(0, 40).replace(new RegExp(search.trim(), 'gi'), match => `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`)
                          : session.snippet.slice(0, 40)
                      }}
                    />
                  )}

                  <div className="flex items-center gap-1.5 mt-auto flex-wrap pl-[46px]">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${sourceColor[src] || sourceColor.web}`}>
                      {sourceLabel[src] || src}
                    </span>
                    {curMode && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium inline-flex items-center gap-0.5 ${modeAccentRing[curMode.accent] ?? modeAccentRing.neutral}`}>
                        <span>{curMode.icon}</span>{curMode.label}
                      </span>
                    )}
                    <span className="text-[10px] text-muted-foreground">
                      {format(session.updated_at * 1000, "MM-dd HH:mm")}
                    </span>
                    <span className="text-[10px] text-muted-foreground ml-auto truncate max-w-[100px]">
                      {session.model.split('/').pop() || session.model}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Pagination Controls */}
        {sessions.length > 0 && (
          <div className="flex items-center justify-center mt-8 gap-4 pb-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1 || loading}
            >
              <ChevronLeft className="h-4 w-4 mr-1" /> 上一页
            </Button>
            <span className="text-sm text-muted-foreground">
              第 {page} 页
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage(p => p + 1)}
              disabled={!hasMore || loading}
            >
              下一页 <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
