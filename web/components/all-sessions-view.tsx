"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { format } from "date-fns";
import { zhCN } from "date-fns/locale";
import { SessionInfo, fetchSessions } from "@/lib/api";
import { Loader2, Search, Calendar, MessageSquare, ChevronLeft, ChevronRight } from "lucide-react";
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

  return (
    <div className="flex-1 flex flex-col h-full bg-background overflow-hidden">
      <div className="p-6 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            全部历史对话
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            浏览和搜索所有历史会话记录
          </p>
        </div>
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索对话..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-background"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
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
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {sessions.map((session) => (
              <div
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className="group p-4 rounded-xl border border-border bg-card hover:border-primary/50 hover:shadow-md transition-all cursor-pointer flex flex-col h-40"
              >
                <div className="flex justify-between items-start mb-2 gap-2">
                  <h3 
                    className="font-semibold text-card-foreground line-clamp-2 leading-tight group-hover:text-primary transition-colors flex-1"
                    dangerouslySetInnerHTML={{
                      __html: search.trim() 
                        ? session.title.replace(new RegExp(search.trim(), 'gi'), match => `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`)
                        : session.title
                    }}
                  />
                </div>
                
                {session.snippet && (
                  <p 
                    className="text-xs text-muted-foreground line-clamp-3 mb-auto"
                    dangerouslySetInnerHTML={{
                      __html: session.snippet.replace(new RegExp(search.trim(), 'gi'), match => `<span class="bg-yellow-500/30 text-yellow-500 rounded px-0.5">${match}</span>`)
                    }}
                  />
                )}
                {!session.snippet && <div className="mb-auto"></div>}

                <div className="flex items-center justify-between mt-4 pt-3 border-t border-border/50 text-xs">
                  <div className="flex items-center text-muted-foreground gap-1.5">
                    <Calendar className="h-3.5 w-3.5" />
                    {format(session.updated_at * 1000, "MM-dd HH:mm")}
                  </div>
                  <Badge variant="secondary" className="text-[10px] font-normal px-1.5 py-0">
                    {session.model.split('/').pop() || session.model}
                  </Badge>
                </div>
              </div>
            ))}
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
