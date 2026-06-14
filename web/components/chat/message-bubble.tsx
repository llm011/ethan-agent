"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ToolTimeline } from "@/components/tool-timeline";
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
}

export function MessageBubble({ msg, isStreaming, isLast }: MessageBubbleProps) {
  return (
    <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[90%] md:max-w-[80%] rounded-2xl px-4 py-3 ${
          msg.role === "user"
            ? "bg-primary text-primary-foreground"
            : "bg-muted prose prose-sm dark:prose-invert max-w-none"
        }`}
      >
        {msg.role === "user" ? (
          <>
            {msg.files && msg.files.length > 0 && (
              <div className="text-xs opacity-70 mb-1">
                {msg.files.map((f, j) => <span key={j} className="mr-2">📎 {f}</span>)}
              </div>
            )}
            <p className="whitespace-pre-wrap">{msg.content.split("\n\n").pop()}</p>
            {msg.created_at && (
              <div className="text-[10px] opacity-40 mt-1 text-right">
                {formatTime(msg.created_at)}
              </div>
            )}
          </>
        ) : (
          <>
            {msg.toolSteps && msg.toolSteps.length > 0 && (
              <ToolTimeline steps={msg.toolSteps} defaultExpanded={msg.toolsExpanded ?? false} />
            )}
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                pre: ({ children }) => <pre className="bg-background/50 rounded-lg p-3 overflow-x-auto text-xs">{children}</pre>,
                code: ({ className, children, ...props }) => {
                  const isInline = !className;
                  return isInline
                    ? <code className="bg-background/50 px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
                    : <code className={className} {...props}>{children}</code>;
                },
              }}
            >
              {fixBold(msg.content)}
            </ReactMarkdown>
            <div className="flex justify-end items-center mt-2 gap-1.5 text-[10px] text-muted-foreground/35 tabular-nums">
              {msg.created_at && <span>{formatTime(msg.created_at)}</span>}
              {msg.usage && (
                <>
                  {msg.created_at && <span className="inline-block w-px h-2.5 bg-muted-foreground/20" />}
                  <span>↑{msg.usage.input.toLocaleString()}</span>
                  <span>↓{msg.usage.output.toLocaleString()}</span>
                  {msg.usage.cache > 0 && <span>⚡{msg.usage.cache.toLocaleString()}</span>}
                  {msg.ttft !== undefined && <span>{msg.ttft < 1000 ? `${msg.ttft}ms` : `${(msg.ttft / 1000).toFixed(1)}s`}</span>}
                </>
              )}
            </div>
          </>
        )}
        {msg.role === "assistant" && isStreaming && isLast && (
          <span className="inline-block w-2 h-4 bg-foreground/50 animate-pulse ml-0.5" />
        )}
      </div>
    </div>
  );
}
