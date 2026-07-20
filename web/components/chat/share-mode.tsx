"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toPng } from "html-to-image";
import { Share2, Check, Copy, Loader2, X } from "lucide-react";
import { MarkdownContent } from "./markdown";
import type { Message } from "@ethan/shared/chat/types";

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function snippet(text: string, n = 80): string {
  const oneLine = text.replace(/\s+/g, " ").trim();
  return oneLine.length > n ? oneLine.slice(0, n) + "…" : oneLine;
}

function keyOf(m: Message, i: number): string {
  return m.id != null ? `id:${m.id}` : `idx:${i}`;
}

interface ShareModeProps {
  open: boolean;
  messages: Message[];
  defaultSelectedKey: string | null;
  onClose: () => void;
}

export function ShareMode({ open, messages, defaultSelectedKey, onClose }: ShareModeProps) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(defaultSelectedKey ? [defaultSelectedKey] : []),
  );
  const [includeMeta, setIncludeMeta] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [resultImage, setResultImage] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const selectedMessages = useMemo(
    () => messages.filter((m, i) => selected.has(keyOf(m, i))),
    [messages, selected],
  );

  if (!open) return null;

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const generate = async () => {
    if (!previewRef.current || generating) return;
    setGenerating(true);
    setCopied(false);
    try {
      if (document.fonts?.ready) await document.fonts.ready;
      const dataUrl = await toPng(previewRef.current, {
        pixelRatio: 2,
        cacheBust: true,
        backgroundColor: "#ffffff",
      });
      setResultImage(dataUrl);
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = `ethan-share-${Date.now()}.png`;
      a.click();
    } catch (err) {
      console.error("生成分享图片失败", err);
      alert("生成图片失败，请重试");
    } finally {
      setGenerating(false);
    }
  };

  const copyImage = async () => {
    if (!resultImage) return;
    try {
      const blob = await (await fetch(resultImage)).blob();
      if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }
    } catch {
      // 剪贴板不可用时忽略
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex h-[88vh] w-[92vw] max-w-4xl flex-col overflow-hidden rounded-xl border border-border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Share2 className="h-4 w-4" /> 分享对话
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              勾选要分享的消息，生成一张图片（可下载 / 复制到剪贴板）
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 主体：左选右预览 */}
        <div className="flex min-h-0 flex-1">
          {/* 左侧：消息勾选列表 */}
          <div className="w-1/3 shrink-0 overflow-y-auto border-r border-border p-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">
              本会话 {messages.length} 条消息
            </div>
            <div className="space-y-1.5">
              {messages.map((m, i) => {
                const k = keyOf(m, i);
                const checked = selected.has(k);
                return (
                  <label
                    key={k}
                    className={`flex cursor-pointer gap-2 rounded-lg border p-2 text-xs transition-colors ${
                      checked
                        ? "border-primary/50 bg-primary/5"
                        : "border-transparent hover:bg-accent/50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(k)}
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-primary"
                    />
                    <div className="min-w-0">
                      <div className="font-medium text-foreground/80">
                        {m.role === "user" ? "我" : "Ethan"}
                      </div>
                      <div className="truncate text-muted-foreground">{snippet(m.content)}</div>
                    </div>
                  </label>
                );
              })}
            </div>
          </div>

          {/* 右侧：预览卡片（即导出内容） */}
          <div className="flex min-w-0 flex-1 flex-col bg-muted/40">
            <div className="flex items-center justify-between border-b border-border bg-background/60 px-4 py-2">
              <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={includeMeta}
                  onChange={(e) => setIncludeMeta(e.target.checked)}
                  className="h-3.5 w-3.5 accent-primary"
                />
                显示角色与时间
              </label>
              <span className="text-xs text-muted-foreground">已选 {selectedMessages.length} 条</span>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {selectedMessages.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  请勾选至少一条消息
                </div>
              ) : (
                <div className="share-card mx-auto" ref={previewRef}>
                  <div className="share-card-inner">
                    <div className="share-head">
                      <span className="share-logo">Ethan</span>
                      <span className="share-sub">{selectedMessages.length} 条对话 · 由 Ethan 整理</span>
                    </div>
                    {selectedMessages.map((m, idx) => (
                      <div key={keyOf(m, idx)} className="share-msg">
                        <div className="share-msg-head">
                          <span className={`share-role ${m.role}`}>
                            {m.role === "user" ? "我" : "Ethan"}
                          </span>
                          {includeMeta && m.created_at && (
                            <span className="share-time">{formatTime(m.created_at)}</span>
                          )}
                        </div>
                        {m.role === "user" ? (
                          <div className="share-user-text whitespace-pre-wrap">
                            {m.content.replace(/^(\[Uploaded file: [^\]]+\]\n)+\n?/, "")}
                          </div>
                        ) : (
                          <MarkdownContent content={m.content} variant="share" />
                        )}
                        {idx < selectedMessages.length - 1 && <div className="share-divider" />}
                      </div>
                    ))}
                    <div className="share-foot">Ethan · 本地对话导出</div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 底部操作条 */}
        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <span className="text-xs text-muted-foreground">
            图片会直接下载；localhost 也能分享，因为导出的是图片而非链接。
          </span>
          <div className="flex items-center gap-2">
            {resultImage && (
              <button
                onClick={copyImage}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent"
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "已复制" : "复制图片"}
              </button>
            )}
            <button
              onClick={generate}
              disabled={generating || selectedMessages.length === 0}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              {generating && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {generating ? "生成中…" : "生成图片"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
