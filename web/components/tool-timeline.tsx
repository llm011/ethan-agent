"use client";

import { useState } from "react";
import {
  ChevronDown, ChevronRight, Terminal, Globe, FileText,
  Search, Clock, CheckCircle2, XCircle, Loader2
} from "lucide-react";

export interface ToolStep {
  tool: string;
  args: string;
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
}

interface ToolTimelineProps {
  steps: ToolStep[];
  defaultExpanded?: boolean;
}

const TOOL_ICONS: Record<string, React.ReactNode> = {
  shell:            <Terminal className="h-3 w-3" />,
  web_search:       <Search className="h-3 w-3" />,
  web_fetch:        <Globe className="h-3 w-3" />,
  file_read:        <FileText className="h-3 w-3" />,
  file_write:       <FileText className="h-3 w-3" />,
  file_list:        <FileText className="h-3 w-3" />,
  knowledge_search: <Search className="h-3 w-3" />,
  knowledge_add:    <FileText className="h-3 w-3" />,
};

function StateIcon({ state }: { state: ToolStep["state"] }) {
  if (state === "running") return <Loader2 className="h-3 w-3 animate-spin text-blue-400" />;
  if (state === "done")    return <CheckCircle2 className="h-3 w-3 text-green-400" />;
  return <XCircle className="h-3 w-3 text-red-400" />;
}

export function ToolTimeline({ steps, defaultExpanded = false }: ToolTimelineProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const hasRunning = steps.some(s => s.state === "running");
  const doneCount = steps.filter(s => s.state !== "running").length;
  const summaryNames = [...new Set(steps.map(s => s.tool))].join(", ");

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-muted/30 overflow-hidden">
      {/* 标题行 */}
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground
                   hover:text-foreground hover:bg-muted/50 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
      >
        {expanded
          ? <ChevronDown className="h-3 w-3 shrink-0" />
          : <ChevronRight className="h-3 w-3 shrink-0" />}
        <span className="font-medium">
          {hasRunning ? "Running" : `${doneCount} action${doneCount !== 1 ? "s" : ""}`}
        </span>
        <span className="truncate opacity-60">{summaryNames}</span>
        {hasRunning && <Loader2 className="h-3 w-3 animate-spin ml-auto shrink-0 text-blue-400" />}
      </button>

      {/* 展开的时间轴 */}
      {expanded && (
        <div className="px-3 pb-2 space-y-0">
          {steps.map((step, i) => (
            <div key={i} className="flex gap-2 pt-2">
              {/* 竖线 + 状态图标 */}
              <div className="flex flex-col items-center mt-0.5">
                <StateIcon state={step.state} />
                {i < steps.length - 1 && (
                  <div className="w-px flex-1 bg-border/50 mt-1 min-h-[14px]" />
                )}
              </div>

              {/* 工具内容 */}
              <div className="flex-1 min-w-0 pb-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-muted-foreground/60">
                    {TOOL_ICONS[step.tool] ?? <Terminal className="h-3 w-3" />}
                  </span>
                  <span className="text-xs font-mono font-medium text-foreground/80">
                    {step.tool}
                  </span>
                  {step.args && (
                    <span className="text-xs text-muted-foreground truncate max-w-[180px]">
                      ({step.args})
                    </span>
                  )}
                  {step.duration_ms !== undefined && step.state !== "running" && (
                    <span className="ml-auto text-[10px] text-muted-foreground/50
                                     flex items-center gap-0.5 shrink-0">
                      <Clock className="h-2.5 w-2.5" />
                      {step.duration_ms < 1000
                        ? `${step.duration_ms}ms`
                        : `${(step.duration_ms / 1000).toFixed(1)}s`}
                    </span>
                  )}
                </div>
                {step.result_preview && step.state !== "running" && (
                  <p className="text-[10px] text-muted-foreground/50 mt-0.5 truncate leading-relaxed">
                    {step.result_preview}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
