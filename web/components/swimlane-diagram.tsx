"use client";

import { useState } from "react";
import { ArrowRight, ChevronDown, ChevronUp, Loader2, CheckCircle2, XCircle } from "lucide-react";
import type { ToolStep } from "@/components/tool-timeline";

const ENTITY_CONFIG: Record<string, { label: string; color: string }> = {
  builtin:       { label: "内置工具",   color: "#6b7280" },
  file:          { label: "文件操作",   color: "#22c55e" },
  search:        { label: "搜索",       color: "#3b82f6" },
  system:        { label: "系统命令",   color: "#a855f7" },
  browser:       { label: "浏览器",     color: "#f97316" },
  delegate:      { label: "委派 Agent", color: "#eab308" },
  computer_use:  { label: "GUI 自动化", color: "#ec4899" },
  communication: { label: "通信",       color: "#06b6d4" },
  knowledge:     { label: "知识技能",   color: "#6366f1" },
  memory:        { label: "记忆",       color: "#14b8a6" },
  task:          { label: "任务调度",   color: "#f43f5e" },
  config:        { label: "配置",       color: "#64748b" },
  ui:            { label: "UI 卡片",    color: "#8b5cf6" },
  meta:          { label: "元工具",     color: "#71717a" },
};

function getColor(entityType: string | undefined) {
  if (!entityType) return ENTITY_CONFIG.builtin.color;
  return ENTITY_CONFIG[entityType]?.color ?? ENTITY_CONFIG.builtin.color;
}

function formatDuration(ms?: number) {
  if (ms === undefined) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

function StateIcon({ state }: { state: ToolStep["state"] }) {
  if (state === "running") return <Loader2 className="h-3 w-3 animate-spin text-blue-400" />;
  if (state === "done")    return <CheckCircle2 className="h-3 w-3 text-green-400" />;
  return <XCircle className="h-3 w-3 text-red-400" />;
}

const ROW_SIZE = 5;
const PREVIEW_ROWS = 2;

interface SwimlaneDiagramProps {
  steps: ToolStep[];
  matchedSkills?: { name: string; is_default?: boolean }[];
  onStepClick?: (index: number) => void;
}

export function SwimlaneDiagram({ steps, matchedSkills, onStepClick }: SwimlaneDiagramProps) {
  const [expanded, setExpanded] = useState(false);
  const doneCount = steps.filter((s) => s.state !== "running").length;
  const runCount = steps.filter((s) => s.state === "running").length;
  const hasRunning = runCount > 0;
  const usedEntities = [...new Set(steps.map((s) => s.entity_type || "builtin"))];
  const rows: ToolStep[][] = [];
  for (let i = 0; i < steps.length; i += ROW_SIZE) {
    rows.push(steps.slice(i, i + ROW_SIZE));
  }
  const needsFold = rows.length > PREVIEW_ROWS;
  const visibleRows = expanded || !needsFold ? rows : rows.slice(0, PREVIEW_ROWS);

  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-muted/30 overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground
                   hover:text-foreground hover:bg-muted/50 transition-colors text-left"
        onClick={() => setCollapsed(c => !c)}
      >
        {collapsed
          ? <ChevronDown className="h-3 w-3 shrink-0 -rotate-90" />
          : <ChevronDown className="h-3 w-3 shrink-0" />}
        <span className="font-medium">调用可视化</span>
        <span className="opacity-50">
          {hasRunning
            ? `${doneCount} 已完成${runCount > 0 ? `, ${runCount} 运行中` : ""}`
            : `${doneCount} 步`}
        </span>
        {usedEntities.length > 0 && (
          <span className="opacity-40 text-[10px] flex items-center gap-0.5 shrink-0">
            {usedEntities.map((et) => {
              const cfg = ENTITY_CONFIG[et] ?? ENTITY_CONFIG.builtin;
              return (
                <span key={et} className="flex items-center gap-0.5">
                  <span
                    className="inline-block h-2 w-2 rounded-full shrink-0"
                    style={{ backgroundColor: cfg.color }}
                  />
                  {cfg.label}
                </span>
              );
            })}
          </span>
        )}
        {hasRunning && <Loader2 className="h-3 w-3 animate-spin ml-auto shrink-0 text-blue-400" />}
      </button>

      {collapsed ? null : <>

      {matchedSkills && matchedSkills.length > 0 && (
        <div className="px-3 pb-1 flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-muted-foreground/60 shrink-0">技能:</span>
          {matchedSkills.map((s) => (
            <span
              key={s.name}
              className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{
                backgroundColor: s.is_default ? "#6366f120" : "#f9731620",
                color: s.is_default ? "#6366f1" : "#f97316",
              }}
            >
              {s.is_default ? "📦 " : "🔌 "}{s.name}
            </span>
          ))}
        </div>
      )}

      <div className="relative">
        <div className="px-3 pb-2 pt-1 overflow-x-auto">
          {visibleRows.map((row, ri) => (
            <div key={ri} className="flex items-start gap-1.5 mb-2 min-w-max">
              {row.map((step, si) => {
                const globalIdx = ri * ROW_SIZE + si;
                const color = getColor(step.entity_type);
                const isRunning = step.state === "running";
                return (
                  <div key={si} className="flex items-center gap-1.5">
                    <button
                      className={`relative rounded-md border px-2.5 py-1.5 text-xs shrink-0 text-left transition-colors ${
                        isRunning ? "animate-pulse" : "hover:shadow-sm hover:brightness-105 cursor-pointer"
                      }`}
                      style={{
                        borderColor: isRunning ? `${color}80` : `${color}50`,
                        backgroundColor: isRunning ? `${color}18` : `${color}10`,
                        minWidth: 110,
                        maxWidth: 180,
                      }}
                      title={`#${globalIdx + 1} ${step.tool}: ${step.intent || step.args}`}
                      onClick={() => onStepClick?.(globalIdx)}
                    >
                      <div className="flex items-center gap-1">
                        <span
                          className="inline-flex items-center justify-center h-4 w-4 rounded-full text-[9px] font-mono font-medium shrink-0"
                          style={{ backgroundColor: isRunning ? `${color}35` : `${color}25`, color }}
                        >
                          {globalIdx + 1}
                        </span>
                        <StateIcon state={step.state} />
                        <span className="font-mono font-medium truncate" style={{ color }}>{step.tool}</span>
                      </div>
                      {step.intent && (
                        <div className="text-[10px] opacity-60 mt-0.5 truncate leading-tight">{step.intent}</div>
                      )}
                      {step.duration_ms !== undefined && step.state !== "running" && (
                        <div className="text-[10px] opacity-40 mt-0.5">{formatDuration(step.duration_ms)}</div>
                      )}
                      {isRunning && (
                        <div className="text-[10px] opacity-50 mt-0.5 italic">执行中…</div>
                      )}
                    </button>
                    {si < row.length - 1 || (ri < visibleRows.length - 1 && si === row.length - 1) ? (
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/25" />
                    ) : null}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {!expanded && needsFold && (
          <div className="absolute bottom-0 left-0 right-0 flex flex-col items-center pointer-events-none">
            <div className="absolute bottom-0 left-0 right-0 h-[60px] bg-gradient-to-t from-muted/95 via-muted/60 to-transparent pointer-events-none" />
            <button
              className="relative mt-auto mb-0.5 px-3 py-1 text-[11px] text-muted-foreground/70 hover:text-muted-foreground transition-colors pointer-events-auto flex items-center gap-1"
              onClick={() => setExpanded(true)}
            >
              <ChevronDown className="h-3 w-3" />
              展开全部
            </button>
          </div>
        )}
      </div>

      {expanded && needsFold && (
        <div className="flex justify-center pb-2">
          <button
            className="px-3 py-1 text-[11px] text-muted-foreground/70 hover:text-muted-foreground transition-colors flex items-center gap-1"
            onClick={() => setExpanded(false)}
          >
            <ChevronUp className="h-3 w-3" />
            收起
          </button>
        </div>
      )}
      </>}
    </div>
  );
}
