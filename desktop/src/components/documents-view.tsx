import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronDown, ChevronRight, FileText, Folder, FolderOpen, Loader2,
  Pin, PinOff, RefreshCw, Search, Star, X, MessageSquare, Trash2,
  Maximize2, Minimize2,
} from "lucide-react";
import { Button } from "@ethan/shared/ui/button";
import { Input } from "@ethan/shared/ui/input";
import { ScrollArea } from "@ethan/shared/ui/scroll-area";
import { ConfirmDialog } from "@ethan/shared/components/confirm-dialog";
import {
  DocNode,
  DocDetail,
  fetchDocumentTree,
  fetchDocument,
  updateDocumentMeta,
  deleteDocument,
} from "@/lib/api";

/** 从树里筛出收藏/置顶的文件（含其相对路径）。 */
function collectFlagged(nodes: DocNode[], key: "favorite" | "pinned"): DocNode[] {
  const out: DocNode[] = [];
  const walk = (list: DocNode[]) => {
    for (const n of list) {
      if (n.is_dir) walk(n.children ?? []);
      else if (n[key]) out.push(n);
    }
  };
  walk(nodes);
  return out;
}

/** 按关键词过滤树：命中文件保留，其祖先目录保留（保证层级完整）。 */
function filterTree(nodes: DocNode[], q: string): DocNode[] {
  if (!q.trim()) return nodes;
  const needle = q.toLowerCase();
  const walk = (list: DocNode[]): DocNode[] => {
    const out: DocNode[] = [];
    for (const n of list) {
      if (n.is_dir) {
        const kids = walk(n.children ?? []);
        // 目录名命中时整棵子树保留，否则只保留有命中后代的目录
        if (kids.length || n.name.toLowerCase().includes(needle)) {
          out.push({ ...n, children: kids.length ? kids : n.children });
        }
      } else if (n.name.toLowerCase().includes(needle)) {
        out.push(n);
      }
    }
    return out;
  };
  return walk(nodes);
}

function fileIcon(ext?: string) {
  return FileText;
}

/** 行操作回调集合（DocRow 与 DocFolder 共用，避免 props 逐个透传时类型漂移）。 */
interface RowActions {
  active: string;   // 当前选中文档的 path
  onOpen: (n: DocNode) => void;
  onTogglePin: (n: DocNode) => void;
  onToggleFavorite: (n: DocNode) => void;
  onLocate: (n: DocNode) => void;
  onDelete: (n: DocNode) => void;
}

/** 单个文件行。 */
function DocRow({ node, active, onOpen, onTogglePin, onToggleFavorite, onLocate, onDelete }: RowActions & { node: DocNode }) {
  const Icon = fileIcon(node.ext);
  return (
    <div
      className={`group flex items-center gap-2 rounded-md px-2 py-1.5 cursor-pointer text-sm transition-colors ${
        active === node.path ? "bg-accent text-accent-foreground" : "hover:bg-muted"
      }`}
      onClick={() => onOpen(node)}
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="truncate flex-1" title={node.path}>{node.name}</span>
      {node.pinned && <Pin className="h-3.5 w-3.5 shrink-0 text-primary" />}
      {node.favorite && !node.pinned && <Star className="h-3.5 w-3.5 shrink-0 text-amber-500" />}
      {/* 操作按钮：hover 显示，避免列表视觉噪音 */}
      <span className="hidden group-hover:flex items-center gap-0.5 shrink-0">
        <button
          className="p-1 rounded hover:bg-background/80"
          title={node.pinned ? "取消置顶" : "置顶"}
          onClick={(e) => { e.stopPropagation(); onTogglePin(node); }}
        >
          {node.pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
        </button>
        <button
          className="p-1 rounded hover:bg-background/80"
          title={node.favorite ? "取消收藏" : "收藏"}
          onClick={(e) => { e.stopPropagation(); onToggleFavorite(node); }}
        >
          <Star className={`h-3.5 w-3.5 ${node.favorite ? "fill-amber-500 text-amber-500" : ""}`} />
        </button>
        {node.session_id && (
          <button
            className="p-1 rounded hover:bg-background/80"
            title="定位到来源对话"
            onClick={(e) => { e.stopPropagation(); onLocate(node); }}
          >
            <MessageSquare className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          className="p-1 rounded hover:bg-background/80 hover:text-destructive"
          title="删除"
          onClick={(e) => { e.stopPropagation(); onDelete(node); }}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </span>
    </div>
  );
}

/** 目录节点（可展开/收起）。 */
function DocFolder({ node, depth, expanded, onToggle, ...rowProps }: RowActions & {
  node: DocNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
}) {
  const isOpen = expanded.has(node.path);
  const FolderIcon = isOpen ? FolderOpen : Folder;
  return (
    <div>
      <div
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 cursor-pointer text-sm hover:bg-muted"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onToggle(node.path)}
      >
        {isOpen ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <FolderIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="truncate">{node.name}</span>
      </div>
      {isOpen && (node.children ?? []).map((c) =>
        c.is_dir ? (
          <DocFolder key={c.path} node={c} depth={depth + 1} expanded={expanded} onToggle={onToggle} {...rowProps} />
        ) : (
          <div key={c.path} style={{ paddingLeft: `${(depth + 1) * 12}px` }}>
            <DocRow node={c} {...rowProps} />
          </div>
        )
      )}
    </div>
  );
}

export function DocumentsView() {
  const navigate = useNavigate();
  const [tree, setTree] = useState<DocNode[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [active, setActive] = useState("");
  const [detail, setDetail] = useState<DocDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [pinnedOpen, setPinnedOpen] = useState(true);
  const [pendingDelete, setPendingDelete] = useState<DocNode | null>(null);
  // 放大：隐藏列表区让正文占满宽度（侧边导航仍在，它是外层 layout 的一部分）。
  // 只影响阅读焦点，关闭预览或切换文档时保持，避免每次都要重新点。
  const [maximized, setMaximized] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchDocumentTree();
      setTree(data.tree);
      setTotal(data.total);
      // 首次加载自动展开一级目录，让用户直接看到内容而不是一排折叠项
      setExpanded((prev) => {
        if (prev.size) return prev;
        return new Set(data.tree.filter((n) => n.is_dir).map((n) => n.path));
      });
    } catch (e: any) {
      setError(e?.message ?? "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const toggleExpand = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(path) ? next.delete(path) : next.add(path);
      return next;
    });
  }, []);

  const openDoc = useCallback(async (node: DocNode) => {
    setActive(node.path);
    setDetailLoading(true);
    try {
      const d = await fetchDocument(node.path);
      setDetail(d);
    } catch (e: any) {
      setDetail({
        path: node.path, title: node.name, content: "",
        favorite: false, pinned: false, session_id: "", message_id: 0, size_kb: 0,
      });
      setError(e?.message ?? "读取失败");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // 元数据改动后局部刷新节点（不重新拉整棵树，避免树展开态被打回）
  const patchNode = useCallback((path: string, patch: Partial<DocNode>) => {
    const walk = (list: DocNode[]): DocNode[] =>
      list.map((n) =>
        n.path === path ? { ...n, ...patch }
          : n.is_dir ? { ...n, children: walk(n.children ?? []) } : n
      );
    setTree((prev) => walk(prev));
  }, []);

  const togglePin = useCallback(async (node: DocNode) => {
    const next = !node.pinned;
    patchNode(node.path, { pinned: next });
    try {
      await updateDocumentMeta(node.path, { pinned: next });
      if (detail?.path === node.path) setDetail({ ...detail, pinned: next });
    } catch { patchNode(node.path, { pinned: !next }); }
  }, [patchNode, detail]);

  const toggleFavorite = useCallback(async (node: DocNode) => {
    const next = !node.favorite;
    patchNode(node.path, { favorite: next });
    try {
      await updateDocumentMeta(node.path, { favorite: next });
      if (detail?.path === node.path) setDetail({ ...detail, favorite: next });
    } catch { patchNode(node.path, { favorite: !next }); }
  }, [patchNode, detail]);

  const locate = useCallback((node: DocNode) => {
    if (!node.session_id) return;
    // 跳到来源会话，带上消息锚点让对话页滚动定位（对话页读 msg 参数）
    const msg = node.message_id ? `?msg=${node.message_id}` : "";
    navigate(`/chat/${encodeURIComponent(node.session_id)}${msg}`);
  }, [navigate]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const node = pendingDelete;
    setPendingDelete(null);
    try {
      await deleteDocument(node.path);
      if (active === node.path) {
        setActive("");
        setDetail(null);
        setMaximized(false);  // 预览已关闭，放大态留着会是一片空白
      }
      void load();
    } catch (e: any) {
      setError(e?.message ?? "删除失败");
    }
  }, [pendingDelete, active, load]);

  const filtered = useMemo(() => filterTree(tree, query), [tree, query]);
  const pinnedList = useMemo(() => collectFlagged(filtered, "pinned"), [filtered]);
  const favoriteList = useMemo(() => collectFlagged(filtered, "favorite"), [filtered]);

  const rowProps: RowActions = {
    active,
    onOpen: (n) => void openDoc(n),
    onTogglePin: (n) => void togglePin(n),
    onToggleFavorite: (n) => void toggleFavorite(n),
    onLocate: locate,
    onDelete: (n) => setPendingDelete(n),
  };

  return (
    <div className="flex h-full min-h-0">
      {/* 左：列表区。放大阅读时整块隐藏，把宽度让给正文 */}
      <div className={`flex flex-col flex-1 min-w-0 border-r border-border ${maximized ? "hidden" : ""}`}>
        {/* 顶部：搜索 + 文件数 */}
        <div className="shrink-0 border-b border-border px-4 py-3 space-y-2">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium">文档</h2>
            <span className="text-xs text-muted-foreground">{total} 个文件</span>
            <Button variant="ghost" size="icon" className="h-7 w-7 ml-auto" onClick={() => void load()} title="刷新">
              <RefreshCw className="h-3.5 w-3.5" />
            </Button>
          </div>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索文档名…"
              className="h-8 pl-8 text-sm"
            />
          </div>
        </div>

        <ScrollArea className="flex-1 min-h-0">
          <div className="p-2">
            {/* 置顶区：可折叠 */}
            {pinnedList.length > 0 && (
              <div className="mb-3">
                <button
                  className="flex items-center gap-1.5 w-full px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                  onClick={() => setPinnedOpen((v) => !v)}
                >
                  {pinnedOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                  <Pin className="h-3.5 w-3.5" />
                  置顶 ({pinnedList.length})
                </button>
                {pinnedOpen && pinnedList.map((n) => (
                  <DocRow key={`pin-${n.path}`} node={n} {...rowProps} />
                ))}
              </div>
            )}

            {/* 收藏区（置顶之外） */}
            {favoriteList.length > 0 && (
              <div className="mb-3">
                <div className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium text-muted-foreground">
                  <Star className="h-3.5 w-3.5" />
                  收藏 ({favoriteList.length})
                </div>
                {favoriteList.map((n) => (
                  <DocRow key={`fav-${n.path}`} node={n} {...rowProps} />
                ))}
              </div>
            )}

            {/* 文件树 */}
            {loading ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中…
              </div>
            ) : error && !tree.length ? (
              <div className="px-3 py-8 text-center text-sm text-destructive">{error}</div>
            ) : !filtered.length ? (
              <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                {query ? "没有匹配的文档" : (
                  <>
                    <p>文档库还是空的</p>
                    <p className="mt-1 text-xs">对话里产出的文档会自动收在这里</p>
                  </>
                )}
              </div>
            ) : (
              filtered.map((n) =>
                n.is_dir ? (
                  <DocFolder key={n.path} node={n} depth={0} expanded={expanded} onToggle={toggleExpand} {...rowProps} />
                ) : (
                  <DocRow key={n.path} node={n} {...rowProps} />
                )
              )
            )}
          </div>
        </ScrollArea>
      </div>

      {/* 右：预览区（复用文件卡片同样的 markdown 渲染）。
          放大时占满整个宽度；正常态固定比例并与列表并排。 */}
      <div className={maximized
        ? "flex-1 min-w-0 flex flex-col min-h-0"
        : "w-[46%] min-w-[320px] flex flex-col min-h-0"}>
        {detailLoading ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载中…
          </div>
        ) : detail ? (
          <>
            <div className="shrink-0 flex items-center gap-2 border-b border-border px-4 py-3">
              {/* 放大态补一个返回按钮：列表区已隐藏，否则没法切回其它文档 */}
              {maximized && (
                <Button
                  variant="ghost" size="sm" className="shrink-0 text-xs"
                  onClick={() => setMaximized(false)}
                  title="返回列表"
                >
                  <Minimize2 className="h-3.5 w-3.5 mr-1" /> 返回
                </Button>
              )}
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">{detail.title}</div>
                <div className="text-xs text-muted-foreground truncate">{detail.path}</div>
              </div>
              {detail.session_id && (
                <Button
                  variant="ghost" size="sm" className="shrink-0 text-xs"
                  onClick={() => locate({
                    path: detail.path, name: detail.title, is_dir: false, mtime: 0,
                    session_id: detail.session_id, message_id: detail.message_id,
                  })}
                >
                  <MessageSquare className="h-3.5 w-3.5 mr-1" /> 来源对话
                </Button>
              )}
              <Button
                variant="ghost" size="icon" className="h-7 w-7 shrink-0"
                title={detail.favorite ? "取消收藏" : "收藏"}
                onClick={() => void toggleFavorite({
                  path: detail.path, name: detail.title, is_dir: false, mtime: 0,
                  favorite: detail.favorite, pinned: detail.pinned,
                })}
              >
                <Star className={`h-4 w-4 ${detail.favorite ? "fill-amber-500 text-amber-500" : ""}`} />
              </Button>
              <Button
                variant="ghost" size="icon" className="h-7 w-7 shrink-0"
                title={detail.pinned ? "取消置顶" : "置顶"}
                onClick={() => void togglePin({
                  path: detail.path, name: detail.title, is_dir: false, mtime: 0,
                  favorite: detail.favorite, pinned: detail.pinned,
                })}
              >
                <Pin className={`h-4 w-4 ${detail.pinned ? "text-primary" : ""}`} />
              </Button>
              <Button
                variant="ghost" size="icon" className="h-7 w-7 shrink-0"
                title={maximized ? "退出放大" : "放大阅读"}
                onClick={() => setMaximized((v) => !v)}
              >
                {maximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </Button>
            </div>
            <ScrollArea className="flex-1 min-h-0">
              <div className="p-6">
                <MarkdownBody content={detail.content} />
              </div>
            </ScrollArea>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            选择左侧文档查看内容
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!pendingDelete}
        title="删除文档"
        description={`确定删除「${pendingDelete?.name}」？此操作不可恢复。`}
        destructive
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

/** Markdown 正文渲染。延迟引入，避免文档页在未打开时也加载 markdown 依赖链。 */
function MarkdownBody({ content }: { content: string }) {
  const [Comp, setComp] = useState<null | React.ComponentType<{ content: string }>>(null);
  useEffect(() => {
    let alive = true;
    void import("@/components/chat/markdown").then((m) => {
      if (alive) setComp(() => m.MarkdownContent as React.ComponentType<{ content: string }>);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!Comp) return <pre className="whitespace-pre-wrap text-sm">{content}</pre>;
  return <Comp content={content} />;
}
