"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  DailySummary,
  StructuredMemory,
  StructuredMemoryType,
  fetchDailySummariesPage,
  fetchStructuredMemoriesPage,
  forgetStructuredMemory,
  triggerStructuredConsolidation,
  updateStructuredMemory,
  wakeStructuredMemory,
} from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader } from "@ethan/shared/ui/card";
import { ScrollArea } from "@ethan/shared/ui/scroll-area";
import { Button } from "@ethan/shared/ui/button";
import { HeaderFillet } from "@/components/header-fillet";
import { Badge } from "@ethan/shared/ui/badge";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";
import {
  MEMORY_PAGE_SIZE,
  appendPage,
  hasMoreAfter,
} from "@ethan/shared/lib/memory-paging";
import { scrollContainerToTop, useDoubleTapTab } from "@ethan/shared/lib/use-memory-list";
import { Archive, Calendar, Check, Loader2, Pencil, RefreshCw, RotateCcw, Trash2, X, Zap } from "lucide-react";

const CJK = /[一-鿿㐀-䶿　-〿＀-￯⺀-⻿]/;
function fixBold(text: string): string {
  let fixed = text.replace(/\*\*\s+([^\*]+?)\s+\*\*/g, "**$1**");
  fixed = fixed
    .replace(/([^\s*_\\`])\*\*/g, (match, c) => (CJK.test(c) ? `${c}​**` : `${c} **`))
    .replace(/\*\*([^\s*_\\`])/g, (match, c) => (CJK.test(c) ? `**​${c}` : `** ${c}`));
  return fixed;
}

const markdownComponents = {
  pre: ({ children }: any) => (
    <pre className="bg-background/50 rounded-lg p-3 overflow-x-auto text-xs">{children}</pre>
  ),
  code: ({ className, children, ...props }: any) => {
    const isInline = !className;
    return isInline ? (
      <code className="bg-background/50 px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
    ) : (
      <code className={className} {...props}>{children}</code>
    );
  },
};

interface InlineEditorProps {
  initialValue: string;
  onSave: (value: string) => Promise<void>;
  onCancel: () => void;
}

function InlineEditor({ initialValue, onSave, onCancel }: InlineEditorProps) {
  const [draft, setDraft] = useState(initialValue);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3 border border-primary/40 rounded-xl overflow-hidden">
      <div className="grid grid-cols-1 md:grid-cols-2 md:divide-x divide-border/60 min-h-[160px]">
        <textarea
          className="p-3 text-sm bg-muted/20 resize-none focus:outline-none font-mono text-foreground"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="输入 Markdown 内容..."
          rows={8}
        />
        <div className="p-3 text-sm prose prose-sm dark:prose-invert max-w-none overflow-auto border-t md:border-t-0 border-border/60">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {fixBold(draft || "*预览为空*")}
          </ReactMarkdown>
        </div>
      </div>
      <div className="flex gap-2 justify-end p-2 bg-muted/10 border-t border-border/60">
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
          <X className="h-3.5 w-3.5 mr-1" /> 取消
        </Button>
        <Button size="sm" onClick={handleSave} disabled={saving || !draft.trim()}>
          {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1" />}
          保存
        </Button>
      </div>
    </div>
  );
}

type Tab = "personal" | "preference" | "methodology" | "activity" | "decisions" | "companion" | "daily";

interface TabConfig {
  key: Tab;
  label: string;
  types?: StructuredMemoryType[];
  domain?: "general" | "companion";
  empty: string;
}

const TABS: TabConfig[] = [
  { key: "personal", label: "个人信息", types: ["personal_information"], domain: "general", empty: "暂无个人信息" },
  { key: "preference", label: "偏好", types: ["preference"], domain: "general", empty: "暂无偏好" },
  { key: "methodology", label: "方法论", types: ["methodology"], domain: "general", empty: "暂无方法论" },
  { key: "activity", label: "正在做的事", types: ["activity"], domain: "general", empty: "暂无活动或目标" },
  { key: "decisions", label: "决定与约定", types: ["decision", "relationship"], domain: "general", empty: "暂无决定或约定" },
  { key: "companion", label: "苏念记忆", types: ["companion"], domain: "companion", empty: "暂无苏念记忆" },
  { key: "daily", label: "每日摘要", empty: "暂无每日摘要" },
];

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    candidate: "候选",
    active: "生效",
    disputed: "冲突",
    superseded: "已替代",
    expired: "已过期",
    forgotten: "已遗忘",
    dormant: "已归档",
  };
  return labels[status] || status;
}

function MemoryCard({
  memory,
  editing,
  onEdit,
  onSave,
  onDelete,
  onWake,
}: {
  memory: StructuredMemory;
  editing: boolean;
  onEdit: () => void;
  onSave: (content: string) => Promise<void>;
  onDelete: () => void;
  onWake?: () => void;
}) {
  const dormant = memory.status === "dormant";
  return (
    <Card className="shadow-none border-border/60 bg-muted/10">
      <CardHeader className="pb-2">
        <div className="flex justify-between items-start gap-3">
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <Badge variant={memory.status === "active" ? "default" : "secondary"}>{statusLabel(memory.status)}</Badge>
            <Badge variant="outline">{memory.dimension}</Badge>
            <span className="text-[11px] text-muted-foreground">
              {memory.scope_type}:{memory.scope_id}
            </span>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {dormant ? (
              onWake && (
                <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onWake} aria-label="唤醒记忆">
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              )
            ) : (
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onEdit} aria-label="编辑记忆">
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            )}
            <Button variant="ghost" size="icon" className="h-7 w-7 hover:text-destructive" onClick={onDelete} aria-label="遗忘记忆">
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        <CardDescription className="text-[11px]">
          {new Date(memory.updated_at * 1000).toLocaleString()} · {Math.round(memory.confidence * 100)}% 置信度
          {memory.source_session_id ? ` · 来源 ${memory.source_session_id}` : ""}
          {dormant && memory.dormant_at ? ` · 归档于 ${new Date(memory.dormant_at * 1000).toLocaleDateString()}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        {editing ? (
          <InlineEditor initialValue={memory.content} onSave={onSave} onCancel={onEdit} />
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {fixBold(memory.content || "*Empty*")}
            </ReactMarkdown>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DailySummaryCard({ summary }: { summary: DailySummary }) {
  return (
    <Card className="shadow-none border-border/60 bg-muted/10">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Badge variant={summary.memory_domain === "companion" ? "secondary" : "default"}>
            {summary.memory_domain === "companion" ? "苏念" : "普通"}
          </Badge>
          <span className="text-sm font-medium">{summary.local_date}</span>
        </div>
        <CardDescription className="text-[11px]">pipeline {summary.pipeline_version}</CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {fixBold(summary.summary_text || "*Empty*")}
          </ReactMarkdown>
        </div>
      </CardContent>
    </Card>
  );
}

export function MemoryView() {
  const [activeTab, setActiveTab] = useState<Tab>("personal");
  const [memories, setMemories] = useState<StructuredMemory[]>([]);
  const [summaries, setSummaries] = useState<DailySummary[]>([]);
  const [dateFilter, setDateFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [consolidating, setConsolidating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showDormant, setShowDormant] = useState(false);
  const [error, setError] = useState("");
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    description: string;
    onConfirm: () => void;
  }>({ open: false, description: "", onConfirm: () => {} });
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  // 分页：hasMore 由后端 total 推；loadingMore 防重入（滚到底会连续触发）
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 3000);
    return () => clearTimeout(t);
  }, [notice]);

  const activeConfig = useMemo(() => TABS.find(tab => tab.key === activeTab) || TABS[0], [activeTab]);

  // 按日期查摘要时不分页（一天通常 1-2 条）；只有「全部日期」才翻页
  const dailyPaged = activeTab === "daily" && !dateFilter;

  const loadData = useCallback(async (offset = 0) => {
    if (offset === 0) setLoading(true);
    setEditingId(null);
    setError("");
    try {
      if (activeTab === "daily") {
        const page = await fetchDailySummariesPage({
          date: dateFilter || undefined,
          limit: dailyPaged ? MEMORY_PAGE_SIZE : 90,
          offset,
        });
        if (offset > 0) {
          setSummaries(prev => [...prev, ...page.items]);
        } else {
          setSummaries(page.items);
        }
        setHasMore(hasMoreAfter(page.items, page.total ?? undefined, offset));
        setMemories([]);
        return;
      }
      // 多 type 一次请求（逗号分隔），一个 offset —— 各 type 各分页会错乱
      const types = activeConfig.types || [];
      const page = await fetchStructuredMemoriesPage({
        type: types.length === 1 ? types[0] : types,
        status: showDormant ? "dormant" : "active",
        domain: activeConfig.domain || "general",
        limit: MEMORY_PAGE_SIZE,
        offset,
      });
      const sorted = [...page.items].sort(
        (a, b) => b.importance - a.importance || b.updated_at - a.updated_at,
      );
      if (offset > 0) {
        // 追加分页：不能重排整体（会把已翻出来的页顺序打乱），只在尾部并入
        setMemories(prev => appendPage(prev, sorted));
      } else {
        setMemories(sorted);
      }
      setHasMore(hasMoreAfter(page.items, page.total, offset));
      setSummaries([]);
    } catch (err) {
      console.error(err);
      setError("加载记忆失败，请稍后重试");
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [activeConfig, activeTab, dateFilter, showDormant, dailyPaged]);

  useEffect(() => {
    loadData(0);
  }, [loadData]);

  /** 滚到底加载下一页。offset 用当前已加载条数（不是页号）。 */
  const loadMore = useCallback(() => {
    if (loadingMore || loading || !hasMore) return;
    setLoadingMore(true);
    const loaded = activeTab === "daily" ? summaries.length : memories.length;
    loadData(loaded);
  }, [activeTab, summaries.length, memories.length, hasMore, loading, loadingMore, loadData]);

  // 哨兵进入视野 → 拉下一页。用 IntersectionObserver 而不是 scroll 事件：
  // 不必每帧读 scrollHeight 触发同步布局。
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasMore || loading || loadingMore) return;
    const observer = new IntersectionObserver(
      entries => { if (entries.some(e => e.isIntersecting)) loadMore(); },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loading, loadingMore, loadMore]);

  const scrollToTop = useCallback(() => scrollContainerToTop(viewportRef.current), []);

  // 单击切 tab（延迟 ~300ms 生效）、双击「切到该 tab + 回到顶部」
  const handleTabClick = useDoubleTapTab<Tab>(
    useCallback((key: Tab) => setActiveTab(key), []),
    useCallback((key: Tab) => {
      setActiveTab(key);
      scrollToTop();
    }, [scrollToTop]),
  );

  const handleSave = async (memory: StructuredMemory, content: string) => {
    await updateStructuredMemory(memory.id, { content });
    setEditingId(null);
    await loadData();
  };

  const handleDelete = (memory: StructuredMemory) => {
    setConfirmState({
      open: true,
      description: memory.status === "dormant"
        ? "这条记忆已归档（不再参与召回）。确认彻底遗忘？内容和来源引用将被清除，操作不可撤销。"
        : "确认遗忘这条结构化记忆？内容和来源引用将被清除，操作不可撤销。",
      onConfirm: async () => {
        setConfirmState(prev => ({ ...prev, open: false }));
        await forgetStructuredMemory(memory.id);
        await loadData();
      },
    });
  };

  const handleWake = async (memory: StructuredMemory) => {
    try {
      await wakeStructuredMemory(memory.id);
      setNotice({ type: "success", text: "记忆已唤醒，重新参与召回" });
      await loadData();
    } catch (err) {
      console.error(err);
      setNotice({ type: "error", text: "唤醒记忆失败" });
    }
  };

  const handleConsolidate = async () => {
    setConsolidating(true);
    try {
      const result = await triggerStructuredConsolidation(dateFilter || undefined);
      const data = result.result;
      setNotice({ type: "success", text: `结构化沉淀完成：${String(data.candidates ?? 0)} 个候选，${String(data.admitted ?? 0)} 条生效记忆` });
      await loadData();
    } catch (err) {
      console.error(err);
      setNotice({ type: "error", text: "结构化沉淀失败" });
    } finally {
      setConsolidating(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <ConfirmDialog
        open={confirmState.open}
        description={confirmState.description}
        destructive
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState(prev => ({ ...prev, open: false }))}
      />

      <header className="relative h-12 border-b border-border bg-sidebar flex items-center px-4 gap-3 shrink-0">
        <HeaderFillet />
        <div className="flex-1 overflow-x-auto">
          <div className="flex gap-4 min-w-max pr-2">
            {TABS.map(tab => (
              <button
                key={tab.key}
                className={`text-sm font-medium transition-colors hover:text-primary whitespace-nowrap ${
                  activeTab === tab.key ? "text-primary" : "text-muted-foreground"
                }`}
                onClick={() => handleTabClick(tab.key)}
                title="双击回到顶部"
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <Button
          variant={showDormant ? "default" : "ghost"}
          size="sm"
          onClick={() => setShowDormant(prev => !prev)}
          disabled={activeTab === "daily"}
          aria-label="切换归档视图"
        >
          <Archive className="h-3.5 w-3.5 mr-1" />
          归档
        </Button>
        <Button variant="ghost" size="icon" onClick={() => loadData()} disabled={loading} aria-label="刷新记忆">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
        </Button>
      </header>

      <ScrollArea className="flex-1" viewportRef={viewportRef}>
        <div className="p-4 pb-6 max-w-5xl mx-auto w-full space-y-3">
          {activeTab === "daily" && (
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div className="flex items-center gap-2">
                <Calendar className="h-4 w-4 text-muted-foreground" />
                <input
                  type="date"
                  className="text-sm px-2 py-1 border border-border rounded bg-background"
                  value={dateFilter}
                  onChange={event => setDateFilter(event.target.value)}
                />
                {dateFilter && <Button variant="ghost" size="sm" onClick={() => setDateFilter("")}>清除</Button>}
              </div>
              <Button variant="outline" size="sm" onClick={handleConsolidate} disabled={consolidating}>
                {consolidating ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Zap className="h-3.5 w-3.5 mr-1" />}
                结构化沉淀
              </Button>
            </div>
          )}

          {loading && memories.length === 0 && summaries.length === 0 && (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
          {notice && (
            <div className={`text-center text-sm py-2 rounded-md ${notice.type === "success" ? "bg-green-500/10 text-green-600" : "bg-destructive/10 text-destructive"}`}>
              {notice.text}
            </div>
          )}
          {error && <div className="text-center text-destructive py-8 text-sm">{error}</div>}
          {!loading && !error && activeTab !== "daily" && memories.length === 0 && (
            <div className="text-center text-muted-foreground py-12 text-sm">
              {showDormant ? "暂无归档记忆" : activeConfig.empty}
              <p className="mt-2 text-xs">结构化记忆会在每 5 轮对话和每日沉淀时更新</p>
            </div>
          )}
          {!loading && !error && activeTab === "daily" && summaries.length === 0 && (
            <div className="text-center text-muted-foreground py-12 text-sm">
              {activeConfig.empty}
              <p className="mt-2 text-xs">每日按普通与苏念两个 domain 独立压缩</p>
            </div>
          )}

          {activeTab !== "daily" && memories.map(memory => (
            <MemoryCard
              key={memory.id}
              memory={memory}
              editing={editingId === memory.id}
              onEdit={() => setEditingId(editingId === memory.id ? null : memory.id)}
              onSave={content => handleSave(memory, content)}
              onDelete={() => handleDelete(memory)}
              onWake={() => handleWake(memory)}
            />
          ))}
          {activeTab === "daily" && summaries.map(summary => <DailySummaryCard key={summary.id} summary={summary} />)}

          {/* 分页哨兵：进入视野就拉下一页；hasMore 时显示转圈 */}
          <div ref={sentinelRef} className="h-px" aria-hidden />
          {hasMore && (
            <div className="flex justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
