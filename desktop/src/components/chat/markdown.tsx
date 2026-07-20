import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "@ethan/shared/components/code-block";
import { PlainCodeBlock } from "@ethan/shared/components/plain-code-block";
import { forwardRef, useMemo, useState } from "react";
import { Lightbox, type LightboxImage } from "./lightbox";
import { openUrl } from "@/lib/external-link";
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

export const markdownComponents: Components = {
  code: ({ className, children }) => {
    const match = /language-(\w+)/.exec(className || "");
    const raw = String(children);
    if (match) {
      return <CodeBlock language={match[1]} code={raw.replace(/\n$/, "")} />;
    }
    if (raw.includes("\n")) {
      return <PlainCodeBlock code={raw.replace(/\n$/, "")} />;
    }
    return <code className="bg-background/50 px-1 py-0.5 rounded text-xs font-mono break-all">{children}</code>;
  },
  pre: ({ children }) => <>{children}</>,
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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
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
