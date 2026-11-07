"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  X,
  Underline as UnderlineIcon,
  Bookmark as BookmarkIcon,
  MessageSquareText,
  Trash2,
  Pencil,
  Check,
  AlertCircle,
  Copy,
  Volume2,
  Pause,
  Play,
  Square,
} from "lucide-react";
import type { CardData, Message } from "@ethan/shared/chat/types";
import type { Annotation, AnnotationColor, AnnotationType } from "@/lib/api";
import { createAnnotation, deleteAnnotation, updateAnnotationOffset, updateMessage, fetchTtsStatus } from "@/lib/api";
import { isPersistedId } from "@ethan/shared/chat/history";
import { MarkdownContent } from "./markdown";
import { A2uiCard } from "./a2ui-card";
import { McpAppView } from "./mcp-app-view";
import { ImageGallery, type ImageCard } from "./image-gallery";
import { FileCardView, type FileCard } from "./file-card";
import { applyHighlights, getSelectionOffsets, getSelectionRawText, getSelectionText, type HighlightSpan } from "@/lib/highlight";
import { useSpeaking } from "@/hooks/use-speaking";
import { copyToClipboard } from "@ethan/shared/lib/clipboard";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@ethan/shared/ui/tooltip";

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

// 阅读模式的卡片区：A2UI 卡片（表格/时间轴等）、图片/文件卡片、MCP 应用。
// 这些结构化字段不在 message.content（Markdown 正文）里，所以必须单独渲染，
// 且放在 contentRef（可标注正文）之外——否则会打乱按文本 offset 定位的标注。
function ReadingCards({ message, sessionId }: { message: Message; sessionId?: string }) {
  const cards = (message.cards ?? []) as CardData[];
  const images = cards.filter((c): c is ImageCard => c.type === "image");
  const files = cards.filter((c): c is FileCard => c.type === "file");
  const a2ui = message.a2ui ?? [];
  const mcpApps = message.mcpApps ?? [];
  if (images.length === 0 && files.length === 0 && a2ui.length === 0 && mcpApps.length === 0) {
    return null;
  }
  return (
    <div className="mt-6 space-y-3 select-text">
      {images.length > 0 && <ImageGallery cards={images} />}
      {files.map((f, i) => (
        <FileCardView key={`${f.path}-${i}`} card={f} sessionId={sessionId} />
      ))}
      {a2ui.length > 0 && <A2uiCard surfaces={a2ui} />}
      {mcpApps.length > 0 && <McpAppView apps={mcpApps} />}
    </div>
  );
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
  // 选中复制：copied 短暂显示「已复制」，copyFailed 明确提示失败（不静默）
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  // 复制反馈 / 失败提示的定时器与工具条闪烁定时器，卸载时统一清掉
  const copiedTimer = useRef<number | null>(null);
  const localRef = useRef(local);
  localRef.current = local;
  // 保存后待重定位标记：等 message.content 更新并重新渲染完成，再按 quote 重算标注 offset
  const pendingRelocateRef = useRef(false);
  const bookmarks = local.filter((a) => a.type === "bookmark");
  // ---- 朗读 ----
  const speaking = useSpeaking();
  const [ttsReady, setTtsReady] = useState<boolean | null>(null);
  // 朗读正文：有选中就读选中，否则读全篇
  const buildSpeakText = useCallback(() => {
    const selected = contentRef.current ? getSelectionText(contentRef.current).trim() : "";
    if (selected) return selected;
    return (message?.content || "").trim();
  }, [message?.content]);
  const onToggleSpeak = useCallback(() => {
    if (speaking.state === "playing") { speaking.pause(); return; }
    if (speaking.state === "paused") { speaking.resume(); return; }
    const text = buildSpeakText();
    if (text) void speaking.start(text);
  }, [speaking, buildSpeakText]);
  // 退出阅读模式 / 切换到别的消息时必须停播，否则会一直在后台念
  useEffect(() => {
    if (!open) speaking.stop();
    return () => speaking.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, message?.id]);
  // 探测本机语音后端（只查状态，不拉起）；没装就在按钮上标出来
  useEffect(() => {
    let alive = true;
    fetchTtsStatus()
      .then((s) => { if (alive) setTtsReady(s.installed); })
      .catch(() => { if (alive) setTtsReady(false); });
    return () => { alive = false; };
  }, []);
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

  // 卸载时清掉「已复制」的定时器，避免关闭阅读模式后对已卸载组件 setState
  useEffect(() => {
    return () => {
      if (copiedTimer.current != null) window.clearTimeout(copiedTimer.current);
    };
  }, []);

  // 复制当前选中的正文。走共享的 copyToClipboard（Clipboard API + execCommand 回退），
  // 失败时明确提示而不是静默——否则用户以为复制成功了。
  // useCallback 让快捷键 effect 能安全依赖它，而不必每次渲染重绑监听。
  const doCopy = useCallback(async () => {
    if (!contentRef.current) return;
    const text = getSelectionText(contentRef.current) || sel?.text || "";
    if (!text) return;
    const ok = await copyToClipboard(text);
    setCopied(ok);
    setCopyFailed(!ok);
    if (copiedTimer.current != null) window.clearTimeout(copiedTimer.current);
    if (ok) {
      copiedTimer.current = window.setTimeout(() => setCopied(false), 1600);
    }
  }, [sel?.text]);

  // Esc：编辑态先退出编辑（防误触丢草稿），非编辑态关闭阅读模式
  // Cmd/Ctrl+C：焦点在正文里时复制选中正文（走同一套回退逻辑，http 局域网也能用）
  // Cmd/Ctrl+A：只全选正文，避免把左右面板/按钮一起选进来
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
        return;
      }
      if (editing || !(e.metaKey || e.ctrlKey)) return;
      // 焦点在输入类元素（批注输入框等）上时放行浏览器默认行为：
      // ⌘A 应全选输入框自己的文字，⌘C 应复制输入框里选中的内容
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (e.key === "c" || e.key === "C") {
        // 没有正文选区时放行走浏览器默认行为，别吞掉用户自己在别处的复制
        if (getSelectionRawText(contentRef.current!).trim()) {
          e.preventDefault();
          void doCopy();
        }
      } else if (e.key === "a" || e.key === "A") {
        const root = contentRef.current;
        if (!root) return;
        const range = document.createRange();
        range.selectNodeContents(root);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, editing, doCopy]);

  const startEdit = () => {
    setDraft(message?.content ?? "");
    setEditing(true);
    setSel(null);
    setActiveId(null);
  };

  const doSave = async () => {
    // 编辑是写操作，必须有落库后的数字 id
    if (!message || !isPersistedId(message.id) || saving) return;
    const messageId = message.id;
    if (draft === message.content) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await updateMessage(sessionId ?? "", messageId, draft);
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
      // quote/offset 用 raw textContent 口径（locateQuote 重定位时在 root.textContent
      // 里 includes，带补充换行的版本匹配不上）；复制的可读版由 doCopy 实时取 getSelectionText
      text: getSelectionRawText(contentRef.current),
      top: rect.bottom + 8,
      left: rect.left + rect.width / 2,
    });
    setNoteMode(false);
    // 新选区出现时清掉上一轮的复制反馈
    setCopied(false);
    setCopyFailed(false);
  };

  const handleClick = (e: React.MouseEvent) => {
    const mark = (e.target as HTMLElement).closest("mark[data-anno-id]");
    if (mark) {
      setActiveId(Number(mark.getAttribute("data-anno-id")));
    }
  };

  const doCreate = async (type: AnnotationType, color?: AnnotationColor, note?: string | null) => {
    // 标注按 message_id 持久化，同样要求真实 id
    if (!sel || !isPersistedId(message.id)) return;
    const messageId = message.id;
    const payload = {
      message_id: messageId,
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
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    onClick={onToggleSpeak}
                    disabled={ttsReady === false || speaking.state === "connecting"}
                    aria-label={speaking.state === "playing" ? "暂停朗读" : "朗读"}
                    className={`flex h-8 w-8 items-center justify-center rounded-md hover:bg-muted disabled:opacity-40 ${
                      speaking.state === "playing" ? "text-primary" : "text-muted-foreground"
                    }`}
                  />
                }
              >
                {speaking.state === "connecting" ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-muted-foreground/40 border-t-transparent" />
                ) : speaking.state === "playing" ? (
                  <Pause className="h-4 w-4" />
                ) : speaking.state === "paused" ? (
                  <Play className="h-4 w-4" />
                ) : (
                  <Volume2 className="h-4 w-4" />
                )}
              </TooltipTrigger>
              <TooltipContent side="bottom">
                {ttsReady === false
                  ? "本机未安装 ethan-tts，无法朗读"
                  : speaking.state === "playing"
                    ? "暂停朗读"
                    : "朗读（有选中读选中，否则读全篇）"}
              </TooltipContent>
            </Tooltip>
            {speaking.state !== "idle" && (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <button
                      onClick={speaking.stop}
                      className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                    />
                  }
                >
                  <Square className="h-4 w-4" />
                </TooltipTrigger>
                <TooltipContent side="bottom">停止朗读</TooltipContent>
              </Tooltip>
            )}
          </>
        )}
      </div>

      {/* 朗读状态条：冷启动要拉起服务并加载模型（实测 6–10 秒），
          不给反馈用户会以为按钮没反应 */}
      {(speaking.warmingUp || speaking.state !== "idle" || speaking.error) && (
        <div
          className={`flex items-center gap-2 border-b px-4 py-1.5 text-xs ${
            speaking.error
              ? "border-destructive/30 bg-destructive/10 text-destructive"
              : "border-border bg-muted/50 text-muted-foreground"
          }`}
        >
          {speaking.error ? (
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <Volume2 className={`h-3.5 w-3.5 shrink-0 ${speaking.state === "playing" ? "text-primary" : ""}`} />
          )}
          <span className="flex-1">
            {speaking.error
              ? speaking.error
              : speaking.warmingUp
                ? "正在启动本地语音，首次使用需要加载模型，请稍候…"
                : speaking.state === "paused"
                  ? "已暂停"
                  : "朗读中"}
          </span>
          {(speaking.state !== "idle" || speaking.error) && (
            <button
              onClick={speaking.stop}
              className="rounded-md border border-current/30 px-2 py-0.5 hover:bg-current/10"
            >
              停止
            </button>
          )}
        </div>
      )}

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

      {/* 复制失败提示：Clipboard API 与 execCommand 都不可用时明确告知，避免用户以为已复制 */}
      {copyFailed && (
        <div className="flex items-center gap-2 border-b border-border bg-destructive/10 px-4 py-1.5 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">复制失败：浏览器拒绝了剪贴板访问，请手动选中后复制。</span>
          <button
            onClick={() => setCopyFailed(false)}
            className="rounded-md border border-destructive/40 px-2 py-0.5 hover:bg-destructive/20"
          >
            知道了
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
        {/* 正文（可滚动、居中、舒适行宽）。显式 select-text：外层若被任何
            `select-none`（如 Tauri 拖拽区、卡片类样式）命中，正文也要可选中复制 */}
        <div
          className="flex-1 select-text overflow-y-auto px-4 py-10"
          onMouseUp={handleMouseUp}
          onClick={handleClick}
        >
          <div className="mx-auto max-w-[720px]">
            <MarkdownContent
              ref={contentRef}
              content={message.content || ""}
              className="prose reading-prose max-w-none"
              speakSentence={speaking.currentSentence}
            />
            <ReadingCards message={message} sessionId={sessionId} />
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
              <Tooltip>
                <TooltipTrigger
                  render={
                    <button
                      onClick={doCopy}
                      // 复制是纯读操作，不依赖后端落库，任何消息（含未持久化的）都能复制
                      aria-label="复制选中文字"
                      className={`flex h-7 items-center gap-1 rounded px-2 text-xs ${
                        copyFailed
                          ? "text-destructive"
                          : copied
                            ? "bg-primary/10 text-primary"
                            : "text-muted-foreground hover:bg-muted"
                      }`}
                    >
                      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                      {copied ? "已复制" : copyFailed ? "复制失败" : "复制"}
                    </button>
                  }
                />
                <TooltipContent side="top">复制选中文字（⌘/Ctrl + C）</TooltipContent>
              </Tooltip>
              <span className="mx-0.5 h-5 w-px bg-border" />
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
