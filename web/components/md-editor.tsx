"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

export function MdEditor({
  value = "",
  onChange,
  placeholder,
  defaultMode = "preview",
}: {
  value?: string;
  onChange: (v: string) => void;
  placeholder?: string;
  defaultMode?: "edit" | "preview" | "split";
}) {
  const [mode, setMode] = useState<"edit" | "preview" | "split">(defaultMode);

  return (
    <div className="flex flex-col flex-1 min-h-[400px] border border-border rounded-lg overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border bg-muted/30 shrink-0">
        {(["preview", "split", "edit"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-2.5 py-1 text-xs rounded transition-colors ${
              mode === m
                ? "bg-background border border-border font-medium"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {m === "edit" ? "编辑" : m === "split" ? "分栏" : "预览"}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground mr-7">{value.length} 字符</span>
      </div>

      {/* Editor area */}
      <div className="flex flex-1 min-h-0">
        {/* Edit pane */}
        {(mode === "edit" || mode === "split") && (
          <textarea
            className="flex-1 font-mono text-sm p-4 bg-background outline-none resize-none leading-relaxed"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            style={mode === "split" ? { borderRight: "1px solid var(--border)", width: "50%", flex: "none" } : {}}
          />
        )}

        {/* Preview pane */}
        {(mode === "preview" || mode === "split") && (
          <div className="flex-1 overflow-y-auto p-4 text-sm leading-relaxed" style={{ minWidth: 0 }}>
            {value ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                components={{
                  h1: ({ children }) => <h1 className="text-xl font-bold mt-4 mb-2 pb-1 border-b border-border">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-lg font-semibold mt-3 mb-2">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-base font-semibold mt-2 mb-1">{children}</h3>,
                  h4: ({ children }) => <h4 className="text-sm font-semibold mt-2 mb-1">{children}</h4>,
                  p: ({ children }) => <p className="my-1.5 leading-relaxed">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc pl-5 my-1.5 space-y-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-5 my-1.5 space-y-0.5">{children}</ol>,
                  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                  em: ({ children }) => <em className="italic">{children}</em>,
                  code: ({ className, children }) => {
                    const isBlock = !!className;
                    return isBlock
                      ? <code className={`${className} block bg-muted rounded px-3 py-2 text-xs font-mono overflow-x-auto`}>{children}</code>
                      : <code className="bg-muted px-1 py-0.5 rounded text-xs font-mono">{children}</code>;
                  },
                  pre: ({ children }) => <pre className="bg-muted rounded-lg p-3 overflow-x-auto text-xs my-2">{children}</pre>,
                  blockquote: ({ children }) => <blockquote className="border-l-2 border-border pl-3 text-muted-foreground my-2">{children}</blockquote>,
                  hr: () => <hr className="border-border my-3" />,
                  a: ({ href, children }) => <a href={href} className="text-primary underline underline-offset-2 hover:opacity-80" target="_blank" rel="noopener noreferrer">{children}</a>,
                }}
              >{value}</ReactMarkdown>
            ) : (
              <p className="text-muted-foreground italic">（空内容）</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
