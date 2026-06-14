"use client";

import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2, Plus, Trash2, Search, Book } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { KnowledgeItem, fetchKnowledge, addKnowledge, deleteKnowledge, searchKnowledge } from "@/lib/api";
import { ConfirmDialog } from "@/components/confirm-dialog";

export function KnowledgeView() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [search, setSearch] = useState("");
  const [searchMode, setSearchMode] = useState<"keyword" | "semantic">("keyword");
  const [loading, setLoading] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [confirmState, setConfirmState] = useState<{ open: boolean; source: string }>({ open: false, source: "" });

  // Add form state
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newTags, setNewTags] = useState("");
  const [addLoading, setAddLoading] = useState(false);

  // Fetch knowledge data
  const loadData = useCallback(async (q?: string, mode: "keyword" | "semantic" = "keyword") => {
    setLoading(true);
    try {
      let data: KnowledgeItem[];
      if (q) {
        data = await searchKnowledge(q, 20, mode === "semantic");
      } else {
        data = await fetchKnowledge();
      }
      setItems(data);
    } catch (err) {
      console.error("Failed to load knowledge", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Debounced search — re-runs when query or mode changes
  useEffect(() => {
    const timer = setTimeout(() => {
      loadData(search.trim() || undefined, searchMode);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, searchMode, loadData]);

  const handleDelete = (source: string) => {
    setConfirmState({ open: true, source });
  };

  const doDelete = async () => {
    const source = confirmState.source;
    setConfirmState({ open: false, source: "" });
    try {
      await deleteKnowledge(source);
      setItems(items.filter((item) => item.source !== source));
    } catch (err) {
      console.error("Failed to delete", err);
      alert("Failed to delete item");
    }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;

    setAddLoading(true);
    try {
      const tags = newTags.split(",").map(t => t.trim()).filter(Boolean);
      await addKnowledge({ title: newTitle, content: newContent, tags });
      setIsAdding(false);
      setNewTitle("");
      setNewContent("");
      setNewTags("");
      loadData(search.trim() || undefined, searchMode); // Refresh
    } catch (err) {
      console.error("Failed to add", err);
      alert("Failed to add item");
    } finally {
      setAddLoading(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-background">
      <ConfirmDialog
        open={confirmState.open}
        title="删除知识条目"
        description="确定要删除这条知识吗？此操作无法撤销。"
        confirmLabel="删除"
        onConfirm={doDelete}
        onCancel={() => setConfirmState({ open: false, source: "" })}
      />
      <header className="h-12 border-b border-border flex items-center justify-between px-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Book className="h-5 w-5" /> 知识库 (Knowledge Base)
        </h2>
        <Button onClick={() => setIsAdding(!isAdding)} size="sm">
          {isAdding ? "Cancel" : <><Plus className="h-4 w-4 mr-1" /> 添加内容</>}
        </Button>
      </header>

      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-2 max-w-lg">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search knowledge..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
          {/* Search mode toggle */}
          <button
            type="button"
            onClick={() => setSearchMode(m => m === "keyword" ? "semantic" : "keyword")}
            className={
              "shrink-0 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors " +
              (searchMode === "semantic"
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background text-muted-foreground hover:text-foreground hover:border-foreground/40")
            }
            title={searchMode === "semantic" ? "切换为关键词检索" : "切换为语义检索"}
          >
            {searchMode === "semantic" ? "语义检索" : "关键词检索"}
          </button>
        </div>
      </div>

      {isAdding && (
        <div className="p-4 border-b border-border bg-muted/30">
          <form onSubmit={handleAdd} className="max-w-2xl space-y-4">
            <h3 className="font-medium">Add New Knowledge</h3>
            <div>
              <Input
                placeholder="Title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                required
              />
            </div>
            <div>
              <textarea
                placeholder="Content"
                value={newContent}
                onChange={(e) => setNewContent(e.target.value)}
                required
                className="w-full resize-none bg-background border border-input rounded-md px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring min-h-[100px]"
              />
            </div>
            <div>
              <Input
                placeholder="Tags (comma separated)"
                value={newTags}
                onChange={(e) => setNewTags(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setIsAdding(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={addLoading}>
                {addLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                Save Knowledge
              </Button>
            </div>
          </form>
        </div>
      )}

      <ScrollArea className="flex-1 p-4">
        {loading && items.length === 0 ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No knowledge items found.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {items.map((item) => (
              <div key={item.source} className="border border-border rounded-lg p-4 flex flex-col bg-card">
                <div className="flex justify-between items-start mb-2">
                  <h3 className="font-semibold text-card-foreground line-clamp-1 flex-1 pr-2" title={item.title}>
                    {item.title}
                  </h3>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 text-muted-foreground hover:text-destructive shrink-0"
                    onClick={() => handleDelete(item.source)}
                    title="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <div className="text-xs text-muted-foreground mb-3 truncate" title={item.source}>
                  Source: {item.source}
                </div>
                {item.content && (
                  <div className="text-xs text-card-foreground/80 mb-4 flex-1 overflow-hidden prose prose-sm dark:prose-invert max-w-none line-clamp-4">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {item.content.slice(0, 300)}
                    </ReactMarkdown>
                  </div>
                )}
                <div className="flex flex-wrap gap-1 mt-auto">
                  {item.tags?.map((tag) => (
                    <span key={tag} className="text-[10px] bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
