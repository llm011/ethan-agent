"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import {
  ChevronDown, ChevronRight, Terminal, Globe, FileText,
  Search, Clock, CheckCircle2, XCircle, Loader2, Code2, Sparkles,
  WrapText, Copy, Check
} from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

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
  intent?: string;
  state: "running" | "done" | "error";
  duration_ms?: number;
  result_preview?: string;
  result_detail?: string;
  thought?: string;
  id?: string;
  sub_steps?: SubStep[];
  entity_type?: string;
  entity_id?: string;
  skill_category?: string;
}

interface ToolTimelineProps {
  steps: ToolStep[];
  defaultExpanded?: boolean;
  highlightIndex?: number;
  onHighlightDone?: () => void;
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

function tryFormatJson(text: string): { formatted: string; language: string } {
  try {
    const trimmed = text.trim();
    if ((trimmed.startsWith("{") || trimmed.startsWith("[")) && (trimmed.endsWith("}") || trimmed.endsWith("]"))) {
      return { formatted: JSON.stringify(JSON.parse(trimmed), null, 2), language: "json" };
    }
  } catch {}
  if (text.startsWith("<") && (text.includes("</") || text.includes("/>"))) {
    return { formatted: text, language: "xml" };
  }
  if (text.includes("Traceback") || text.includes("Error:") || text.includes("Exception")) {
    return { formatted: text, language: "python" };
  }
  return { formatted: text, language: "text" };
}

const HL_STYLE = { margin: 0, borderRadius: "0.5rem", fontSize: "0.75rem", lineHeight: "1.5" };

function DetailOutput({ detail }: { detail: string }) {
  const [wrap, setWrap] = useState(false);
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { formatted, language } = useMemo(() => tryFormatJson(detail), [detail]);

  const customStyle = useMemo(() => ({ ...HL_STYLE, overflowX: wrap ? "hidden" as const : "auto" as const }), [wrap]);

  useEffect(() => {
    const pre = containerRef.current?.querySelector("pre");
    if (pre) {
      pre.style.whiteSpace = wrap ? "pre-wrap" : "pre";
      pre.style.wordBreak = wrap ? "break-all" : "normal";
      pre.style.overflowX = wrap ? "hidden" : "auto";
    }
  }, [wrap]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(detail);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center justify-between mb-0.5 px-0.5">
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">输出</span>
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => setWrap(w => !w)}
            title={wrap ? "关闭自动换行" : "开启自动换行"}
            className={`p-1 rounded hover:bg-muted transition-colors ${wrap ? "text-foreground" : "text-muted-foreground"}`}
          >
            <WrapText className="h-3 w-3" />
          </button>
          <button
            onClick={handleCopy}
            title="复制"
            className="p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          </button>
        </div>
      </div>
      <div className="max-h-80 overflow-y-auto rounded">
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          customStyle={customStyle}
          showLineNumbers
          lineNumberStyle={{ color: "#555", fontSize: "0.65rem", minWidth: "2em" }}
        >
          {formatted}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}

/** 工具参数：截断显示 + hover 弹出完整内容 + 复制按钮 */
function ArgsPopover({ text, maxW = "max-w-[800px]" }: { text: string; maxW?: string }) {
  const [copied, setCopied] = useState(false);
  const [show, setShow] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>(null);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const enter = () => { if (hideTimer.current) clearTimeout(hideTimer.current); setShow(true); };
  const leave = () => { hideTimer.current = setTimeout(() => setShow(false), 150); };

  return (
    <span className="relative inline-flex items-center group/args" onMouseEnter={enter} onMouseLeave={leave}>
      <span className={`text-sm text-muted-foreground truncate ${maxW}`}>
        ({text})
      </span>
      <button
        onClick={handleCopy}
        className="ml-1 shrink-0 opacity-0 group-hover/args:opacity-100 transition-opacity text-muted-foreground/60 hover:text-foreground"
        title="复制参数"
      >
        {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
      </button>
      {show && text.length > 60 && (
        <span
          className="absolute left-0 top-full mt-1 z-50 max-w-[min(90vw,700px)] max-h-[200px] overflow-auto rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md font-mono whitespace-pre-wrap break-all"
          onMouseEnter={enter}
          onMouseLeave={leave}
        >
          {text}
        </span>
      )}
    </span>
  );
}

function StepRow({ step, isLast, highlight }: { step: ToolStep; isLast: boolean; highlight: boolean }) {
  const hasSubs = step.sub_steps && step.sub_steps.length > 0;
  const [subOpen, setSubOpen] = useState(false);
  const isDelegate = step.tool === "delegate_coding";
  const subDoneCount = hasSubs ? step.sub_steps!.filter(s => s.state !== "running").length : 0;

  const hasDetail = (step.thought || step.result_detail) && step.state !== "running";
  const [detailOpen, setDetailOpen] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlight) {
      setDetailOpen(true);
      setTimeout(() => {
        rowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 100);
    }
  }, [highlight]);

  return (
    <div ref={rowRef} className={`flex gap-2 pt-2 ${highlight ? "rounded-md bg-primary/5 -mx-1 px-1" : ""}`}>
      <div className="flex flex-col items-center mt-0.5">
        <StateIcon state={step.state} />
        {!isLast && (
          <div className="w-px flex-1 bg-border/50 mt-1 min-h-[14px]" />
        )}
      </div>

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
          {step.skill_category && (
            <span className={`text-[10px] px-1.5 py-0 rounded-full font-medium shrink-0 ${
              step.skill_category === "default" ? "bg-green-500/15 text-green-600"
              : step.skill_category === "discoverable" ? "bg-amber-500/15 text-amber-600"
              : "bg-gray-400/15 text-gray-500"
            }`}>
              {step.skill_category === "default" ? "常驻" : step.skill_category === "discoverable" ? "按需" : "插件"}
            </span>
          )}
          {step.intent && (
            <span className="text-sm text-foreground/60 truncate max-w-[360px]">
              · {step.intent}
            </span>
          )}
          {step.args && (
            <ArgsPopover text={step.args} />
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
                      <ArgsPopover text={sub.args} maxW="max-w-[550px]" />
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

        {isDelegate && step.result_preview && step.state !== "running" && !detailOpen && (
          <div className="mt-1.5 flex items-start gap-1.5 rounded-md bg-amber-500/10 border border-amber-500/25 px-2 py-1">
            <Sparkles className="h-3 w-3 text-amber-500 shrink-0 mt-0.5" />
            <p className="text-[10px] text-amber-700 dark:text-amber-300 leading-relaxed line-clamp-3">
              {step.result_preview}
            </p>
          </div>
        )}

        {!isDelegate && step.result_preview && step.state !== "running" && !detailOpen && (
          <p className="text-xs text-muted-foreground/60 mt-0.5 leading-relaxed line-clamp-2 font-mono whitespace-pre-wrap break-all">
            {step.result_preview}
          </p>
        )}

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
                <DetailOutput detail={step.result_detail} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function ToolTimeline({ steps, defaultExpanded = false, highlightIndex }: ToolTimelineProps) {
  const hasHighlight = highlightIndex !== undefined;
  const [expanded, setExpanded] = useState(defaultExpanded || hasHighlight);
  const hasRunning = steps.some(s => s.state === "running");
  const doneCount = steps.filter(s => s.state !== "running").length;
  const summaryNames = [...new Set(steps.map(s => s.tool))].join(", ");

  useEffect(() => {
    if (hasHighlight) {
      setExpanded(true);
    } else if (!defaultExpanded) {
      setExpanded(false);
    }
  }, [hasHighlight, defaultExpanded]);

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-muted/30 overflow-hidden">
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

      {expanded && (
        <div className="px-3 pb-2 space-y-0">
          {steps.map((step, i) => (
            <StepRow key={i} step={step} isLast={i === steps.length - 1} highlight={i === highlightIndex} />
          ))}
        </div>
      )}
    </div>
  );
}
