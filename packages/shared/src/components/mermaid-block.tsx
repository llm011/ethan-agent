"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Copy, Expand, AlertCircle } from "lucide-react";
import { Dialog, DialogContent } from "../ui/dialog";
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
    mod.initialize({ startOnLoad: false, theme, securityLevel: "loose" });
  }
  return mod;
}

// 监听系统暗色主题（与应用主题通常一致；应用强制主题的场景由 CSS 同步覆盖）。
function useSystemDark(): boolean {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setDark(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return dark;
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
  const dark = useSystemDark();
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
        const mermaid = await getMermaid(dark ? "dark" : "default");
        if (cancelled || seq !== renderSeq.current) return;
        // parse 抛错即语法错误；render 再画 svg
        await mermaid.parse(debouncedCode);
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
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [debouncedCode, dark]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const svgNode = useMemo(
    () => (svg ? <div dangerouslySetInnerHTML={{ __html: svg }} /> : null),
    [svg],
  );

  return (
    <div className="relative group my-3 rounded-lg border border-border overflow-hidden bg-background">
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
          className="flex items-center justify-center p-4 cursor-zoom-in"
          onClick={() => setZoomOpen(true)}
        >
          {svgNode}
        </div>
      ) : (
        <div className="p-4 text-xs text-muted-foreground">渲染中…</div>
      )}

      <Dialog open={zoomOpen} onOpenChange={setZoomOpen}>
        <DialogContent
          showCloseButton
          className="max-w-none w-screen h-screen p-0 bg-black/95 rounded-none border-none ring-0"
        >
          <div
            className="flex items-center justify-center w-full h-full p-8 overflow-auto"
            onClick={(e) => {
              if (e.target === e.currentTarget) setZoomOpen(false);
            }}
          >
            {svg ? (
              <div
                className="max-w-[90vw] max-h-[90vh]"
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
