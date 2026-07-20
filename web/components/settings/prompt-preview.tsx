"use client";

import { useState, useEffect } from "react";
import { Button } from "@ethan/shared/ui/button";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchSystemPromptPreview, SystemPromptPreview } from "@/lib/api";

export function PromptPreview() {
  const [data, setData] = useState<SystemPromptPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [promptView, setPromptView] = useState<"raw" | "md">("md");

  const load = async () => {
    setLoading(true);
    try {
      const d = await fetchSystemPromptPreview();
      setData(d);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  // Parse the prompt into sections split by XML-like tags.
  // Returns an array of {tag, content} — untagged content has tag = null.
  function parseSections(text: string): { tag: string | null; content: string }[] {
    const lines = text.split("\n");
    const sections: { tag: string | null; content: string }[] = [];
    let currentTag: string | null = null;
    let currentLines: string[] = [];

    for (const line of lines) {
      const openMatch = line.match(/^<([a-zA-Z_][a-zA-Z0-9_-]*)(?:\s[^>]*)?>$/);
      const closeMatch = line.match(/^<\/([a-zA-Z_][a-zA-Z0-9_-]*)>$/);

      if (openMatch) {
        if (currentLines.join("").trim()) {
          sections.push({ tag: currentTag, content: currentLines.join("\n").trim() });
        }
        currentTag = openMatch[1];
        currentLines = [];
      } else if (closeMatch) {
        sections.push({ tag: currentTag, content: currentLines.join("\n").trim() });
        currentTag = null;
        currentLines = [];
      } else {
        currentLines.push(line);
      }
    }
    if (currentLines.join("").trim()) {
      sections.push({ tag: currentTag, content: currentLines.join("\n").trim() });
    }
    return sections;
  }

  return (
    <div className="h-full flex flex-col min-h-[500px] gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">Prompt 预览</h3>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          {loading ? "加载中..." : "刷新"}
        </Button>
      </div>

      {data && (
        <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm space-y-1">
          <div className="flex justify-between">
            <span className="text-muted-foreground">System prompt</span>
            <span className="font-mono">~{data.approx_tokens.toLocaleString()} tokens ({data.chars.toLocaleString()} 字符)</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Tools schema（{data.tool_count} 个工具）</span>
            <span className="font-mono">~{data.approx_tools_tokens.toLocaleString()} tokens</span>
          </div>
          <div className="border-t pt-1 mt-1 flex justify-between font-semibold">
            <span>Total（每轮 input 底线）</span>
            <span className="font-mono">~{data.approx_total_tokens.toLocaleString()} tokens</span>
          </div>
        </div>
      )}

      {data && (
        <div className="rounded-lg border overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-4 py-2 text-sm font-medium bg-muted/30 hover:bg-muted/50 transition-colors"
            onClick={() => setToolsOpen(o => !o)}
          >
            <span>工具 Schema（{data.tool_count} 个）</span>
            <span className="text-muted-foreground text-xs">{toolsOpen ? "收起 ▲" : "展开 ▼"}</span>
          </button>
          {toolsOpen && (
            <div className="divide-y max-h-[400px] overflow-auto">
              {data.tools.map(tool => (
                <div key={tool.name} className="p-3 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold">{tool.name}</span>
                    {!tool.fast_path && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">full-path only</span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{tool.description}</p>
                  <pre className="text-[11px] font-mono bg-muted/40 rounded p-2 overflow-auto whitespace-pre-wrap text-muted-foreground leading-relaxed">
                    {JSON.stringify(tool.parameters, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* View toggle */}
      <div className="flex items-center gap-1 self-end">
        {(["md", "raw"] as const).map(v => (
          <button
            key={v}
            onClick={() => setPromptView(v)}
            className={`px-2.5 py-1 text-xs rounded transition-colors border ${
              promptView === v
                ? "bg-background border-border font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {v === "md" ? "预览" : "原文"}
          </button>
        ))}
      </div>

      {promptView === "raw" ? (
        <pre className="flex-1 text-xs font-mono bg-muted/40 rounded-lg p-4 overflow-auto whitespace-pre-wrap leading-relaxed text-muted-foreground">
          {data ? data.system_prompt : (loading ? "加载中..." : "")}
        </pre>
      ) : (
        <div className="flex-1 overflow-auto space-y-2 pb-4">
          {data ? parseSections(data.system_prompt).map((section, i) => (
            <div key={i} className="rounded-lg border border-border/60 overflow-hidden">
              {section.tag && (
                <div className="px-4 py-1.5 bg-muted/40 border-b border-border/40 flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">{section.tag}.md</span>
                </div>
              )}
              <div className="px-4 py-3 prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.content}</ReactMarkdown>
              </div>
            </div>
          )) : (
            <p className="text-muted-foreground italic text-sm">{loading ? "加载中..." : ""}</p>
          )}
        </div>
      )}
    </div>
  );
}
