"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Loader2, Plus, Trash2, Search, Book, Save, Pencil, X, ChevronRight, ChevronDown, Folder, FolderOpen, FileText } from "lucide-react";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";
import { ScrollArea } from "@ethan/shared/ui/scroll-area";
import { MdEditor } from "@ethan/shared/components/md-editor";
import {
  KnowledgeItem,
  fetchKnowledge,
  addKnowledge,
  updateKnowledge,
  deleteKnowledge,
  searchKnowledge,
} from "@/lib/api";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";

type PanelMode = "view" | "edit" | "add";

// ── 目录树构建 ──────────────────────────────────────────────────────
// 跨后端统一用 tags[0]（层级标签，如 "work/coze/prd"）推导目录层级，
// 与 filesystem/Obsidian/Notion 的多层级落点打平。无标签的条目落根目录。
type TreeNode = {
  name: string;
  path: string; // 到该节点的完整路径（用于展开态 key）
  children: Map<string, TreeNode>;
  items: KnowledgeItem[]; // 直接挂在该目录下的条目
};

function newNode(name: string, path: string): TreeNode {
  return { name, path, children: new Map(), items: [] };
}

function groupSegments(item: KnowledgeItem): string[] {
  const tag = item.tags?.[0]?.trim();
  if (!tag) return [];
  return tag.split("/").map(s => s.trim()).filter(Boolean);
}

function buildTree(items: KnowledgeItem[]): TreeNode {
  const root = newNode("", "");
  for (const item of items) {
    const segs = groupSegments(item);
    let node = root;
    let acc = "";
    for (const seg of segs) {
      acc = acc ? `${acc}/${seg}` : seg;
      let child = node.children.get(seg);
      if (!child) {
        child = newNode(seg, acc);
        node.children.set(seg, child);
      }
      node = child;
    }
    node.items.push(item);
  }
  return root;
}

// 收集所有 folder path，用于「默认全部展开」
function allFolderPaths(node: TreeNode, acc: Set<string>): void {
  for (const child of node.children.values()) {
    acc.add(child.path);
    allFolderPaths(child, acc);
  }
}

export function KnowledgeView() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [selected, setSelected] = useState<KnowledgeItem | null>(null);
  const [panelMode, setPanelMode] = useState<PanelMode>("view");
  const deepLinkHandled = useRef(false);

  const [search, setSearch] = useState("");
  const [searchMode, setSearchMode] = useState<"keyword" | "semantic">("keyword");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState<{ open: boolean; source: string }>({ open: false, source: "" });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [userToggled, setUserToggled] = useState(false); // 用户手动展开/折叠后不再自动全展开

  const isSearching = search.trim().length > 0;
  const tree = useMemo(() => buildTree(items), [items]);
  const [autoExpandedFor, setAutoExpandedFor] = useState<TreeNode | null>(null);

  // 数据变化时默认全部展开（用户手动操作过后不再覆盖）。
  // 用「渲染期按上一次快照调整 state」模式，避免 setState-in-effect 的级联渲染。
  if (!userToggled && !isSearching && tree !== autoExpandedFor) {
    const paths = new Set<string>();
    allFolderPaths(tree, paths);
    setExpanded(paths);
    setAutoExpandedFor(tree);
  }

  const toggleFolder = useCallback((path: string) => {
    setUserToggled(true);
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  // Form fields (shared between add and edit)
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editTags, setEditTags] = useState("");

  const loadData = useCallback(async (q?: string, mode: "keyword" | "semantic" = "keyword") => {
    setLoading(true);
    try {
      const data = q
        ? await searchKnowledge(q, 20, mode === "semantic")
        : await fetchKnowledge();
      setItems(data);
    } catch (err) {
      console.error("Failed to load knowledge", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    const sourceParam = searchParams.get("source");
    if (!sourceParam || deepLinkHandled.current || items.length === 0) return;
    const target = items.find(i => i.source === sourceParam);
    if (target) {
      setSelected(target);
      setPanelMode("view");
    }
    deepLinkHandled.current = true;
    router.replace("/knowledge", { scroll: false });
  }, [items, searchParams, router]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData(search.trim() || undefined, searchMode);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, searchMode, loadData]);

  function handleSelect(item: KnowledgeItem) {
    setSelected(item);
    setPanelMode("view");
  }

  function handleNewClick() {
    setSelected(null);
    setEditTitle("");
    setEditContent("");
    setEditTags("");
    setPanelMode("add");
  }

  function handleEditClick() {
    if (!selected) return;
    setEditTitle(selected.title);
    setEditContent(selected.content ?? "");
    setEditTags(selected.tags?.join(", ") ?? "");
    setPanelMode("edit");
  }

  function handleCancelEdit() {
    setPanelMode("view");
  }

  const handleSave = async () => {
    if (panelMode === "add") {
      if (!editTitle.trim() || !editContent.trim()) return;
      setSaving(true);
      try {
        const tags = editTags.split(",").map(t => t.trim()).filter(Boolean);
        await addKnowledge({ title: editTitle, content: editContent, tags });
        await loadData(search.trim() || undefined, searchMode);
        setPanelMode("view");
        setSelected(null);
      } catch (err) {
        console.error("Failed to add", err);
        alert("Failed to add item");
      } finally {
        setSaving(false);
      }
    } else if (panelMode === "edit" && selected) {
      if (!editTitle.trim() || !editContent.trim()) return;
      setSaving(true);
      try {
        const tags = editTags.split(",").map(t => t.trim()).filter(Boolean);
        await updateKnowledge(selected.source, { title: editTitle, content: editContent, tags });
        const updated: KnowledgeItem = { ...selected, title: editTitle, content: editContent, tags };
        setItems(prev => prev.map(i => i.source === selected.source ? updated : i));
        setSelected(updated);
        setPanelMode("view");
      } catch (err) {
        console.error("Failed to update", err);
        alert("Failed to update item");
      } finally {
        setSaving(false);
      }
    }
  };

  const handleDelete = (source: string) => {
    setConfirmState({ open: true, source });
  };

  const doDelete = async () => {
    const source = confirmState.source;
    setConfirmState({ open: false, source: "" });
    try {
      await deleteKnowledge(source);
      setItems(prev => prev.filter(i => i.source !== source));
      if (selected?.source === source) {
        setSelected(null);
        setPanelMode("view");
      }
    } catch (err) {
      console.error("Failed to delete", err);
      alert("Failed to delete item");
    }
  };

  const isFormMode = panelMode === "add" || panelMode === "edit";

  return (
    <div className="flex h-full w-full bg-background border-l border-border/40">
      <ConfirmDialog
        open={confirmState.open}
        title="删除知识条目"
        description="确定要删除这条知识吗？此操作无法撤销。"
        confirmLabel="删除"
        onConfirm={doDelete}
        onCancel={() => setConfirmState({ open: false, source: "" })}
      />

      {/* Sidebar */}
      <div className="w-64 border-r border-border/40 flex flex-col bg-muted/10 shrink-0">
        <div className="p-3 border-b border-border/40 flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2 text-sm">
            <Book className="w-4 h-4" />
            知识库
          </h2>
          <Button variant="ghost" size="icon" onClick={handleNewClick} title="添加知识">
            <Plus className="w-4 h-4" />
          </Button>
        </div>

        {/* Search */}
        <div className="p-2 border-b border-border/40 space-y-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="搜索..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="pl-8 h-8 text-xs"
            />
          </div>
          <button
            type="button"
            onClick={() => setSearchMode(m => m === "keyword" ? "semantic" : "keyword")}
            className={
              "w-full rounded border px-2 py-1 text-[11px] font-medium transition-colors " +
              (searchMode === "semantic"
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background text-muted-foreground hover:text-foreground hover:border-foreground/40")
            }
          >
            {searchMode === "semantic" ? "语义检索" : "关键词检索"}
          </button>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-2 space-y-0.5">
            {loading && items.length === 0 ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : items.length === 0 ? (
              <div className="p-4 text-xs text-muted-foreground text-center">
                {isSearching ? "无匹配结果" : "暂无知识条目"}
              </div>
            ) : isSearching ? (
              // 搜索态：平铺结果（跨目录），带所属目录路径提示
              items.map(item => {
                const segs = groupSegments(item);
                return (
                  <button
                    key={item.source}
                    type="button"
                    onClick={() => handleSelect(item)}
                    className={`w-full text-left px-2 py-1.5 rounded-md cursor-pointer transition-colors flex items-start gap-2 ${
                      selected?.source === item.source && panelMode !== "add"
                        ? "bg-primary/10 text-primary"
                        : "hover:bg-muted"
                    }`}
                  >
                    <FileText className="w-3.5 h-3.5 mt-0.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0">
                      <span className="block text-sm truncate">{item.title}</span>
                      {segs.length > 0 && (
                        <span className="block text-[10px] text-muted-foreground truncate">{segs.join(" / ")}</span>
                      )}
                    </span>
                  </button>
                );
              })
            ) : (
              <TreeView
                node={tree}
                depth={0}
                expanded={expanded}
                onToggle={toggleFolder}
                selectedSource={panelMode === "add" ? null : (selected?.source ?? null)}
                onSelect={handleSelect}
              />
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Main panel */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {/* Header */}
        <div className="p-4 border-b border-border/40 flex items-center justify-between bg-card shrink-0">
          <h2 className="font-semibold truncate flex-1 pr-4">
            {panelMode === "add"
              ? "添加知识"
              : panelMode === "edit"
              ? `编辑：${selected?.title}`
              : (selected?.title ?? "")}
          </h2>
          <div className="flex items-center gap-2 shrink-0">
            {isFormMode ? (
              <>
                <Button variant="ghost" size="sm" onClick={handleCancelEdit} className="gap-1.5">
                  <X className="h-4 w-4" />
                  取消
                </Button>
                <Button
                  size="sm"
                  onClick={handleSave}
                  disabled={saving || !editTitle.trim() || !editContent.trim()}
                  className="gap-1.5"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存
                </Button>
              </>
            ) : selected ? (
              <>
                <Button variant="ghost" size="sm" onClick={handleEditClick} className="gap-1.5">
                  <Pencil className="h-4 w-4" />
                  编辑
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-muted-foreground hover:text-destructive gap-1.5"
                  onClick={() => handleDelete(selected.source)}
                >
                  <Trash2 className="h-4 w-4" />
                  删除
                </Button>
              </>
            ) : null}
          </div>
        </div>

        {/* Body */}
        {isFormMode ? (
          <ScrollArea className="flex-1 p-6">
            <div className="max-w-3xl mx-auto space-y-4 pb-20">
              <div className="grid gap-2">
                <label className="text-sm font-medium">标题</label>
                <Input
                  placeholder="Title"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">标签（逗号分隔）</label>
                <Input
                  placeholder="tag1, tag2, tag3"
                  value={editTags}
                  onChange={e => setEditTags(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <label className="text-sm font-medium">内容</label>
                <MdEditor
                  value={editContent}
                  onChange={setEditContent}
                  placeholder="支持 Markdown 格式..."
                />
              </div>
            </div>
          </ScrollArea>
        ) : selected ? (
          <ScrollArea className="flex-1 p-6">
            <div className="max-w-3xl mx-auto pb-20 space-y-4">
              <div className="text-xs text-muted-foreground">来源：{selected.source}</div>
              {selected.tags && selected.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selected.tags.map(tag => (
                    <span key={tag} className="text-xs bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {selected.content && (
                <MdEditor
                  value={selected.content}
                  onChange={() => {}}
                />
              )}
            </div>
          </ScrollArea>
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            选择一条知识查看详情，或点击 <Plus className="h-3.5 w-3.5 mx-1" /> 添加新内容
          </div>
        )}
      </div>
    </div>
  );
}

// ── 目录树渲染 ──────────────────────────────────────────────────────
function TreeView({
  node,
  depth,
  expanded,
  onToggle,
  selectedSource,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  selectedSource: string | null;
  onSelect: (item: KnowledgeItem) => void;
}) {
  // 子目录名排序，条目按标题排序
  const folders = Array.from(node.children.values()).sort((a, b) => a.name.localeCompare(b.name));
  const items = [...node.items].sort((a, b) => a.title.localeCompare(b.title));

  return (
    <>
      {folders.map(child => {
        const isOpen = expanded.has(child.path);
        const count = countItems(child);
        return (
          <div key={child.path}>
            <button
              type="button"
              onClick={() => onToggle(child.path)}
              className="w-full text-left px-1.5 py-1 rounded-md hover:bg-muted transition-colors flex items-center gap-1 text-sm"
              style={{ paddingLeft: `${depth * 12 + 6}px` }}
            >
              {isOpen ? <ChevronDown className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
                      : <ChevronRight className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />}
              {isOpen ? <FolderOpen className="w-3.5 h-3.5 shrink-0 text-primary/70" />
                      : <Folder className="w-3.5 h-3.5 shrink-0 text-primary/70" />}
              <span className="truncate font-medium">{child.name}</span>
              <span className="ml-auto pl-1 text-[10px] text-muted-foreground shrink-0">{count}</span>
            </button>
            {isOpen && (
              <TreeView
                node={child}
                depth={depth + 1}
                expanded={expanded}
                onToggle={onToggle}
                selectedSource={selectedSource}
                onSelect={onSelect}
              />
            )}
          </div>
        );
      })}
      {items.map(item => (
        <button
          key={item.source}
          type="button"
          onClick={() => onSelect(item)}
          className={`w-full text-left px-1.5 py-1 rounded-md cursor-pointer transition-colors flex items-center gap-1.5 ${
            selectedSource === item.source ? "bg-primary/10 text-primary" : "hover:bg-muted"
          }`}
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <FileText className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate text-sm">{item.title}</span>
        </button>
      ))}
    </>
  );
}

function countItems(node: TreeNode): number {
  let n = node.items.length;
  for (const child of node.children.values()) n += countItems(child);
  return n;
}
