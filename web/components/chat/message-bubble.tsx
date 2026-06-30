"use client";

import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Quote as QuoteIcon } from "lucide-react";
import { ToolTimeline } from "@/components/tool-timeline";
import { fmtTokens } from "@/lib/utils";
import { CodeBlock } from "@/components/code-block";
import { PlainCodeBlock } from "@/components/plain-code-block";
import { A2uiCard } from "./a2ui-card";
import type { Message } from "./types";

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
}

export function MessageBubble({ msg, isStreaming, isLast, onQuote, onCardAction }: MessageBubbleProps) {
  return (
    <div className={`group flex ${msg.role === "user" ? "justify-end" : "justify-start"} gap-2`}>
      {msg.role === "assistant" && (
        <div className="flex-shrink-0 mt-1">
          <Image src="/logo-avatar.png" alt="Ethan" width={28} height={28} className="rounded-full" />
        </div>
      )}
      <div className="relative max-w-[90%] md:max-w-[80%]">
        {/* 悬浮引用按钮 */}
        {onQuote && !isStreaming && (
          <button
            onClick={() => onQuote(msg)}
            className={`absolute -top-2 ${msg.role === "user" ? "-left-7" : "-right-7"} opacity-0 group-hover:opacity-100 transition-opacity h-6 w-6 flex items-center justify-center rounded-md bg-muted border border-border text-muted-foreground hover:text-foreground hover:bg-accent`}
            title="引用此消息"
          >
            <QuoteIcon className="h-3 w-3" />
          </button>
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
              <details className="mb-2 border border-border/50 bg-background/50 rounded-lg overflow-hidden group">
                <summary className="px-3 py-1.5 text-xs text-muted-foreground font-medium cursor-pointer hover:bg-background/80 flex items-center transition-colors list-none select-none">
                  <span className="opacity-70 group-open:opacity-100 transition-opacity">🤔 思考过程</span>
                </summary>
                <div className="px-3 py-2 text-xs text-muted-foreground opacity-80 border-t border-border/50 bg-background/30 whitespace-pre-wrap leading-relaxed">
                  {msg.thought}
                </div>
              </details>
            )}
            {msg.toolSteps && msg.toolSteps.length > 0 && (
              <ToolTimeline steps={msg.toolSteps} defaultExpanded={msg.toolsExpanded ?? false} />
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code: ({ className, children }) => {
                  const match = /language-(\w+)/.exec(className || "");
                  const raw = String(children);
                  if (match) {
                    return <CodeBlock language={match[1]} code={raw.replace(/\n$/, "")} />;
                  }
                  if (raw.includes("\n")) {
                    return <PlainCodeBlock code={raw.replace(/\n$/, "")} />;
                  }
                  return <code className="bg-background/50 px-1 py-0.5 rounded text-xs font-mono break-all">{children}</code>;
                },
                pre: ({ children }) => <>{children}</>,
              }}
            >
              {fixBold(msg.content)}
            </ReactMarkdown>
            {msg.a2ui && msg.a2ui.length > 0 && (
              <A2uiCard surfaces={msg.a2ui} onAction={onCardAction} />
            )}
            <div className="flex justify-end items-center mt-2 gap-1.5 text-[10px] text-muted-foreground/35 tabular-nums">
              {msg.created_at && <span>{formatTime(msg.created_at)}</span>}
              {msg.usage && (
                <>
                  {msg.created_at && <span className="inline-block w-px h-2.5 bg-muted-foreground/20" />}
                  <span title={`${msg.usage.input.toLocaleString()} tokens`}>↑{fmtTokens(msg.usage.input)}</span>
                  <span title={`${msg.usage.output.toLocaleString()} tokens`}>↓{fmtTokens(msg.usage.output)}</span>
                  {msg.usage.cache > 0 && <span title={`${msg.usage.cache.toLocaleString()} tokens`}>⚡{fmtTokens(msg.usage.cache)}</span>}
                  {msg.ttft !== undefined && <span>{msg.ttft < 1000 ? `${msg.ttft}ms` : `${(msg.ttft / 1000).toFixed(1)}s`}</span>}
                </>
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
      </div>
    </div>
  );
}
