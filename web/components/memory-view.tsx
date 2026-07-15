"use client";

import { useEffect, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  Fact, Episode, Procedure, Insight, InsightsResponse, Signal,
  fetchFacts, fetchEpisodes, fetchProcedures,
  deleteFact, updateFact, deleteEpisode, deleteProcedure,
  fetchInsights, fetchInsightsByDate, fetchTodaySignals, fetchSignalsByDate,
  triggerConsolidation,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Loader2, RefreshCw, Pencil, Trash2, Check, X, ChevronLeft, ChevronRight, Calendar, Zap } from "lucide-react";

// ── Markdown helpers ──────────────────────────────────────────────────────────

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

// ── Split-pane inline editor ──────────────────────────────────────────────────

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
      <div className="grid grid-cols-2 divide-x divide-border/60 min-h-[160px]">
        {/* Left: textarea */}
        <textarea
          className="p-3 text-sm bg-muted/20 resize-none focus:outline-none font-mono text-foreground placeholder:text-muted-foreground"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="输入 Markdown 内容..."
          rows={8}
        />
        {/* Right: preview */}
        <div className="p-3 text-sm prose prose-sm dark:prose-invert max-w-none overflow-auto">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
            {fixBold(draft || "*预览为空*")}
          </ReactMarkdown>
        </div>
      </div>
      <div className="flex gap-2 justify-end p-2 bg-muted/10 border-t border-border/60">
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={saving}>
          <X className="h-3.5 w-3.5 mr-1" /> 取消
        </Button>
        <Button size="sm" onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Check className="h-3.5 w-3.5 mr-1" />}
          保存
        </Button>
      </div>
    </div>
  );
}

// ── Signal type label helpers ─────────────────────────────────────────────────

function signalTypeLabel(type: string): string {
  switch (type) {
    case "repetition": return "重复模式";
    case "error": return "错误总结";
    case "success_path": return "成功路径";
    default: return type;
  }
}

function signalTypeBadgeVariant(type: string): "default" | "destructive" | "secondary" {
  switch (type) {
    case "repetition": return "default";
    case "error": return "destructive";
    case "success_path": return "secondary";
    default: return "secondary";
  }
}

// ── Main component ────────────────────────────────────────────────────────────

type Tab = "facts" | "episodes" | "procedures" | "insights" | "signals";

export function MemoryView() {
  const [activeTab, setActiveTab] = useState<Tab>("insights");
  const [facts, setFacts] = useState<Fact[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(false);

  // Insights state
  const [insights, setInsights] = useState<Insight[]>([]);
  const [insightsTotal, setInsightsTotal] = useState(0);
  const [insightsPage, setInsightsPage] = useState(0);
  const [insightsDateFilter, setInsightsDateFilter] = useState("");
  const PAGE_SIZE = 20;

  // Signals state
  const [signals, setSignals] = useState<Signal[]>([]);
  const [signalsDateFilter, setSignalsDateFilter] = useState("");
  const [consolidating, setConsolidating] = useState(false);

  const [editingFactIdx, setEditingFactIdx] = useState<number | null>(null);
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    description: string;
    onConfirm: () => void;
  }>({ open: false, description: "", onConfirm: () => {} });

  const loadData = useCallback(async () => {
    setLoading(true);
    setEditingFactIdx(null);
    try {
      if (activeTab === "facts") {
        const data = await fetchFacts();
        setFacts(data.filter((f: any) => !f.superseded));
      } else if (activeTab === "episodes") {
        const data = await fetchEpisodes();
        setEpisodes(data);
      } else if (activeTab === "procedures") {
        const data = await fetchProcedures();
        setProcedures(data);
      } else if (activeTab === "insights") {
        if (insightsDateFilter) {
          const items = await fetchInsightsByDate(insightsDateFilter);
          setInsights(items);
          setInsightsTotal(items.length);
        } else {
          const resp = await fetchInsights(PAGE_SIZE, insightsPage * PAGE_SIZE);
          setInsights(resp.items);
          setInsightsTotal(resp.total);
        }
      } else if (activeTab === "signals") {
        if (signalsDateFilter) {
          const data = await fetchSignalsByDate(signalsDateFilter);
          setSignals(data);
        } else {
          const data = await fetchTodaySignals();
          setSignals(data);
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [activeTab, insightsPage, insightsDateFilter, signalsDateFilter]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Facts handlers ──────────────────────────────────────────────────────────

  const [allFacts, setAllFacts] = useState<any[]>([]);

  const loadFacts = useCallback(async () => {
    setLoading(true);
    setEditingFactIdx(null);
    try {
      const data = await fetchFacts();
      setAllFacts(data);
      setFacts(data.filter((f: any) => !f.superseded));
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === "facts") loadFacts();
  }, [activeTab, loadFacts]);

  const handleDeleteFact = (fact: Fact) => {
    setConfirmState({
      open: true,
      description: "确认删除这条记忆？",
      onConfirm: async () => {
        setConfirmState(prev => ({ ...prev, open: false }));
        const idx = allFacts.indexOf(allFacts.find((af: any) =>
          af.content === fact.content && af.created_at === (fact as any).created_at
        ));
        await deleteFact(String(idx));
        await loadFacts();
      },
    });
  };

  const handleSaveFact = async (fact: Fact, newContent: string) => {
    const idx = allFacts.indexOf(allFacts.find((af: any) =>
      af.content === fact.content && af.created_at === (fact as any).created_at
    ));
    await updateFact(String(idx), newContent);
    await loadFacts();
    setEditingFactIdx(null);
  };

  // ── Episodes handlers ───────────────────────────────────────────────────────

  const handleDeleteEpisode = (episode: Episode) => {
    setConfirmState({
      open: true,
      description: "确认删除这段历史？",
      onConfirm: async () => {
        setConfirmState(prev => ({ ...prev, open: false }));
        await deleteEpisode(episode.session_id);
        setEpisodes((prev) => prev.filter((e) => e.session_id !== episode.session_id));
      },
    });
  };

  // ── Procedures handlers ─────────────────────────────────────────────────────

  const handleDeleteProcedure = (proc: Procedure) => {
    setConfirmState({
      open: true,
      description: "确认删除这条行为准则？",
      onConfirm: async () => {
        setConfirmState(prev => ({ ...prev, open: false }));
        await deleteProcedure(proc.id);
        setProcedures((prev) => prev.filter((p) => p.id !== proc.id));
      },
    });
  };

  // ── Consolidation handler ───────────────────────────────────────────────────

  const handleConsolidate = async () => {
    setConsolidating(true);
    try {
      const result = await triggerConsolidation();
      alert(`沉淀完成，新增 ${result.added} 条记忆`);
      if (activeTab === "insights") loadData();
    } catch (err) {
      alert("沉淀失败");
    } finally {
      setConsolidating(false);
    }
  };

  // ── Tabs ────────────────────────────────────────────────────────────────────

  const tabs: { key: Tab; label: string }[] = [
    { key: "insights", label: "永久记忆" },
    { key: "signals", label: "每日信号" },
    { key: "facts", label: "事实 (Facts)" },
    { key: "episodes", label: "对话历程" },
    { key: "procedures", label: "行为准则" },
  ];

  const handleRefresh = () => {
    if (activeTab === "facts") loadFacts();
    else loadData();
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <ConfirmDialog
        open={confirmState.open}
        description={confirmState.description}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState(prev => ({ ...prev, open: false }))}
      />
      {/* Header / Tabs */}
      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <div className="flex gap-4">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={`text-sm font-medium transition-colors hover:text-primary ${
                activeTab === tab.key ? "text-primary" : "text-muted-foreground"
              }`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <Button variant="ghost" size="icon" onClick={handleRefresh} disabled={loading}>
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
        </Button>
      </header>

      <ScrollArea className="flex-1">
        <div className="p-4 pb-6 max-w-5xl mx-auto w-full">

          {/* ── Insights Tab ───────────────────────────────────────────────── */}
          {activeTab === "insights" && (
            <div className="space-y-3">
              {/* Date filter + pagination controls */}
              <div className="flex items-center justify-between gap-4 mb-4">
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <input
                    type="date"
                    className="text-sm px-2 py-1 border border-border rounded bg-background"
                    value={insightsDateFilter}
                    onChange={(e) => { setInsightsDateFilter(e.target.value); setInsightsPage(0); }}
                  />
                  {insightsDateFilter && (
                    <Button variant="ghost" size="sm" onClick={() => setInsightsDateFilter("")}>
                      清除
                    </Button>
                  )}
                </div>
                {!insightsDateFilter && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span>{insightsTotal} 条</span>
                    <Button
                      variant="ghost" size="icon" className="h-7 w-7"
                      disabled={insightsPage === 0}
                      onClick={() => setInsightsPage(p => Math.max(0, p - 1))}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span>{insightsPage + 1}/{Math.max(1, Math.ceil(insightsTotal / PAGE_SIZE))}</span>
                    <Button
                      variant="ghost" size="icon" className="h-7 w-7"
                      disabled={(insightsPage + 1) * PAGE_SIZE >= insightsTotal}
                      onClick={() => setInsightsPage(p => p + 1)}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                )}
              </div>

              {loading && insights.length === 0 && (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loading && insights.length === 0 && (
                <div className="text-center text-muted-foreground py-12 text-sm">
                  暂无永久记忆
                  <p className="mt-2 text-xs">每晚 0 点会自动从当日信号中沉淀有价值的记忆</p>
                </div>
              )}
              {insights.map((insight) => (
                <Card key={insight.id} className="shadow-none border-border/60 bg-muted/10">
                  <CardHeader className="pb-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={signalTypeBadgeVariant(insight.metadata.type || "")}>
                        {signalTypeLabel(insight.metadata.type || "unknown")}
                      </Badge>
                      {insight.metadata.date && (
                        <span className="text-xs text-muted-foreground">{insight.metadata.date}</span>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {fixBold(insight.text || "*Empty*")}
                      </ReactMarkdown>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* ── Signals Tab ────────────────────────────────────────────────── */}
          {activeTab === "signals" && (
            <div className="space-y-3">
              {/* Date filter + consolidation button */}
              <div className="flex items-center justify-between gap-4 mb-4">
                <div className="flex items-center gap-2">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <input
                    type="date"
                    className="text-sm px-2 py-1 border border-border rounded bg-background"
                    value={signalsDateFilter}
                    onChange={(e) => setSignalsDateFilter(e.target.value)}
                  />
                  {signalsDateFilter && (
                    <Button variant="ghost" size="sm" onClick={() => setSignalsDateFilter("")}>
                      清除 (查看今日)
                    </Button>
                  )}
                </div>
                <Button
                  variant="outline" size="sm"
                  onClick={handleConsolidate}
                  disabled={consolidating}
                >
                  {consolidating ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <Zap className="h-3.5 w-3.5 mr-1" />
                  )}
                  手动沉淀
                </Button>
              </div>

              {loading && signals.length === 0 && (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loading && signals.length === 0 && (
                <div className="text-center text-muted-foreground py-12 text-sm">
                  {signalsDateFilter ? `${signalsDateFilter} 无信号记录` : "今日暂无信号"}
                  <p className="mt-2 text-xs">信号在每 10 轮用户消息时自动采集</p>
                </div>
              )}
              {signals.map((sig, i) => (
                <Card key={i} className="shadow-none border-border/60 bg-muted/10">
                  <CardHeader className="pb-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={signalTypeBadgeVariant(sig.type)}>
                        {signalTypeLabel(sig.type)}
                      </Badge>
                      {sig.ts && (
                        <span className="text-xs text-muted-foreground">
                          {new Date(sig.ts * 1000).toLocaleTimeString()}
                        </span>
                      )}
                      {sig.count && (
                        <Badge variant="outline" className="text-[10px]">
                          {sig.count}次
                        </Badge>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0 space-y-1">
                    {sig.type === "repetition" && (
                      <>
                        <p className="text-sm">{sig.pattern}</p>
                        {sig.suggestion && (
                          <p className="text-xs text-muted-foreground italic">建议：{sig.suggestion}</p>
                        )}
                      </>
                    )}
                    {sig.type === "error" && (
                      <>
                        <p className="text-sm">{sig.context}</p>
                        {sig.resolution && (
                          <p className="text-xs text-muted-foreground italic">改进：{sig.resolution}</p>
                        )}
                      </>
                    )}
                    {sig.type === "success_path" && (
                      <>
                        <p className="text-sm">{sig.scenario}</p>
                        {sig.method && (
                          <p className="text-xs text-muted-foreground italic">方法：{sig.method}</p>
                        )}
                      </>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* ── Facts Tab ─────────────────────────────────────────────────── */}
          {activeTab === "facts" && (
            <div className="space-y-3">
              {loading && facts.length === 0 && (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loading && facts.length === 0 && (
                <div className="text-center text-muted-foreground py-12 text-sm">
                  暂无事实记忆
                </div>
              )}
              {facts.map((fact, i) => (
                <Card key={i} className="shadow-none border-border/60 bg-muted/10">
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-center gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide shrink-0">
                          {(fact as any).category || "knowledge"}
                        </span>
                        <Badge
                          variant={(fact as any).confidence > 0.8 ? "default" : "secondary"}
                          className="text-[10px] shrink-0"
                        >
                          {Math.round(((fact as any).confidence ?? 0.8) * 100)}%
                        </Badge>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-foreground"
                          onClick={() => setEditingFactIdx(editingFactIdx === i ? null : i)}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={() => handleDeleteFact(fact)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                    <CardDescription className="text-[11px]">
                      {(fact as any).created_at
                        ? new Date((fact as any).created_at * 1000).toLocaleString()
                        : ""}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="pt-0">
                    {editingFactIdx === i ? (
                      <InlineEditor
                        initialValue={fact.content}
                        onSave={(val) => handleSaveFact(fact, val)}
                        onCancel={() => setEditingFactIdx(null)}
                      />
                    ) : (
                      <div className="prose prose-sm dark:prose-invert max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                          {fixBold(fact.content || "*Empty*")}
                        </ReactMarkdown>
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* ── Episodes Tab ───────────────────────────────────────────────── */}
          {activeTab === "episodes" && (
            <div className="space-y-3">
              {loading && episodes.length === 0 && (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loading && episodes.length === 0 && (
                <div className="text-center text-muted-foreground py-12 text-sm">
                  暂无对话历程
                </div>
              )}
              {episodes.map((episode, i) => (
                <Card key={i} className="shadow-none border-border/60 bg-muted/10">
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-start gap-2">
                      <div className="flex flex-col gap-1 min-w-0">
                        <CardTitle className="text-sm font-semibold">
                          {new Date(episode.timestamp * 1000).toLocaleString()}
                        </CardTitle>
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className="text-[10px]">
                            {episode.turn_count} turns
                          </Badge>
                          {episode.model && (
                            <span className="text-[10px] text-muted-foreground">{episode.model}</span>
                          )}
                        </div>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                        onClick={() => handleDeleteEpisode(episode)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <div className="prose prose-sm dark:prose-invert max-w-none mb-3">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {fixBold(episode.summary || "*Empty*")}
                      </ReactMarkdown>
                    </div>
                    {episode.keywords?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {episode.keywords.map((kw, j) => (
                          <Badge key={j} variant="outline" className="text-[10px]">
                            {kw}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          {/* ── Procedures Tab ─────────────────────────────────────────────── */}
          {activeTab === "procedures" && (
            <div className="space-y-3">
              {loading && procedures.length === 0 && (
                <div className="flex justify-center py-12">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              )}
              {!loading && procedures.length === 0 && (
                <div className="text-center text-muted-foreground py-12 text-sm">
                  暂无行为准则
                </div>
              )}
              {procedures.map((proc, i) => (
                <Card key={i} className="shadow-none border-border/60 bg-muted/10">
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-start gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <Badge variant="secondary" className="text-[10px] shrink-0">
                          命中 {proc.hit_count} 次
                        </Badge>
                        <CardDescription className="text-[11px]">
                          {proc.created_at
                            ? new Date(proc.created_at * 1000).toLocaleString()
                            : ""}
                        </CardDescription>
                      </div>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-destructive shrink-0"
                        onClick={() => handleDeleteProcedure(proc)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {fixBold(proc.rule || "*Empty*")}
                      </ReactMarkdown>
                    </div>
                    {proc.context && (
                      <p className="text-xs text-muted-foreground mt-2 italic">{proc.context}</p>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

        </div>
      </ScrollArea>
    </div>
  );
}
