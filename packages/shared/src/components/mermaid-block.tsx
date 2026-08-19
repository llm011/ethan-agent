"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy, Expand, AlertCircle } from "lucide-react";
import { Lightbox } from "../chat/lightbox";
import { PlainCodeBlock } from "./plain-code-block";

interface MermaidBlockProps {
  code: string;
}

// 模块级单例：mermaid 库动态加载 + 主题初始化标志。
// 避免每个 MermaidBlock 实例都重复 initialize。
let _mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
let _currentTheme: "dark" | "default" = "default";

async function getMermaid(theme: "dark" | "default") {
  const mod = await (_mermaidPromise ??= import("mermaid").then((m) => m.default));
  if (_currentTheme !== theme) {
    _currentTheme = theme;
    mod.initialize({ startOnLoad: false, theme, securityLevel: "antiscript" });
  }
  return mod;
}

// 流式友好：code 变化后等 150ms 无新内容再 parse，避免半截代码块报错闪烁。
function useDebounced<T>(value: T, delay = 150): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export function MermaidBlock({ code }: MermaidBlockProps) {
  const debouncedCode = useDebounced(code);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [zoomOpen, setZoomOpen] = useState(false);
  // 每个 MermaidBlock 实例独立 render id（mermaid 要求 svg id 唯一）
  const idRef = useRef(`mermaid-${Math.random().toString(36).slice(2, 10)}`);
  const renderSeq = useRef(0);

  useEffect(() => {
    if (!debouncedCode.trim()) {
      setSvg("");
      setError("");
      return;
    }
    let cancelled = false;
    const seq = ++renderSeq.current;
    (async () => {
      try {
        const mermaid = await getMermaid("default");
        if (cancelled || seq !== renderSeq.current) return;
        await mermaid.parse(debouncedCode);
        if (cancelled || seq !== renderSeq.current) return;
        const { svg: rendered } = await mermaid.render(
          `${idRef.current}-${seq}`,
          debouncedCode,
        );
        if (cancelled || seq !== renderSeq.current) return;
        setSvg(rendered);
        setError("");
      } catch (e: unknown) {
        if (cancelled || seq !== renderSeq.current) return;
        setSvg("");
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg.replace(/^.*?Syntax error in text/s, "Syntax error in text") || "渲染失败");
      } finally {
        // mermaid 11.x may leave orphaned error/render containers in the DOM
        const orphan = document.getElementById(`${idRef.current}-${seq}`);
        orphan?.closest(".mermaid")?.remove();
        orphan?.remove();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [debouncedCode]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const svgNode = useMemo(
    () => (svg ? <div dangerouslySetInnerHTML={{ __html: svg }} /> : null),
    [svg],
  );

  const svgDataUrl = useMemo(
    () => svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : "",
    [svg],
  );

  return (
    <div className="relative group my-3 rounded-lg border border-border overflow-hidden">
      <div className="absolute right-2 top-2 z-10 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {svg && (
          <button
            onClick={() => setZoomOpen(true)}
            aria-label="放大查看"
            title="放大查看"
            className="p-1.5 rounded bg-zinc-700/80 text-zinc-300 hover:text-white transition-colors"
          >
            <Expand className="h-3.5 w-3.5" />
          </button>
        )}
        <button
          onClick={handleCopy}
          aria-label="复制代码"
          title="复制代码"
          className="p-1.5 rounded bg-zinc-700/80 text-zinc-300 hover:text-white transition-colors"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>

      {error ? (
        <div className="flex flex-col">
          <div className="flex items-start gap-2 px-3 py-2 bg-red-500/10 text-red-600 dark:text-red-400 text-xs">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="flex-1 break-all">
              <div className="font-medium">Mermaid 渲染失败</div>
              <div className="mt-0.5 opacity-80">{error}</div>
            </div>
          </div>
          <PlainCodeBlock code={code} />
        </div>
      ) : svgNode ? (
        <div
          className="flex items-center justify-center p-4 bg-white cursor-zoom-in"
          onClick={() => setZoomOpen(true)}
        >
          {svgNode}
        </div>
      ) : (
        <div className="p-4 text-xs text-muted-foreground">渲染中…</div>
      )}

      <Lightbox
        images={svg ? [{ url: svgDataUrl, html: svg, title: "Mermaid Diagram" }] : []}
        index={0}
        open={zoomOpen}
        onOpenChange={setZoomOpen}
      />
    </div>
  );
}
