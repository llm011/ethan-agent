"use client";

import { useEffect, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  Fact, Episode, Procedure,
  fetchFacts, fetchEpisodes, fetchProcedures,
  deleteFact, updateFact, deleteEpisode, deleteProcedure,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, RefreshCw, Pencil, Trash2, Check, X } from "lucide-react";

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

// ── Main component ────────────────────────────────────────────────────────────

type Tab = "facts" | "episodes" | "procedures";

export function MemoryView() {
  const [activeTab, setActiveTab] = useState<Tab>("facts");
  const [facts, setFacts] = useState<Fact[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(false);

  // Index of the fact being edited (into the displayed list)
  const [editingFactIdx, setEditingFactIdx] = useState<number | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setEditingFactIdx(null);
    try {
      if (activeTab === "facts") {
        const data = await fetchFacts();
        // Filter out superseded facts (backend marks them with superseded: true)
        setFacts(data.filter((f: any) => !f.superseded));
      } else if (activeTab === "episodes") {
        const data = await fetchEpisodes();
        setEpisodes(data);
      } else {
        const data = await fetchProcedures();
        setProcedures(data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [activeTab]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Facts handlers ──────────────────────────────────────────────────────────

  // facts come from store._facts (all items, indexed), we need the original index.
  // Since we filter superseded on client, we need to track original indices.
  // Re-fetch after any mutation to get correct indices.
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

  const handleDeleteFact = async (fact: Fact) => {
    if (!window.confirm("确认删除这条记忆？")) return;
    // Find original index in allFacts
    const originalIdx = allFacts.findIndex((f: any) => f === (allFacts.find((af: any) =>
      af.content === fact.content && af.created_at === (fact as any).created_at
    )));
    const idx = allFacts.indexOf(allFacts.find((af: any) =>
      af.content === fact.content && af.created_at === (fact as any).created_at
    ));
    await deleteFact(String(idx));
    await loadFacts();
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

  const handleDeleteEpisode = async (episode: Episode) => {
    if (!window.confirm("确认删除这段历史？")) return;
    await deleteEpisode(episode.session_id);
    setEpisodes((prev) => prev.filter((e) => e.session_id !== episode.session_id));
  };

  // ── Procedures handlers ─────────────────────────────────────────────────────

  const handleDeleteProcedure = async (proc: Procedure) => {
    if (!window.confirm("确认删除这条行为准则？")) return;
    await deleteProcedure(proc.id);
    setProcedures((prev) => prev.filter((p) => p.id !== proc.id));
  };

  // ── Tabs ────────────────────────────────────────────────────────────────────

  const tabs: { key: Tab; label: string }[] = [
    { key: "facts", label: "事实记忆 (Facts)" },
    { key: "episodes", label: "对话历程 (Episodes)" },
    { key: "procedures", label: "行为准则 (Procedures)" },
  ];

  const handleRefresh = () => {
    if (activeTab === "facts") loadFacts();
    else loadData();
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
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
