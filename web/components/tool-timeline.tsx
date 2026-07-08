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
  /** 模型填的「本次调用目的」，显示在工具名旁（如 查 MR 状态） */
  intent?: string;
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
  /** 展开看的完整结果（多行） */
  result_detail?: string;
  /** 这个工具调用前 agent 的叙述文字（挂到工具下，可折叠） */
  thought?: string;
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

/** 单个工具步骤行（可折叠 sub_steps + 展开 thought/result_detail） */
function StepRow({ step, isLast }: { step: ToolStep; isLast: boolean }) {
  const hasSubs = step.sub_steps && step.sub_steps.length > 0;
  const [subOpen, setSubOpen] = useState(false);
  const isDelegate = step.tool === "delegate_coding";
  const subDoneCount = hasSubs ? step.sub_steps!.filter(s => s.state !== "running").length : 0;

  // 有 thought 或 result_detail 才允许展开看细节
  const hasDetail = (step.thought || step.result_detail) && step.state !== "running";
  const [detailOpen, setDetailOpen] = useState(false);

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
        <div
          className={"flex items-center gap-1.5 flex-wrap" + (hasDetail ? " cursor-pointer" : "")}
          onClick={() => hasDetail && setDetailOpen(o => !o)}
        >
          <span className="text-muted-foreground/60">
            {TOOL_ICONS[step.tool] ?? <Terminal className="h-3 w-3" />}
          </span>
          <span className="text-sm font-mono font-medium text-foreground/85">
            {step.tool}
          </span>
          {step.intent && (
            <span className="text-sm text-foreground/60 truncate max-w-[360px]">
              · {step.intent}
            </span>
          )}
          {step.args && (
            <span className="text-sm text-muted-foreground truncate max-w-[800px]">
              ({step.args})
            </span>
          )}
          {hasSubs && (
            <button
              className="text-xs text-muted-foreground/70 hover:text-foreground flex items-center gap-0.5 px-1 py-0.5 rounded hover:bg-muted/60 transition-colors"
              onClick={(e) => { e.stopPropagation(); setSubOpen(o => !o); }}
            >
              {subOpen
                ? <ChevronDown className="h-2.5 w-2.5" />
                : <ChevronRight className="h-2.5 w-2.5" />}
              {subDoneCount}/{step.sub_steps!.length} 步
            </button>
          )}
          {hasDetail && (
            <button
              className="text-xs text-muted-foreground/70 hover:text-foreground flex items-center gap-0.5 px-1 py-0.5 rounded hover:bg-muted/60 transition-colors"
              onClick={(e) => { e.stopPropagation(); setDetailOpen(o => !o); }}
            >
              {detailOpen
                ? <ChevronDown className="h-2.5 w-2.5" />
                : <ChevronRight className="h-2.5 w-2.5" />}
              详情
            </button>
          )}
          {step.duration_ms !== undefined && step.state !== "running" && (
            <span className="ml-auto text-xs text-muted-foreground/60 flex items-center gap-0.5 shrink-0">
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
                    <span className="text-xs font-mono text-muted-foreground/80">
                      {sub.tool}
                    </span>
                    {sub.args && (
                      <span className="text-xs text-muted-foreground/60 truncate max-w-[550px]">
                        {sub.args}
                      </span>
                    )}
                    {sub.duration_ms !== undefined && sub.state !== "running" && (
                      <span className="ml-auto text-xs text-muted-foreground/50 shrink-0">
                        {formatDuration(sub.duration_ms)}
                      </span>
                    )}
                  </div>
                  {sub.result_preview && sub.state !== "running" && (
                    <p className="text-xs text-muted-foreground/50 mt-0.5 truncate leading-relaxed">
                      {sub.result_preview}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 委派工具的最终结果：高亮展示（暖色，明暗两种模式都可读） */}
        {isDelegate && step.result_preview && step.state !== "running" && !detailOpen && (
          <div className="mt-1.5 flex items-start gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/25 px-2 py-1">
            <Sparkles className="h-3 w-3 text-amber-500 shrink-0 mt-0.5" />
            <p className="text-[10px] text-amber-700 dark:text-amber-300 leading-relaxed line-clamp-3">
              {step.result_preview}
            </p>
          </div>
        )}

        {/* 普通工具的结果预览（未展开时显示） */}
        {!isDelegate && step.result_preview && step.state !== "running" && !detailOpen && (
          <p className="text-xs text-muted-foreground/60 mt-0.5 leading-relaxed line-clamp-2 font-mono whitespace-pre-wrap break-all">
            {step.result_preview}
          </p>
        )}

        {/* 展开的详情：工具前的叙述 + 完整结果 */}
        {detailOpen && (
          <div className="mt-1.5 rounded-md border border-border bg-background overflow-hidden">
            {step.thought && (
              <div className="px-3 py-2 border-b border-border/50">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">思考</div>
                <p className="text-sm text-foreground/80 whitespace-pre-wrap leading-relaxed">
                  {step.thought}
                </p>
              </div>
            )}
            {step.result_detail && (
              <div className="px-3 py-2">
                <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">输出</div>
                <pre className="text-sm text-slate-100 bg-slate-900 whitespace-pre-wrap break-all font-mono leading-relaxed max-h-80 overflow-y-auto rounded p-2">
                  {step.result_detail}
                </pre>
              </div>
            )}
          </div>
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
