"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { toPng } from "html-to-image";
import { Share2, Check, Copy, Loader2, X, AlertCircle, Pencil, Eye } from "lucide-react";
import { MarkdownContent } from "./markdown";
import { fmtTokens } from "@/lib/utils";
import type { Message } from "@ethan/shared/chat/types";

function formatTime(ts?: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 毫秒 → 紧凑时长，与气泡底部统计行一致
function fmtDur(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;
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
  const [copyFailed, setCopyFailed] = useState(false);
  const [saveInfo, setSaveInfo] = useState<{ filename: string } | null>(null);
  const [editedContent, setEditedContent] = useState<Record<string, string>>({});
  const [editingKey, setEditingKey] = useState<string | null>(null);
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
    setSaveInfo(null);
    try {
      if (document.fonts?.ready) await document.fonts.ready;
      const dataUrl = await toPng(previewRef.current, {
        pixelRatio: 2,
        cacheBust: true,
        backgroundColor: "#ffffff",
      });
      setResultImage(dataUrl);
      const filename = `ethan-share-${Date.now()}.png`;
      const a = document.createElement("a");
      a.href = dataUrl;
      a.download = filename;
      a.click();
      setSaveInfo({ filename });
    } catch (err) {
      console.error("生成分享图片失败", err);
      alert("生成图片失败，请重试");
    } finally {
      setGenerating(false);
    }
  };

  const copyImage = async () => {
    if (!resultImage) return;
    setCopyFailed(false);
    try {
      const blob = await (await fetch(resultImage)).blob();
      if (typeof ClipboardItem !== "undefined" && navigator.clipboard?.write) {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
        return;
      }
    } catch {
      // 落到下方 fallback
    }
    // 剪贴板不可用或写入失败：提示用户
    setCopyFailed(true);
    setTimeout(() => setCopyFailed(false), 2500);
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
                    {selectedMessages.map((m, idx) => {
                      const k = keyOf(m, idx);
                      const raw = editedContent[k] ?? m.content;
                      const display = m.role === "user"
                        ? raw.replace(/^(\[Uploaded file: [^\]]+\]\n)+\n?/, "")
                        : raw;
                      const isEditing = editingKey === k;
                      return (
                      <div key={k} className="share-msg">
                        <div className="share-msg-head">
                          <span className={`share-role ${m.role}`}>
                            {m.role === "user" ? "我" : "Ethan"}
                          </span>
                          {includeMeta && m.created_at && (
                            <span className="share-time">{formatTime(m.created_at)}</span>
                          )}
                          <button
                            type="button"
                            className="share-edit-btn"
                            title={isEditing ? "完成编辑" : "编辑文字"}
                            onClick={() => setEditingKey(isEditing ? null : k)}
                          >
                            {isEditing ? <Eye className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
                          </button>
                        </div>
                        {isEditing ? (
                          <textarea
                            className="share-edit-textarea"
                            value={raw}
                            autoFocus
                            onChange={(e) =>
                              setEditedContent((prev) => ({ ...prev, [k]: e.target.value }))
                            }
                          />
                        ) : m.role === "user" ? (
                          <div className="share-user-text whitespace-pre-wrap">{display}</div>
                        ) : (
                          <MarkdownContent content={raw} variant="share" />
                        )}
                        {m.role === "assistant" && (m.usage || m.ttfb_ms != null || m.total_ms != null) && (
                          <div className="share-stats">
                            {m.usage && (
                              <span
                                className="share-stat share-stat-tokens"
                                title={`输入 ${m.usage.input.toLocaleString()} / 输出 ${m.usage.output.toLocaleString()}${m.usage.cache > 0 ? ` / 缓存 ${m.usage.cache.toLocaleString()}` : ""}`}
                              >
                                <span>↑{fmtTokens(m.usage.input)}</span>
                                <span>↓{fmtTokens(m.usage.output)}</span>
                                {m.usage.cache > 0 && <span>⚡{fmtTokens(m.usage.cache)}</span>}
                              </span>
                            )}
                            {m.ttfb_ms != null && (
                              <span className="share-stat share-stat-ttfb" title={`首字耗时 ${m.ttfb_ms}ms`}>
                                TTFB {m.ttfb_ms < 1000 ? `${m.ttfb_ms}ms` : `${(m.ttfb_ms / 1000).toFixed(1)}s`}
                              </span>
                            )}
                            {m.total_ms != null && (
                              <span className="share-stat share-stat-total" title={`总耗时 ${m.total_ms}ms`}>
                                总 {fmtDur(m.total_ms)}
                              </span>
                            )}
                            {m.ttfb_ms != null && m.total_ms != null && m.total_ms > m.ttfb_ms && (
                              <span className="share-stat share-stat-gen" title={`实际生成耗时 ${m.total_ms - m.ttfb_ms}ms`}>
                                生成 {fmtDur(m.total_ms - m.ttfb_ms)}
                              </span>
                            )}
                          </div>
                        )}
                        {idx < selectedMessages.length - 1 && <div className="share-divider" />}
                      </div>
                      );
                    })}
                    <div className="share-foot">
                      <span className="share-logo">Ethan</span>
                      <span className="share-sub">
                        {selectedMessages.length} 条对话 · 由 Ethan 整理
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 底部操作条 */}
        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <div className="min-w-0 flex-1 text-xs">
            {saveInfo ? (
              <div className="flex items-center gap-2">
                <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
                <span className="truncate text-muted-foreground">
                  图片已下载到浏览器默认下载目录（{saveInfo.filename}）
                </span>
              </div>
            ) : copyFailed ? (
              <div className="flex items-center gap-1.5 text-red-600">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                <span>
                  复制到剪贴板失败。浏览器可能限制了图片剪贴板权限，请使用「生成图片」直接下载。
                </span>
              </div>
            ) : (
              <span className="text-muted-foreground">
                生成后图片会下载到浏览器默认下载目录。
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {resultImage && (
              <button
                onClick={copyImage}
                className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm ${
                  copyFailed
                    ? "border-red-400 text-red-600"
                    : "border-border hover:bg-accent"
                }`}
              >
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "已复制" : copyFailed ? "复制失败" : "复制图片"}
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
