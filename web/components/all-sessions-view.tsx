"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { format } from "date-fns";
import { zhCN } from "date-fns/locale";
import { SessionInfo, fetchSessions, renameSession, deleteSession } from "@/lib/api";
import { Loader2, Search, Calendar, MessageSquare, ChevronLeft, ChevronRight, Pencil, Trash2, Check, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

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
  const limit = 20;

  const loadSessions = useCallback(async (pageNum: number, q: string) => {
    setLoading(true);
    try {
      const offset = (pageNum - 1) * limit;
      const data = await fetchSessions(limit, offset, q || undefined);
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
      loadSessions(1, q);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, loadSessions]);

  useEffect(() => {
    if (page > 1) {
      loadSessions(page, search.trim());
    }
  }, [page, search, loadSessions]);

  const commitRename = async (id: string) => {
    const title = editingTitle.trim();
    if (title) {
      await renameSession(id, title);
      setSessions(prev => prev.map(s => s.id === id ? { ...s, title } : s));
    }
    setEditingId(null);
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm("确定要删除这个对话吗？")) return;
    await deleteSession(id);
    setSessions(prev => prev.filter(s => s.id !== id));
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-background overflow-hidden">
      <div className="p-4 border-b border-border flex items-center justify-between shrink-0">
        <h1 className="text-lg font-semibold">全部历史对话</h1>
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
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {sessions.map((session) => {
              const sourceLabel: Record<string, string> = { lark: "飞书", repl: "REPL", web: "Web", heartbeat: "心跳" };
              const sourceColor: Record<string, string> = {
                lark: "bg-blue-500/15 text-blue-600 dark:text-blue-400",
                repl: "bg-purple-500/15 text-purple-600 dark:text-purple-400",
                web: "bg-green-500/15 text-green-600 dark:text-green-400",
                heartbeat: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
              };
              const src = session.source || "web";
              return (
                <div
                  key={session.id}
                  onClick={() => onSelectSession(session.id)}
                  className="group p-3 rounded-xl border border-border bg-card hover:border-primary/50 hover:shadow-md transition-all cursor-pointer flex flex-col"
                >
                  <div className="flex items-start gap-1 mb-0.5">
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
                        <button onClick={e => { e.stopPropagation(); commitRename(session.id); }} className="text-primary shrink-0"><Check className="h-3 w-3" /></button>
                        <button onClick={e => { e.stopPropagation(); setEditingId(null); }} className="text-muted-foreground shrink-0"><X className="h-3 w-3" /></button>
                      </div>
                    ) : (
                      <h3
                        className="font-semibold text-sm text-card-foreground line-clamp-2 leading-snug group-hover:text-primary transition-colors flex-1 min-w-0"
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
                        className="p-1 hover:text-foreground text-muted-foreground rounded"
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(session.id); }}
                        className="p-1 hover:text-destructive text-muted-foreground rounded"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>

                  {session.snippet && (
                    <p
                      className="text-xs text-muted-foreground/70 line-clamp-1 mb-2"
                      dangerouslySetInnerHTML={{
                        __html: search.trim()
                          ? session.snippet.slice(0, 40).replace(new RegExp(search.trim(), 'gi'), match => `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`)
                          : session.snippet.slice(0, 40)
                      }}
                    />
                  )}

                  <div className="flex items-center gap-1.5 mt-auto flex-wrap">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${sourceColor[src] || sourceColor.web}`}>
                      {sourceLabel[src] || src}
                    </span>
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
