
import { useState, useEffect, useRef, useMemo } from "react";
import {
  ChevronDown, ChevronRight, Terminal, Globe, FileText,
  Search, Clock, CheckCircle2, XCircle, Loader2, Code2, Sparkles,
  WrapText, Copy, Check, BrainCircuit, MessageSquareText, X, Ban
} from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { SearchResultCard } from "../chat/search-card-carousel";

export interface SubStep {
  tool: string;
  args: string;
  state: "running" | "done" | "error" | "cancelled";
  duration_ms?: number;
  result_preview?: string;
}

export interface ToolStep {
  tool: string;
  args: string;
  intent?: string;
  state: "running" | "done" | "error" | "cancelled";
  duration_ms?: number;
  result_preview?: string;
  result_detail?: string;
  thought?: string;
  id?: string;
  sub_steps?: SubStep[];
  cards?: SearchResultCard[];
  entity_type?: string;
  entity_id?: string;
  skill_category?: string;
  injected?: string[];
}

interface ToolTimelineProps {
  steps: ToolStep[];
  defaultExpanded?: boolean;
  highlightIndex?: number;
  onHighlightDone?: () => void;
  /** 老会话回退：step 上没有 cards 时，用消息级 cards 兜底（避免历史数据丢失） */
  messageCards?: SearchResultCard[];
  /** 取消正在运行的工具调用（tool_call_id）。仅在工具 running 状态可用。 */
  onCancelTool?: (toolCallId: string) => void;
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
  memory_recall:    <BrainCircuit className="h-3 w-3" />,
};

function StateIcon({ state }: { state: ToolStep["state"] }) {
  if (state === "running") return <Loader2 className="h-3 w-3 animate-spin text-blue-400" />;
  if (state === "done")    return <CheckCircle2 className="h-3 w-3 text-green-400" />;
  if (state === "cancelled") return <Ban className="h-3 w-3 text-muted-foreground" />;
  return <XCircle className="h-3 w-3 text-red-400" />;
}

/** 取消按钮：点击后立即隐藏（乐观 UI），避免工具恰好完成时点 X 无反馈。
 *  cancelled=false 时工具已完成，SSE 会很快把 state 从 running 更新为 done/error/cancelled。 */
function CancelButton({ onClick }: { onClick: (e: React.MouseEvent) => void }) {
  const [clicked, setClicked] = useState(false);
  if (clicked) return <Loader2 className="ml-auto h-3 w-3 animate-spin text-muted-foreground/50 shrink-0" />;
  return (
    <button
      className="ml-auto p-0.5 rounded text-muted-foreground/50 hover:text-red-500 hover:bg-red-500/10 transition-colors shrink-0"
      title="终止此工具"
      onClick={(e) => { e.stopPropagation(); setClicked(true); onClick(e); }}
    >
      <X className="h-3 w-3" />
    </button>
  );
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

/** 解析 [image:<mime>:<base64>:<filename>] 标记。返回 null 表示不是图片标记。 */
function parseImageMarker(detail: string): { mime: string; b64: string; filename: string } | { tooLarge: true; mime: string; size: string; filename: string } | null {
  if (!detail.startsWith("[image:")) return null;
  // [image:<mime>:<b64>:<filename>]
  // base64 不含冒号，filename 不含 ]，所以 split(":", 3) 安全
  const m = detail.match(/^\[image:([^:]+):([^:]+):([^\]]+)\]$/);
  if (!m) return null;
  const [, mime, payload, filename] = m;
  if (mime === "too-large") {
    // 格式实际上是 [image:too-large:<mime>:<size>:<filename>]
    // 上面正则把 mime 匹配成 "too-large"，payload 是真实 mime，filename 是 "size:filename"
    const parts = filename.split(":");
    return { tooLarge: true, mime: payload, size: parts[0] || "?", filename: parts.slice(1).join(":") || "image" };
  }
  return { mime, b64: payload, filename };
}

function ImageOutput({ detail }: { detail: string }) {
  const [copied, setCopied] = useState(false);
  const parsed = useMemo(() => parseImageMarker(detail), [detail]);
  if (!parsed) return null;

  if ("tooLarge" in parsed) {
    return (
      <div className="px-3 py-3 text-center text-xs text-muted-foreground">
        🖼️ {parsed.filename}（{parsed.mime}，{parsed.size} 字节，过大未渲染）
      </div>
    );
  }

  const src = `data:${parsed.mime};base64,${parsed.b64}`;
  const handleCopy = async () => {
    await navigator.clipboard.writeText(detail);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-0.5 px-0.5">
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          🖼️ {parsed.filename} · {parsed.mime}
        </span>
        <button
          onClick={handleCopy}
          title="复制 Base64"
          className="p-1 rounded hover:bg-muted text-muted-foreground transition-colors"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        </button>
      </div>
      <div className="max-h-96 overflow-y-auto rounded flex justify-center bg-muted/20 p-2">
        <img
          src={src}
          alt={parsed.filename}
          className="max-w-full max-h-96 object-contain rounded"
          style={{ imageRendering: "auto" }}
        />
      </div>
    </div>
  );
}

function DetailOutput({ detail }: { detail: string }) {
  const [wrap, setWrap] = useState(false);
  const [copied, setCopied] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const isImage = detail.startsWith("[image:");
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

  if (isImage) {
    return <ImageOutput detail={detail} />;
  }

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

function parseSearchResults(detail: string): SearchResultCard[] | null {
  const blocks = detail.split(/\n\n+/);
  const results: SearchResultCard[] = [];
  for (const block of blocks) {
    let lines = block.split("\n").map(l => l.trimEnd()).filter(l => l.trim());
    if (lines.length === 0) continue;
    if (/^Found ~\d+ results/i.test(lines[0])) {
      lines = lines.slice(1);
      if (lines.length === 0) continue;
    }
    const urlLine = lines.find(l => /^https?:\/\//.test(l.trim()));
    if (!urlLine) continue;
    const url = urlLine.trim();
    const titleLine = lines.find(l => /^\*\*.*\*\*$/.test(l.trim())) ?? lines[0];
    const m = titleLine.match(/^\*\*(?:\[([^\]]*)\]\s*)?(.+?)(?:\s{2}\[(\d{4}[^\]]*)\])?\*\*$/);
    let title = titleLine.replace(/^\*\*|\*\*$/g, "");
    let source = "";
    let published = "";
    if (m) {
      source = m[1] || "";
      title = m[2] || title;
      published = m[3] || "";
    }
    const snippetLines = lines.filter(l => l !== titleLine && l !== urlLine);
    const snippet = snippetLines.join(" ").trim();
    results.push({ type: "search_result", title, url, snippet, engine: source || "", source: "", published: published || "" });
  }
  return results.length > 0 ? results : null;
}

/** web_search 详情：优先消费后端产出的结构化搜索卡片，也兼容旧文本格式解析（浅色可读列表） */

/** 将 ISO / 日期字符串统一格式化为 YYYY-MM-DD；无法解析则原样返回前 10 字符 */
function formatDate(raw: string): string {
  if (!raw) return "";
  // 已是 YYYY-MM-DD 格式（10 字符）
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
  // 尝试解析 ISO（2026-08-03T07:06:33.218901+00:00 / 2026-08-03T07:06:33Z）
  const d = new Date(raw);
  if (!isNaN(d.getTime())) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }
  // 兜底：截取前 10 字符
  return raw.slice(0, 10);
}

function SearchResultList({ results }: { results: SearchResultCard[] }) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-1 rounded-md">
      {results.map((r, i) => {
        let domain = "";
        try { domain = new URL(r.url).hostname.replace(/^www\./, ""); } catch {}
        return (
          <a
            key={`${r.url}-${i}`}
            href={r.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ textDecoration: "none" }}
            className="block w-[250px] min-w-[250px] max-w-[250px] flex-shrink-0 px-3 py-2 rounded-lg border border-border/60 bg-background no-underline hover:bg-muted/50 hover:border-border transition-colors group"
          >
            <div className="flex items-center gap-1.5 mb-1 min-w-0">
              {r.engine && (
                <span className="text-[10px] px-1.5 py-0 rounded-full font-medium bg-primary/10 text-primary shrink-0 uppercase tracking-wide">
                  {r.engine}
                </span>
              )}
              {r.source && (
                <span className="text-[10px] text-muted-foreground/60 truncate min-w-0 flex-1">{r.source}</span>
              )}
              {r.published && (
                <span className="text-[10px] text-muted-foreground/60 shrink-0 tabular-nums">{formatDate(r.published)}</span>
              )}
            </div>
            <div className="text-sm font-medium text-foreground/85 group-hover:text-primary line-clamp-2 leading-snug">
              {r.title}
            </div>
            {r.snippet && (
              <p className="text-xs text-muted-foreground/70 mt-1 line-clamp-3 leading-relaxed">
                {r.snippet}
              </p>
            )}
            <div className="text-[10px] text-muted-foreground/50 mt-1 truncate">{domain}</div>
          </a>
        );
      })}
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
    <span className="relative inline-flex items-center max-w-full group/args" onMouseEnter={enter} onMouseLeave={leave}>
      <span className={`text-sm text-muted-foreground truncate min-w-0 ${maxW}`}>
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

function StepRow({ step, isLast, highlight, fallbackCards, onCancelTool }: { step: ToolStep; isLast: boolean; highlight: boolean; fallbackCards?: SearchResultCard[]; onCancelTool?: (toolCallId: string) => void }) {
  const hasSubs = step.sub_steps && step.sub_steps.length > 0;
  const [subOpen, setSubOpen] = useState(false);
  const isDelegate = step.tool === "delegate_coding";
  const subDoneCount = hasSubs ? step.sub_steps!.filter(s => s.state !== "running").length : 0;

  const hasDetail = (step.thought || step.result_detail) && step.state !== "running";
  const [detailOpen, setDetailOpen] = useState(false);
  const rowRef = useRef<HTMLDivElement>(null);
  // web_search 详情优先用 step 自带的结构化卡片；老会话仅在 fallbackCards 门控放行时回退到消息级 cards；再兼容旧文本格式解析（不丢数据）
  const searchResults: SearchResultCard[] | null = step.tool === "web_search"
    ? ((step.cards && step.cards.length > 0) ? step.cards
        : (fallbackCards && fallbackCards.length > 0 ? fallbackCards
          : (step.result_detail ? parseSearchResults(step.result_detail) : null)))
    : null;

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
        {step.injected && step.injected.length > 0 && (
          <div className="mb-1.5 rounded-md bg-blue-500/8 border border-blue-500/20 px-2.5 py-1.5">
            <div className="flex items-start gap-1.5">
              <MessageSquareText className="h-3 w-3 text-blue-500 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <div className="text-[10px] text-blue-600 dark:text-blue-400 font-medium mb-0.5">补充信息</div>
                {step.injected.map((msg, i) => (
                  <p key={i} className="text-xs text-foreground/70 leading-relaxed whitespace-pre-wrap break-words">
                    {msg}
                  </p>
                ))}
              </div>
            </div>
          </div>
        )}
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
          {step.duration_ms != null && step.state !== "running" && (
            <span className="ml-auto text-xs text-muted-foreground/60 flex items-center gap-0.5 shrink-0">
              <Clock className="h-2.5 w-2.5" />
              {formatDuration(step.duration_ms)}
            </span>
          )}
          {step.state === "running" && onCancelTool && step.id && (
            <CancelButton onClick={(e) => { e.stopPropagation(); onCancelTool(step.id!); }} />
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
                    {sub.duration_ms != null && sub.state !== "running" && (
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
                <div className="text-sm text-foreground/80 leading-relaxed prose prose-sm prose-neutral dark:prose-invert max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{step.thought}</ReactMarkdown>
                </div>
              </div>
            )}
            {step.result_detail && (
              <div className="px-3 py-2">
                {searchResults ? <SearchResultList results={searchResults} /> : <DetailOutput detail={step.result_detail} />}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function ToolTimeline({ steps: rawSteps, defaultExpanded = false, highlightIndex, messageCards, onCancelTool }: ToolTimelineProps) {
  const steps = useMemo(() => {
    if (onCancelTool || !rawSteps.some(s => s.state === "running")) return rawSteps;
    return rawSteps.map(s => s.state === "running" ? { ...s, state: "cancelled" as const } : s);
  }, [rawSteps, onCancelTool]);
  const hasHighlight = highlightIndex !== undefined;
  const [expanded, setExpanded] = useState(defaultExpanded || hasHighlight);
  const hasRunning = steps.some(s => s.state === "running");
  const doneCount = steps.filter(s => s.state !== "running").length;
  const summaryNames = [...new Set(steps.map(s => s.tool))].join(", ");
  // messageCards 是整条消息合并后的搜索结果，无法按 step 拆分归属。
  // 仅当消息里恰好只有一个 web_search step 时才用它兜底（归属唯一）；
  // 多个搜索时传 undefined，各 step 回退到自身 result_detail 文本解析，避免重复与错配。
  const webSearchCount = steps.filter(s => s.tool === "web_search").length;
  const fallbackCards = webSearchCount === 1 ? messageCards : undefined;

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
        <span className="font-medium shrink-0 whitespace-nowrap">
          {hasRunning ? "Running" : `${doneCount} action${doneCount !== 1 ? "s" : ""}`}
        </span>
        <span className="truncate opacity-60">{summaryNames}</span>
        {hasRunning && <Loader2 className="h-3 w-3 animate-spin ml-auto shrink-0 text-blue-400" />}
      </button>

      {expanded && (
        <div className="px-3 pb-2 space-y-0">
          {steps.map((step, i) => (
            <StepRow key={i} step={step} isLast={i === steps.length - 1} highlight={i === highlightIndex} fallbackCards={fallbackCards} onCancelTool={onCancelTool} />
          ))}
        </div>
      )}
    </div>
  );
}
