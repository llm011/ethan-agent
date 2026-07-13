"use client";

import { useEffect, useRef, useState } from "react";
import {
  X,
  Underline as UnderlineIcon,
  Bookmark as BookmarkIcon,
  MessageSquareText,
  Trash2,
} from "lucide-react";
import type { Message } from "./types";
import type { Annotation, AnnotationColor, AnnotationType } from "@/lib/api";
import { createAnnotation, deleteAnnotation } from "@/lib/api";
import { MarkdownContent } from "./markdown";
import { applyHighlights, getSelectionOffsets, type HighlightSpan } from "@/lib/highlight";

interface ReadingModeProps {
  open: boolean;
  message: Message | null;
  annotations: Annotation[];
  onClose: () => void;
  onChange: (next: Annotation[]) => void;
}

const HL_COLORS: { key: AnnotationColor; label: string; bg: string }[] = [
  { key: "yellow", label: "重点", bg: "oklch(0.95 0.13 105 / 0.7)" },
  { key: "blue", label: "疑问", bg: "oklch(0.92 0.10 230 / 0.6)" },
  { key: "green", label: "待办", bg: "oklch(0.94 0.12 150 / 0.6)" },
  { key: "pink", label: "反对", bg: "oklch(0.93 0.11 350 / 0.6)" },
];

function colorBg(c: AnnotationColor): string {
  switch (c) {
    case "yellow": return "oklch(0.95 0.13 105 / 0.8)";
    case "blue": return "oklch(0.92 0.10 230 / 0.7)";
    case "green": return "oklch(0.94 0.12 150 / 0.7)";
    case "pink": return "oklch(0.93 0.11 350 / 0.7)";
    default: return "var(--muted-foreground)";
  }
}

function typeLabel(t: AnnotationType): string {
  return (
    { highlight: "高亮", underline: "划线", strike: "删除线", comment: "批注", bookmark: "书签" } as Record<string, string>
  )[t] ?? t;
}

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function ReadingMode({ open, message, annotations, onClose, onChange }: ReadingModeProps) {
  const [local, setLocal] = useState<Annotation[]>(annotations);
  const [sel, setSel] = useState<{ start: number; end: number; text: string; top: number; left: number } | null>(null);
  const [noteMode, setNoteMode] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [activeId, setActiveId] = useState<number | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // 把标注画进正文（阅读模式用全强度）。
  // 注意：local 的初始值即打开时传入的 annotations；切换不同消息由父组件用
  // key={message.id} 触发整体重挂载，从而拿到新消息的标注重置，无需在 effect 里 setState。
  useEffect(() => {
    if (open && contentRef.current) {
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

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || !message) return null;

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
      // ignore
    }
    const next = local.filter((a) => a.id !== id);
    setLocal(next);
    onChange(next);
    if (activeId === id) setActiveId(null);
  };

  const jumpTo = (id: number) => {
    setActiveId(id);
    const el = contentRef.current?.querySelector(`mark[data-anno-id="${id}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.add("ring-2", "ring-primary");
    window.setTimeout(() => el?.classList.remove("ring-2", "ring-primary"), 1200);
  };

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-background">
      {/* 顶部条 */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2.5">
        <button
          onClick={onClose}
          className="flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted text-muted-foreground"
          title="退出阅读模式 (Esc)"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="text-sm font-medium">阅读模式</div>
        {message.created_at && (
          <div className="text-xs text-muted-foreground">{formatTime(message.created_at)}</div>
        )}
        <div className="ml-auto rounded-full bg-muted px-2.5 py-0.5 text-xs text-muted-foreground">
          {local.length} 处标注
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
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
          <div className="border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
            标注 ({local.length})
          </div>
          <div className="flex-1 space-y-1 overflow-y-auto p-2">
            {local.length === 0 && (
              <p className="px-2 py-4 text-xs text-muted-foreground">
                在正文中选中文字，即可高亮、划线或批注。
              </p>
            )}
            {local.map((a) => (
              <button
                key={a.id}
                onClick={() => jumpTo(a.id)}
                className={`w-full rounded-md p-2 text-left text-xs hover:bg-muted ${
                  activeId === a.id ? "bg-muted" : ""
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: colorBg(a.color) }}
                  />
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
      </div>

      {/* 选区工具条（fixed 定位到选区下方） */}
      {sel && (
        <div
          className="fixed z-[70] flex -translate-x-1/2 items-center gap-1 rounded-lg border border-border bg-popover p-1 shadow-lg"
          style={{ top: sel.top, left: sel.left }}
          onMouseDown={(e) => e.preventDefault()}
        >
          {!noteMode ? (
            <>
              {HL_COLORS.map((c) => (
                <button
                  key={c.key as string}
                  title={c.label}
                  onClick={() => doCreate("highlight", c.key)}
                  className="h-6 w-6 rounded"
                  style={{ background: c.bg }}
                />
              ))}
              <span className="mx-0.5 h-5 w-px bg-border" />
              <button
                title="划线"
                onClick={() => doCreate("underline")}
                className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
              >
                <UnderlineIcon className="h-4 w-4" />
              </button>
              <button
                title="书签"
                onClick={() => doCreate("bookmark")}
                className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
              >
                <BookmarkIcon className="h-4 w-4" />
              </button>
              <button
                title="批注"
                onClick={() => setNoteMode(true)}
                className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-muted"
              >
                <MessageSquareText className="h-4 w-4" />
              </button>
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
  );
}
