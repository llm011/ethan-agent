import { useEffect, useRef, useState } from "react";
import {
  X,
  Underline as UnderlineIcon,
  Bookmark as BookmarkIcon,
  MessageSquareText,
  Trash2,
  Pencil,
  Check,
  AlertCircle,
} from "lucide-react";
import type { Message } from "@ethan/shared/chat/types";
import type { Annotation, AnnotationColor, AnnotationType } from "@/lib/api";
import { createAnnotation, deleteAnnotation, updateAnnotationOffset, updateMessage } from "@/lib/api";
import { MarkdownContent } from "./markdown";
import { applyHighlights, getSelectionOffsets, type HighlightSpan } from "@/lib/highlight";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@ethan/shared/ui/tooltip";
import { annotationTypeLabel as typeLabel, annotationColorBg as colorBg } from "@ethan/shared/lib/reading";

interface ReadingModeProps {
  open: boolean;
  message: Message | null;
  annotations: Annotation[];
  /** 编辑保存需要：定位会话 */
  sessionId?: string;
  onClose: () => void;
  onChange: (next: Annotation[]) => void;
  /** 编辑保存成功后回写正文（父组件更新 messages state） */
  onEditContent?: (content: string) => void;
}

const HL_COLORS: { key: AnnotationColor; label: string; bg: string }[] = [
  { key: "yellow", label: "重点", bg: "oklch(0.95 0.13 105 / 0.7)" },
  { key: "blue", label: "疑问", bg: "oklch(0.92 0.10 230 / 0.6)" },
  { key: "green", label: "待办", bg: "oklch(0.94 0.12 150 / 0.6)" },
  { key: "pink", label: "反对", bg: "oklch(0.93 0.11 350 / 0.6)" },
];

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 正文编辑后按 quote 重定位 offset：
 * 1. 原位置仍是 quote（该处未被编辑影响）→ 保持不动；
 * 2. 重复文本歧义 → 在原位置前后就近取最近的匹配，而非从头 indexOf；
 * 3. 找不到（原文被删改）→ 返回 -1，调用方删除该标注。 */
function locateQuote(text: string, quote: string, prevStart: number): number {
  if (!quote) return -1;
  if (text.startsWith(quote, prevStart)) return prevStart;
  if (!text.includes(quote)) return -1;
  const fwd = text.indexOf(quote, prevStart);
  const bwd = prevStart > 0 ? text.lastIndexOf(quote, prevStart - 1) : -1;
  if (fwd < 0) return bwd;
  if (bwd < 0) return fwd;
  return fwd - prevStart <= prevStart - bwd ? fwd : bwd;
}

export function ReadingMode({ open, message, annotations, sessionId, onClose, onChange, onEditContent }: ReadingModeProps) {
  const [local, setLocal] = useState<Annotation[]>(annotations);
  const [sel, setSel] = useState<{ start: number; end: number; text: string; top: number; left: number } | null>(null);
  const [noteMode, setNoteMode] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [activeId, setActiveId] = useState<number | null>(null);
  const [filter, setFilter] = useState<"all" | "bookmark">("all");
  const contentRef = useRef<HTMLDivElement>(null);
  const [hoverNote, setHoverNote] = useState<{text: string; top: number; left: number} | null>(null);
  // 编辑态
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  // 保存/同步失败提示：静默吞错会导致「本地已更新、后端没保存」，
  // 重开会话后 offset/正文不一致，这里收集起来明确提示并支持重试
  const [saveError, setSaveError] = useState<string | null>(null);
  const [syncFails, setSyncFails] = useState<{ id: number; kind: "offset" | "delete"; start: number; end: number }[]>([]);
  const localRef = useRef(local);
  localRef.current = local;
  // 保存后待重定位标记：等 message.content 更新并重新渲染完成，再按 quote 重算标注 offset
  const pendingRelocateRef = useRef(false);
  const bookmarks = local.filter((a) => a.type === "bookmark");
  const shown = filter === "bookmark" ? bookmarks : local;

  // 把标注画进正文（阅读模式用全强度）。
  // 注意：local 的初始值即打开时传入的 annotations；切换不同消息由父组件用
  // key={message.id} 触发整体重挂载，从而拿到新消息的标注重置，无需在 effect 里 setState。
  // pendingRelocateRef 为 true（编辑已保存、待重定位）时跳过：避免用旧 offset 在
  // 新文本上画出错位高亮，等重定位完成后由 local 变化触发重画。
  useEffect(() => {
    if (open && contentRef.current && !pendingRelocateRef.current) {
      const spans: HighlightSpan[] = local.map((a) => ({
        id: a.id,
        type: a.type,
        color: a.color,
        start: a.start,
        end: a.end,
        note: a.note,
      }));
      applyHighlights(contentRef.current, spans, false);
    }
  }, [open, local, message?.content]);

  // 批注 hover tooltip：mark[data-note] 上悬浮即时展示
  useEffect(() => {
    const root = contentRef.current;
    if (!open || !root || editing) return;
    const onEnter = (e: Event) => {
      const mark = e.currentTarget as HTMLElement;
      const note = mark.dataset.note;
      if (!note) return;
      const rect = mark.getBoundingClientRect();
      setHoverNote({ text: note, top: rect.bottom + 6, left: rect.left + rect.width / 2 });
    };
    const onLeave = () => setHoverNote(null);
    const marks = root.querySelectorAll("mark[data-note]");
    marks.forEach((m) => {
      m.addEventListener("mouseenter", onEnter);
      m.addEventListener("mouseleave", onLeave);
    });
    return () => {
      marks.forEach((m) => {
        m.removeEventListener("mouseenter", onEnter);
        m.removeEventListener("mouseleave", onLeave);
      });
    };
  }, [open, local, message?.content, editing]);

  // 正文编辑保存后：等新内容渲染完成（下一帧），按 quote 在新纯文本中重新定位标注。
  // 原位置优先、就近匹配（防重复文本歧义）；定位不到的（原文被删改）删除；
  // 成功重定位的同步更新后端 offset。
  useEffect(() => {
    if (!pendingRelocateRef.current || editing) return;
    const raf = requestAnimationFrame(() => {
      pendingRelocateRef.current = false;
      const root = contentRef.current;
      if (!root) return;
      const text = root.textContent ?? "";
      const next: Annotation[] = [];
      for (const a of localRef.current) {
        const quote = a.quote ?? "";
        const idx = locateQuote(text, quote, a.start);
        if (idx < 0) {
          deleteAnnotation(a.id).catch(() => {
            setSyncFails((prev) => [...prev, { id: a.id, kind: "delete", start: 0, end: 0 }]);
          });
          continue;
        }
        if (idx !== a.start || idx + quote.length !== a.end) {
          updateAnnotationOffset(a.id, idx, idx + quote.length).catch(() => {
            setSyncFails((prev) => [...prev, { id: a.id, kind: "offset", start: idx, end: idx + quote.length }]);
          });
          next.push({ ...a, start: idx, end: idx + quote.length });
        } else {
          next.push(a);
        }
      }
      setLocal(next);
      onChange(next);
    });
    return () => cancelAnimationFrame(raf);
  }, [message?.content, editing]);

  // Esc：编辑态先退出编辑（防误触丢草稿），非编辑态关闭阅读模式
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (editing) {
          setEditing(false);
          setSel(null);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, editing]);

  if (!open || !message) return null;

  const startEdit = () => {
    setDraft(message?.content ?? "");
    setEditing(true);
    setSel(null);
    setActiveId(null);
  };

  const doSave = async () => {
    if (!message || message.id == null || saving) return;
    if (draft === message.content) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await updateMessage(sessionId ?? "", message.id, draft);
      onEditContent?.(draft);
      pendingRelocateRef.current = true;
      setEditing(false);
    } catch {
      // 保存失败停留在编辑态并明确提示，让用户重试或取消
      setSaveError("保存失败：正文未写入后端，重开会话会恢复旧内容，请重试。");
    } finally {
      setSaving(false);
    }
  };

  const handleMouseUp = () => {
    if (!contentRef.current) return;
    const off = getSelectionOffsets(contentRef.current);
    const selObj = window.getSelection();
    if (!off || off.end - off.start === 0 || !selObj || selObj.rangeCount === 0) {
      setSel(null);
      return;
    }
    const rect = selObj.getRangeAt(0).getBoundingClientRect();
    setSel({
      start: off.start,
      end: off.end,
      text: selObj.toString(),
      top: rect.bottom + 8,
      left: rect.left + rect.width / 2,
    });
    setNoteMode(false);
  };

  const handleClick = (e: React.MouseEvent) => {
    const mark = (e.target as HTMLElement).closest("mark[data-anno-id]");
    if (mark) {
      setActiveId(Number(mark.getAttribute("data-anno-id")));
    }
  };

  const doCreate = async (type: AnnotationType, color?: AnnotationColor, note?: string | null) => {
    if (!sel || message.id == null) return;
    const payload = {
      message_id: message.id,
      type,
      color: color ?? null,
      start: sel.start,
      end: sel.end,
      quote: sel.text,
      note: note ?? null,
    };
    try {
      const id = await createAnnotation(payload);
      const created: Annotation = {
        id,
        type,
        color: color ?? null,
        start: sel.start,
        end: sel.end,
        quote: sel.text,
        note: note ?? null,
        created_at: 0,
      };
      const next = [...local, created].sort((a, b) => a.start - b.start);
      setLocal(next);
      onChange(next);
    } catch {
      // 网络失败静默忽略，标注仅留本地预览
    }
    setSel(null);
    setNoteMode(false);
    setNoteText("");
  };

  const doDelete = async (id: number) => {
    try {
      await deleteAnnotation(id);
    } catch {
      // 本地已删除但后端失败：收集到同步失败提示，供重试（重开会话会“复活”该标注）
      setSyncFails((prev) => [...prev, { id, kind: "delete", start: 0, end: 0 }]);
    }
    const next = local.filter((a) => a.id !== id);
    setLocal(next);
    onChange(next);
    if (activeId === id) setActiveId(null);
  };

  // 重试同步失败的标注操作（重定位 offset / 删除）
  const retrySync = async () => {
    const fails = syncFails;
    setSyncFails([]);
    const remaining: typeof fails = [];
    for (const f of fails) {
      try {
        if (f.kind === "delete") await deleteAnnotation(f.id);
        else await updateAnnotationOffset(f.id, f.start, f.end);
      } catch {
        remaining.push(f);
      }
    }
    if (remaining.length > 0) setSyncFails(remaining);
  };

  const jumpTo = (id: number) => {
    setActiveId(id);
    const el = contentRef.current?.querySelector(`mark[data-anno-id="${id}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.add("ring-2", "ring-primary");
    window.setTimeout(() => el?.classList.remove("ring-2", "ring-primary"), 1200);
  };

  return (
    <TooltipProvider delay={0}>
    <div className="fixed inset-0 z-[60] flex flex-col bg-background">
      {/* 顶部条 */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2.5">
        <Tooltip>
          <TooltipTrigger
            render={
              <button
                onClick={onClose}
                className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted text-muted-foreground"
              />
            }
          >
            <X className="h-4 w-4" />
          </TooltipTrigger>
          <TooltipContent side="bottom">退出阅读模式 (Esc)</TooltipContent>
        </Tooltip>
        <div className="text-sm font-medium">阅读模式</div>
        {message.created_at && !editing && (
          <div className="text-xs text-muted-foreground">{formatTime(message.created_at)}</div>
        )}
        {editing ? (
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">编辑正文（Markdown），保存后已有标注按原文自动重定位</span>
            {saveError && <span className="text-xs text-destructive">{saveError}</span>}
            <button
              onClick={() => { setEditing(false); setSel(null); setSaveError(null); }}
              disabled={saving}
              className="rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted disabled:opacity-40"
            >
              取消
            </button>
            <button
              onClick={doSave}
              disabled={saving}
              className="flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              <Check className="h-3 w-3" /> {saving ? "保存中…" : "保存"}
            </button>
          </div>
        ) : (
          <>
            <div className="ml-auto flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">
              <span>{local.length} 处标注</span>
              {bookmarks.length > 0 && (
                <>
                  <span className="inline-block h-3 w-px bg-muted-foreground/30" />
                  <BookmarkIcon className="h-3 w-3 text-pink-500" />
                  <span>{bookmarks.length}</span>
                </>
              )}
            </div>
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    onClick={startEdit}
                    className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                  />
                }
              >
                <Pencil className="h-4 w-4" />
              </TooltipTrigger>
              <TooltipContent side="bottom">编辑正文</TooltipContent>
            </Tooltip>
          </>
        )}
      </div>

      {/* 标注同步失败提示：本地已生效但后端未保存，不提示会在重开后表现为错位/复活 */}
      {syncFails.length > 0 && (
        <div className="flex items-center gap-2 border-b border-border bg-destructive/10 px-4 py-1.5 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">{syncFails.length} 处标注同步失败，重开会话后可能错位。</span>
          <button
            onClick={retrySync}
            className="rounded-md border border-destructive/40 px-2 py-0.5 hover:bg-destructive/20"
          >
            重试
          </button>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {editing ? (
          /* 编辑态：与正文同布局的 textarea */
          <div className="flex-1 overflow-y-auto px-4 py-10">
            <textarea
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) doSave();
              }}
              spellCheck={false}
              className="mx-auto block h-full min-h-[60vh] w-full max-w-[720px] resize-none rounded-md border border-border bg-background p-4 text-sm leading-7 outline-none focus-visible:ring-1 focus-visible:ring-ring"
              placeholder="编辑正文内容（Markdown）…"
            />
          </div>
        ) : (
        <>
        {/* 正文（可滚动、居中、舒适行宽） */}
        <div
          className="flex-1 overflow-y-auto px-4 py-10"
          onMouseUp={handleMouseUp}
          onClick={handleClick}
        >
          <div className="mx-auto max-w-[720px]">
            <MarkdownContent
              ref={contentRef}
              content={message.content || ""}
              className="prose reading-prose max-w-none"
            />
          </div>
        </div>

        {/* 右侧标注面板（md 及以上） */}
        <aside className="hidden w-72 shrink-0 flex-col border-l border-border md:flex">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-medium text-muted-foreground">标注 ({local.length})</span>
            {bookmarks.length > 0 && (
              <div className="flex items-center gap-0.5 text-[11px]">
                <button
                  onClick={() => setFilter("all")}
                  className={`rounded px-1.5 py-0.5 ${filter === "all" ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60"}`}
                >全部</button>
                <button
                  onClick={() => setFilter("bookmark")}
                  className={`flex items-center gap-0.5 rounded px-1.5 py-0.5 ${filter === "bookmark" ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60"}`}
                ><BookmarkIcon className="h-3 w-3 text-pink-500" />书签</button>
              </div>
            )}
          </div>
          <div className="flex-1 space-y-1 overflow-y-auto p-2">
            {local.length === 0 && (
              <p className="px-2 py-4 text-xs text-muted-foreground">
                在正文中选中文字，即可高亮、划线或批注。
              </p>
            )}
            {shown.length === 0 && local.length > 0 && filter === "bookmark" && (
              <p className="px-2 py-4 text-xs text-muted-foreground">还没有书签，选中文字后点工具条上的 🔖 即可添加。</p>
            )}
            {shown.map((a) => (
              <button
                key={a.id}
                onClick={() => jumpTo(a.id)}
                className={`w-full rounded-md p-2 text-left text-xs hover:bg-muted ${
                  activeId === a.id ? "bg-muted" : ""
                }`}
              >
                <div className="flex items-center gap-1.5">
                  {a.type === "bookmark" ? (
                    <BookmarkIcon className="h-3 w-3 shrink-0 text-pink-500" />
                  ) : (
                    <span
                      className="h-2.5 w-2.5 rounded-full shrink-0"
                      style={{ background: colorBg(a.color) }}
                    />
                  )}
                  <span className="text-muted-foreground">{typeLabel(a.type)}</span>
                </div>
                <p className="mt-1 line-clamp-2 text-foreground/80">{a.quote}</p>
                {a.note && (
                  <p className="mt-1 border-l-2 border-border pl-1.5 text-[11px] text-muted-foreground">
                    {a.note}
                  </p>
                )}
              </button>
            ))}
          </div>
          {local.length > 0 && (
            <div className="border-t border-border p-2">
              <button
                onClick={() => activeId != null && doDelete(activeId)}
                disabled={activeId == null}
                className="flex w-full items-center justify-center gap-1.5 rounded-md border border-border py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-40"
              >
                <Trash2 className="h-3.5 w-3.5" /> 删除所选标注
              </button>
            </div>
          )}
        </aside>
        </>
        )}
      </div>

      {/* 选区工具条（fixed 定位到选区下方） */}
      {sel && !editing && (
        <div
          className="fixed z-[70] flex -translate-x-1/2 items-center gap-1 rounded-lg border border-border bg-popover p-1 shadow-lg"
          style={{ top: sel.top, left: sel.left }}
          onMouseDown={(e) => e.preventDefault()}
        >
          {!noteMode ? (
            <>
              {HL_COLORS.map((c) => (
                <Tooltip key={c.key as string}>
                  <TooltipTrigger
                    render={
                      <button
                        onClick={() => doCreate("highlight", c.key)}
                        className="h-6 w-6 rounded"
                        style={{ background: c.bg }}
                      />
                    }
                  />
                  <TooltipContent side="top">{c.label}</TooltipContent>
                </Tooltip>
              ))}
              <span className="mx-0.5 h-5 w-px bg-border" />
              <Tooltip>
                <TooltipTrigger
                  render={
                    <button
                      onClick={() => doCreate("underline")}
                      className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
                    />
                  }
                >
                  <UnderlineIcon className="h-3.5 w-3.5" />
                </TooltipTrigger>
                <TooltipContent side="top">划线</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <button
                      onClick={() => doCreate("bookmark")}
                      className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
                    />
                  }
                >
                  <BookmarkIcon className="h-3.5 w-3.5" />
                </TooltipTrigger>
                <TooltipContent side="top">书签（右侧面板「书签」里可查找）</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <button
                      onClick={() => setNoteMode(true)}
                      className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
                    />
                  }
                >
                  <MessageSquareText className="h-3.5 w-3.5" />
                </TooltipTrigger>
                <TooltipContent side="top">批注</TooltipContent>
              </Tooltip>
            </>
          ) : (
            <div className="flex items-center gap-1">
              <input
                autoFocus
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") doCreate("comment", "yellow", noteText);
                }}
                placeholder="写点批注…"
                className="w-40 rounded border border-border bg-background px-2 py-1 text-xs outline-none"
              />
              <button
                onClick={() => doCreate("comment", "yellow", noteText)}
                className="rounded bg-primary px-2 py-1 text-xs text-primary-foreground"
              >
                保存
              </button>
              <button
                onClick={() => {
                  setNoteMode(false);
                  setNoteText("");
                }}
                className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
              >
                取消
              </button>
            </div>
          )}
        </div>
      )}
    </div>
      {/* 批注悬浮提示 */}
      {hoverNote && (
        <div
          className="fixed z-[80] max-w-xs -translate-x-1/2 rounded-md bg-foreground px-3 py-1.5 text-xs text-background shadow-lg"
          style={{ top: hoverNote.top, left: hoverNote.left }}
        >
          {hoverNote.text}
        </div>
      )}
    </TooltipProvider>
  );
}
