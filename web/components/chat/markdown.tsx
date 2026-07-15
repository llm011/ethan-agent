"use client";

import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "@/components/code-block";
import { PlainCodeBlock } from "@/components/plain-code-block";
import { forwardRef } from "react";

// CommonMark 规定 ** 紧内侧不能有空格，否则不渲染加粗。
// 此函数去掉 AI 生成文本中 ** 内侧的多余空白，修复渲染。
// 气泡与阅读模式都必须经过此函数，保证「渲染后的纯文本」字符序列一致，
// 这样按字符偏移存储的标注在两边都能精确回显。
export function fixBold(text: string): string {
  return text.replace(/\*\*[ \t]*((?:[^*\n]|\*(?!\*))+?)[ \t]*\*\*/g, (_, inner) => {
    const trimmed = inner.trim();
    return trimmed ? `**${trimmed}**` : `**${inner}**`;
  });
}

export const markdownComponents: Components = {
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
  table: ({ children }) => (
    <div className="table-wrapper">
      <table>{children}</table>
    </div>
  ),
};

// 气泡与阅读模式共用同一个渲染入口，确保 DOM 文本节点序列完全一致，
// 标注偏移（基于渲染后纯文本）在两边才能对齐。
export const MarkdownContent = forwardRef<
  HTMLDivElement,
  { content: string; className?: string; variant?: "bubble" | "share" }
>(({ content, className, variant = "bubble" }, ref) => (
  <div
    ref={ref}
    className={
      variant === "share"
        ? `share-prose ${className ?? ""}`
        : `prose prose-sm dark:prose-invert max-w-none ${className ?? ""}`
    }
  >
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {fixBold(content)}
    </ReactMarkdown>
  </div>
));
MarkdownContent.displayName = "MarkdownContent";
