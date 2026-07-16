"use client";

import { useState, useEffect, useRef } from "react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Quote as QuoteIcon, Zap, Flag, Activity, BookOpen as BookOpenIcon, Share2 as ShareIcon } from "lucide-react";
import { ToolTimeline } from "@/components/tool-timeline";
import { SwimlaneDiagram } from "@/components/swimlane-diagram";
import { fmtTokens } from "@/lib/utils";
import { A2uiCard } from "./a2ui-card";
import { MarkdownContent } from "./markdown";
import { applyHighlights } from "@/lib/highlight";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import type { Message } from "./types";
import type { Annotation } from "@/lib/api";

function formatTime(ts?: number) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const yyyy = d.getFullYear();
  const MM = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const HH = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${MM}-${dd} ${HH}:${mm}`;
}

// 毫秒 → 紧凑时长：999ms 以下显示 ms，1 分钟内显示 1 位小数秒，超过则 XmYs
function fmtDur(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;
}

// CommonMark 规定 ** 紧内侧不能有空格，否则不渲染加粗。
// 此函数去掉 AI 生成文本中 ** 内侧的多余空白，修复渲染。
function fixBold(text: string): string {
  return text.replace(/\*\*[ \t]*((?:[^*\n]|\*(?!\*))+?)[ \t]*\*\*/g, (_, inner) => {
    const trimmed = inner.trim();
    return trimmed ? `**${trimmed}**` : `**${inner}**`;
  });
}


interface MessageBubbleProps {
  msg: Message;
  isStreaming: boolean;
  isLast: boolean;
  onQuote?: (msg: Message) => void;
  onCardAction?: (text: string) => void;
  onRead?: (msg: Message) => void;
  onShare?: (msg: Message) => void;
  annotations?: Annotation[];
}

export function MessageBubble({ msg, isStreaming, isLast, onQuote, onCardAction, onRead, onShare, annotations }: MessageBubbleProps) {
  const [highlightedStep, setHighlightedStep] = useState<number | undefined>(undefined);
  // 过程记录默认展开（流式结束后仍可见），用户可手动折叠
  const [intermediateOpen, setIntermediateOpen] = useState(true);
  const contentRef = useRef<HTMLDivElement>(null);

  // 把已保存的标注以「淡显」方式画回气泡正文（阅读模式是完整强度）。
  useEffect(() => {
    if (msg.role !== "assistant" || !contentRef.current) return;
    const spans = !isStreaming && annotations && annotations.length > 0
      ? annotations.map((a) => ({ id: a.id, type: a.type, color: a.color, start: a.start, end: a.end, note: a.note }))
      : [];
    applyHighlights(contentRef.current, spans, true);
  }, [annotations, msg.content, isStreaming, msg.role]);

  return (
    <TooltipProvider delay={0}>
    <div className={`group flex ${msg.role === "user" ? "justify-end" : "justify-start"} gap-2`}>
      {msg.role === "assistant" && (
        <div className="flex-shrink-0 mt-1">
          <Image src={`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/logo-avatar.png`} alt="Ethan" width={28} height={28} className="rounded-full" />
        </div>
      )}
      <div className="relative max-w-[90%] md:max-w-[80%]">
        {/* 悬浮引用按钮 */}
        {onQuote && !isStreaming && (
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  onClick={() => onQuote(msg)}
                  className={`absolute -top-2 ${msg.role === "user" ? "-left-7" : "-right-7"} opacity-0 group-hover:opacity-100 transition-opacity h-6 w-6 flex items-center justify-center rounded-md bg-muted border border-border text-muted-foreground hover:text-foreground hover:bg-accent`}
                />
              }
            />
            <TooltipContent side={msg.role === "user" ? "left" : "right"}>引用此消息</TooltipContent>
          </Tooltip>
        )}
        {/* 悬浮阅读按钮（仅 assistant 且已有稳定 id） */}
        {msg.role === "assistant" && onRead && !isStreaming && msg.id != null && (
          <Tooltip>
            <TooltipTrigger
              render={
                <button
                  onClick={() => onRead(msg)}
                  className="absolute -top-2 -right-14 opacity-0 group-hover:opacity-100 transition-opacity h-6 w-6 flex items-center justify-center rounded-md bg-muted border border-border text-muted-foreground hover:text-foreground hover:bg-accent"
                />
              }
            />
            <TooltipContent side="right">阅读模式（可标注 / 划线 / 批注）</TooltipContent>
          </Tooltip>
        )}
        <div
          className={`rounded-2xl px-4 py-3 break-words ${
            msg.role === "user"
              ? "bg-primary text-primary-foreground"
              : "bg-muted prose prose-sm dark:prose-invert max-w-none"
          }`}
        >
          {msg.role === "user" ? (
            <>
              {msg.quote && (
                <div className="mb-1.5 pl-2 border-l-2 border-primary-foreground/40 text-xs opacity-80">
                  <div className="font-medium opacity-70">
                    {msg.quote.role === "user" ? "引用 我" : "引用 Ethan"}
                  </div>
                  <p className="truncate opacity-70">{msg.quote.content.replace(/\n/g, " ")}</p>
                </div>
              )}
              {msg.files && msg.files.length > 0 && (
                <div className="text-xs opacity-70 mb-1">
                  {msg.files.map((f, j) => <span key={j} className="mr-2">📎 {f}</span>)}
                </div>
              )}
              {msg.images && msg.images.length > 0 && (
                <div className="flex gap-1.5 flex-wrap mb-1.5">
                  {msg.images.map((img, j) => (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      key={j}
                      src={img.dataUrl}
                      alt=""
                      className="max-h-48 max-w-xs rounded-lg object-contain border border-primary-foreground/20"
                    />
                  ))}
                </div>
              )}
              <p className="whitespace-pre-wrap">{msg.content.replace(/^(\[Uploaded file: [^\]]+\]\n)+\n?/, '')}</p>
              {msg.created_at && (
                <div className="text-[10px] opacity-40 mt-1 text-right">
                  {formatTime(msg.created_at)}
                </div>
              )}
            </>
          ) : (
          <>
            {msg.thought && (
              <details className="mb-2 border border-border/50 bg-background/50 rounded-lg overflow-hidden group" open={intermediateOpen}>
                <summary className="px-3 py-1.5 text-xs text-muted-foreground font-medium cursor-pointer hover:bg-background/80 flex items-center transition-colors list-none select-none">
                  <span className="opacity-70 group-open:opacity-100 transition-opacity">🤔 思考过程</span>
                </summary>
                <div className="px-3 py-2 text-xs text-muted-foreground opacity-80 border-t border-border/50 bg-background/30 whitespace-pre-wrap leading-relaxed">
                  {msg.thought}
                </div>
              </details>
            )}
            {msg.intermediateOutput && (
              isStreaming && isLast ? (
                <div className="mb-2 rounded-lg border border-border/50 bg-background/30 px-3 py-2 text-sm text-muted-foreground/80 leading-relaxed">
                  <div className="text-xs font-medium text-muted-foreground mb-1.5">📝 过程记录</div>
                  <MarkdownContent content={msg.intermediateOutput} />
                </div>
              ) : (
                <details
                  className="mb-2 border border-border/50 bg-background/50 rounded-lg overflow-hidden group"
                  open={intermediateOpen}
                  onToggle={(e) => setIntermediateOpen(e.currentTarget.open)}
                >
                  <summary className="px-3 py-1.5 text-xs text-muted-foreground font-medium cursor-pointer hover:bg-background/80 flex items-center transition-colors list-none select-none">
                    <span className="opacity-70 group-open:opacity-100 transition-opacity">📝 过程记录</span>
                  </summary>
                  <div className="px-3 py-2 text-sm text-muted-foreground/80 border-t border-border/50 bg-background/30 leading-relaxed">
                    <MarkdownContent content={msg.intermediateOutput} />
                  </div>
                </details>
              )
            )}
            {msg.toolSteps && msg.toolSteps.length > 0 && (
              <ToolTimeline steps={msg.toolSteps} defaultExpanded={msg.toolsExpanded ?? false} highlightIndex={highlightedStep} />
            )}
            {msg.toolSteps && msg.toolSteps.length > 0 && msg.toolSteps.some(s => s.entity_type) && (
              <SwimlaneDiagram steps={msg.toolSteps} matchedSkills={msg.matchedSkills} onStepClick={setHighlightedStep} />
            )}
            <MarkdownContent ref={contentRef} content={msg.content} />
            {msg.a2ui && msg.a2ui.length > 0 && (
              <A2uiCard surfaces={msg.a2ui} onAction={onCardAction} />
            )}
            <div className="flex justify-end items-center mt-2 gap-1.5 text-[10px] text-muted-foreground/35 tabular-nums">
              {msg.created_at && <span>{formatTime(msg.created_at)}</span>}
              {msg.created_at && (msg.usage || msg.ttfb_ms != null || msg.total_ms != null) && <span className="inline-block w-px h-2.5 bg-muted-foreground/20" />}
              {msg.usage && (
                <span title={`${msg.usage.input.toLocaleString()} in / ${msg.usage.output.toLocaleString()} out${msg.usage.cache > 0 ? ` / ${msg.usage.cache.toLocaleString()} cache` : ""}`} className="inline-flex items-center gap-0.5 rounded bg-muted/50 px-1 py-px">
                  <span>↑{fmtTokens(msg.usage.input)}</span>
                  <span>↓{fmtTokens(msg.usage.output)}</span>
                  {msg.usage.cache > 0 && <span>⚡{fmtTokens(msg.usage.cache)}</span>}
                </span>
              )}
              {msg.ttfb_ms != null && (
                <span title={`首字耗时 ${msg.ttfb_ms}ms`} className="inline-flex items-center rounded bg-muted/50 px-1 py-px">
                  TTFB {msg.ttfb_ms < 1000 ? `${msg.ttfb_ms}ms` : `${(msg.ttfb_ms / 1000).toFixed(1)}s`}
                </span>
              )}
              {msg.total_ms != null && (
                <span title={`总耗时 ${msg.total_ms}ms`} className="inline-flex items-center rounded bg-muted/50 px-1 py-px">
                  总 {msg.total_ms < 1000 ? `${msg.total_ms}ms` : msg.total_ms < 60000 ? `${(msg.total_ms / 1000).toFixed(1)}s` : `${Math.floor(msg.total_ms / 60000)}m${Math.round((msg.total_ms % 60000) / 1000)}s`}
                </span>
              )}
            </div>
          </>
        )}
        {msg.role === "assistant" && isStreaming && isLast && (
          !msg.content
            ? (
              // 尚未吐字：三点波浪 + 柔和呼吸，比单根闪条更生动
              <span className="inline-flex items-center gap-1 py-1 align-middle">
                <span className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-bounce" style={{ animationDelay: "0ms", animationDuration: "0.9s" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-bounce" style={{ animationDelay: "150ms", animationDuration: "0.9s" }} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary/70 animate-bounce" style={{ animationDelay: "300ms", animationDuration: "0.9s" }} />
              </span>
            )
            : (
              // 已在吐字：贴在文末的平滑光标
              <span className="inline-block w-1.5 h-4 rounded-full bg-primary/60 ml-0.5 align-text-bottom animate-pulse" />
            )
        )}
        </div>
        {/* 气泡操作行：分享按钮（两个角色都有） */}
        {!isStreaming && onShare && (
          <div className={`flex items-center mt-1 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <Tooltip>
              <TooltipTrigger
                render={
                  <button
                    onClick={() => onShare(msg)}
                    className="inline-flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-foreground px-1.5 py-0.5 rounded hover:bg-accent transition-colors"
                  />
                }
              />
              <TooltipContent side="bottom">分享这条消息</TooltipContent>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
    </TooltipProvider>
  );
}
