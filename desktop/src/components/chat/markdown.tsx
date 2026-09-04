import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import "katex/dist/katex.min.css";
import { CodeBlock } from "@ethan/shared/components/code-block";
import { PlainCodeBlock } from "@ethan/shared/components/plain-code-block";
import { MermaidBlock } from "@ethan/shared/components/mermaid-block";
import { forwardRef, useMemo, useState, useEffect } from "react";
import { Lightbox, type LightboxImage } from "./lightbox";
import { openUrl } from "@/lib/external-link";

let _katex: typeof import("katex").default | undefined;
let _katexLoading: Promise<void> | undefined;
function loadKatex() {
  if (!_katexLoading) {
    _katexLoading = import("katex").then(m => { _katex = m.default; });
  }
  return _katexLoading;
}
// CommonMark 规定 ** 紧内侧不能有空格，否则不渲染加粗。
// 此函数去掉 AI 生成文本中 ** 内侧的多余空白，修复渲染。
// 气泡与阅读模式都必须经过此函数，保证「渲染后的纯文本」字符序列一致，
// 这样按字符偏移存储的标注在两边都能精确回显。
export function fixBold(text: string): string {
  return text.replace(/\*\*[ \t]*((?:[^*\n]|\*(?!\*))+?)[ \t]*\*\*/g, (_, inner) => {
    const trimmed = inner.trim();
    return trimmed ? `**${trimmed}**` : `**${inner}**`;
  });
}

// ---- 数学公式渲染 ----
// LLM 常输出 $$...$$ / $...$ 包裹的 LaTeX（如 $$\text{¥94.59}+...$$），此前只会原样
// 漏出。这里用轻量 remark 插件把 text 节点里的公式拆成 span 元素，交给 KaTeX 真渲染
// （代码块/行内 code 是独立 mdast 节点，天然不受影响）。
// 标注偏移基于渲染后纯文本（highlight.ts 的 TreeWalker），KaTeX html 输出的 text 节点
// 仍可被遍历，且气泡与阅读模式共用本组件，两端 DOM 保持一致。

// $$...$$ 总是公式；单 $...$ 常见于货币（"价格 $5 和 $9"），仅当内容含 LaTeX 命令
// 特征（反斜杠/上下标）时才按公式处理，避免货币被误渲染。
const MATH_RE = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;

/* eslint-disable @typescript-eslint/no-explicit-any */
function remarkMath(): (tree: any) => void {
  // 把一个 text 节点拆成 [text, inlineMath, text, ...]；无公式时返回 null
  const split = (value: string): any[] | null => {
    if (!value.includes("$")) return null;
    const out: any[] = [];
    let last = 0;
    let m: RegExpExecArray | null;
    MATH_RE.lastIndex = 0;
    while ((m = MATH_RE.exec(value)) !== null) {
      const isDisplayDollar = m[1] !== undefined;
      const latex = (isDisplayDollar ? m[1] : m[2]).trim();
      // 非公式（如货币 $50）不能吞掉右侧 $：回退 lastIndex，让该 $ 可作为
      // 后续公式（如 $x^2$）的起始定界符，否则紧随其后的公式会漏渲染
      if (!latex || (!isDisplayDollar && !/[\\^_]/.test(latex))) {
        MATH_RE.lastIndex = m.index + (isDisplayDollar ? 2 : 1);
        continue;
      }
      // $$...$$ 夹在其他文字中间（如行内合计式）按行内渲染；独占段落才用 display 模式
      const alone =
        value.slice(0, m.index).trim() === "" && value.slice(m.index + m[0].length).trim() === "";
      const display = isDisplayDollar && alone;
      if (m.index > last) out.push({ type: "text", value: value.slice(last, m.index) });
      out.push({
        type: "inlineMath",
        data: {
          hName: "span",
          hProperties: { className: [display ? "math-block" : "math-inline"], "data-latex": latex },
        },
      });
      last = m.index + m[0].length;
    }
    if (last === 0) return null;
    out.push({ type: "text", value: value.slice(last) });
    return out;
  };

  return (tree) => {
    const walk = (node: any) => {
      if (!node || !Array.isArray(node.children)) return;
      const next: any[] = [];
      for (const child of node.children) {
        if (child?.type === "text" && typeof child.value === "string") {
          const parts = split(child.value);
          if (parts) {
            next.push(...parts);
            continue;
          }
        }
        walk(child);
        next.push(child);
      }
      node.children = next;
    };
    walk(tree);
  };
}

function MathSpan({ latex, display }: { latex: string; display: boolean }) {
  const [ready, setReady] = useState(!!_katex);
  useEffect(() => {
    if (!_katex) loadKatex().then(() => setReady(true));
  }, []);
  const html = useMemo(() => {
    if (!_katex) return null;
    try {
      return _katex.renderToString(latex, { displayMode: display, throwOnError: false, output: "html" });
    } catch {
      return null;
    }
  }, [latex, display, ready]);
  if (!html) return <code className="bg-background/50 px-1 py-0.5 rounded text-xs font-mono">{latex}</code>;
  // display 时 KaTeX 自带 katex-display 样式（居中块级），外层 span 仅作挂载点
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}


export const markdownComponents: Components = {
  code: ({ className, children }) => {
    const match = /language-(\w+)/.exec(className || "");
    const raw = String(children);
    const lang = match?.[1] || "";
    if (lang === "mermaid") {
      return <MermaidBlock code={raw.replace(/\n$/, "")} />;
    }
    if (match) {
      return <CodeBlock language={lang} code={raw.replace(/\n$/, "")} />;
    }
    if (raw.includes("\n")) {
      return <PlainCodeBlock code={raw.replace(/\n$/, "")} />;
    }
    return <code className="bg-background/50 px-1 py-0.5 rounded text-xs font-mono break-all">{children}</code>;
  },
  pre: ({ children }) => <>{children}</>,
  span: ({ className, children, ...rest }) => {
    const cls = String(className || "");
    if (cls.includes("math-inline") || cls.includes("math-block")) {
      const latex = String((rest as Record<string, unknown>)["data-latex"] || "");
      return <MathSpan latex={latex} display={cls.includes("math-block")} />;
    }
    return <span className={className}>{children}</span>;
  },
  table: ({ children }) => (
    <div className="table-wrapper">
      <table>{children}</table>
    </div>
  ),
  // 桌面端 webview 内部点击外链会被顶走（回不去），所有 http(s)/mailto 链接
  // 都改走系统默认浏览器打开。锚点链接（#xxx）保持默认行为。
  a: ({ href, children }) => (
    <a
      href={href}
      className="text-primary underline underline-offset-2 hover:opacity-80 cursor-pointer"
      onClick={(e) => {
        if (!href || href.startsWith("#")) return;
        e.preventDefault();
        openUrl(href);
      }}
    >
      {children}
    </a>
  ),
};

// 气泡与阅读模式共用同一个渲染入口，确保 DOM 文本节点序列完全一致，
// 标注偏移（基于渲染后纯文本）在两边才能对齐。
export const MarkdownContent = forwardRef<
  HTMLDivElement,
  { content: string; className?: string; variant?: "bubble" | "share" }
>(({ content, className, variant = "bubble" }, ref) => {
  // markdown 中 <img> 点击放大所需的内部状态
  const [lightboxImages, setLightboxImages] = useState<LightboxImage[]>([]);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [lightboxOpen, setLightboxOpen] = useState(false);

  // 合并默认 components 与 img 处理；img 点击打开 Lightbox 显示大图
  const components = useMemo<Components>(() => ({
    ...markdownComponents,
    img: ({ src, alt }) => {
      const url = String(src || "");
      return (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt={alt || ""}
          className="cursor-zoom-in max-h-96 rounded-lg"
          onClick={() => {
            setLightboxImages([{ url, title: alt || "" }]);
            setLightboxIndex(0);
            setLightboxOpen(true);
          }}
        />
      );
    },
  }), []);

  // 缓存 markdown 解析结果：content 不变时不重新解析（react-markdown 解析是同步阻塞主线程的昂贵操作）
  const parsed = useMemo(
    () => (
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath as never]} components={components}>
        {fixBold(content)}
      </ReactMarkdown>
    ),
    [content, components],
  );

  return (
    <div
      ref={ref}
      className={
        variant === "share"
          ? `share-prose ${className ?? ""}`
          : `prose prose-sm dark:prose-invert max-w-none ${className ?? ""}`
      }
    >
      {parsed}
      <Lightbox
        images={lightboxImages}
        index={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />
    </div>
  );
});
MarkdownContent.displayName = "MarkdownContent";
