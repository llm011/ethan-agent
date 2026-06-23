"use client";

import { useState } from "react";
import {
  ChevronDown, ChevronRight, Terminal, Globe, FileText,
  Search, Clock, CheckCircle2, XCircle, Loader2, Code2, Sparkles
} from "lucide-react";

export interface SubStep {
  tool: string;
  args: string;
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
}

export interface ToolStep {
  tool: string;
  args: string;
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
  /** 唯一标识，用于精确配对 start/done（同名工具并发时不串） */
  id?: string;
  /** 委派类工具（如 delegate_coding）的内部子步骤 */
  sub_steps?: SubStep[];
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
  delegate_coding:  <Code2 className="h-3 w-3" />,
};

function StateIcon({ state }: { state: ToolStep["state"] }) {
  if (state === "running") return <Loader2 className="h-3 w-3 animate-spin text-blue-400" />;
  if (state === "done")    return <CheckCircle2 className="h-3 w-3 text-green-400" />;
  return <XCircle className="h-3 w-3 text-red-400" />;
}

function formatDuration(ms?: number) {
  if (ms === undefined) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** 单个工具步骤行（可折叠 sub_steps） */
function StepRow({ step, isLast }: { step: ToolStep; isLast: boolean }) {
  const hasSubs = step.sub_steps && step.sub_steps.length > 0;
  const [subOpen, setSubOpen] = useState(false);
  const isDelegate = step.tool === "delegate_coding";
  const subDoneCount = hasSubs ? step.sub_steps!.filter(s => s.state !== "running").length : 0;

  return (
    <div className="flex gap-2 pt-2">
      {/* 竖线 + 状态图标 */}
      <div className="flex flex-col items-center mt-0.5">
        <StateIcon state={step.state} />
        {!isLast && (
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
            <span className="text-xs text-muted-foreground truncate max-w-[320px]">
              ({step.args})
            </span>
          )}
          {hasSubs && (
            <button
              className="text-[10px] text-muted-foreground/70 hover:text-foreground flex items-center gap-0.5 px-1 py-0.5 rounded hover:bg-muted/60 transition-colors"
              onClick={(e) => { e.stopPropagation(); setSubOpen(o => !o); }}
            >
              {subOpen
                ? <ChevronDown className="h-2.5 w-2.5" />
                : <ChevronRight className="h-2.5 w-2.5" />}
              {subDoneCount}/{step.sub_steps!.length} 步
            </button>
          )}
          {step.duration_ms !== undefined && step.state !== "running" && (
            <span className="ml-auto text-[10px] text-muted-foreground/50 flex items-center gap-0.5 shrink-0">
              <Clock className="h-2.5 w-2.5" />
              {formatDuration(step.duration_ms)}
            </span>
          )}
        </div>

        {/* 子步骤（折叠）— delegate_coding 等委派工具的内部 Coding Agent 调用 */}
        {hasSubs && subOpen && (
          <div className="mt-1.5 ml-1 pl-3 border-l border-border/40 space-y-0.5">
            {step.sub_steps!.map((sub, j) => (
              <div key={j} className="flex items-start gap-1.5 py-0.5">
                <span className="mt-0.5 shrink-0">
                  <StateIcon state={sub.state} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="text-[10px] font-mono text-muted-foreground/80">
                      {sub.tool}
                    </span>
                    {sub.args && (
                      <span className="text-[10px] text-muted-foreground/50 truncate max-w-[220px]">
                        {sub.args}
                      </span>
                    )}
                    {sub.duration_ms !== undefined && sub.state !== "running" && (
                      <span className="ml-auto text-[10px] text-muted-foreground/40 shrink-0">
                        {formatDuration(sub.duration_ms)}
                      </span>
                    )}
                  </div>
                  {sub.result_preview && sub.state !== "running" && (
                    <p className="text-[10px] text-muted-foreground/40 mt-0.5 truncate leading-relaxed">
                      {sub.result_preview}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 委派工具的最终结果：高亮展示 */}
        {isDelegate && step.result_preview && step.state !== "running" && (
          <div className="mt-1.5 flex items-start gap-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/20 px-2 py-1">
            <Sparkles className="h-3 w-3 text-emerald-400 shrink-0 mt-0.5" />
            <p className="text-[10px] text-emerald-300/90 leading-relaxed line-clamp-3">
              {step.result_preview}
            </p>
          </div>
        )}

        {/* 普通工具的结果预览 */}
        {!isDelegate && step.result_preview && step.state !== "running" && (
          <p className="text-[10px] text-muted-foreground/50 mt-0.5 leading-relaxed line-clamp-3 font-mono break-all">
            {step.result_preview}
          </p>
        )}
      </div>
    </div>
  );
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
            <StepRow key={i} step={step} isLast={i === steps.length - 1} />
          ))}
        </div>
      )}
    </div>
  );
}
