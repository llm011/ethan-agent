"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchDoc, resolveDocsImageUrl } from "@/lib/api";
import { DOC_NAV } from "@/lib/docs-nav";
import { CodeBlock } from "@ethan/shared/components/code-block";
import { PlainCodeBlock } from "@ethan/shared/components/plain-code-block";
import { Loader2, ChevronDown, ChevronRight } from "lucide-react";

interface TocItem {
  level: number;
  text: string;
  id: string;
}

interface DocsViewProps {
  initialSlug?: string;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^\w一-龥-]+/g, "")
    .replace(/^-+|-+$/g, "");
}

function extractToc(content: string): TocItem[] {
  const items: TocItem[] = [];
  let inFence = false;
  for (const line of content.split("\n")) {
    if (/^(`{3,}|~{3,})/.test(line.trimStart())) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const m = line.match(/^(#{1,3})\s+(.+)$/);
    if (m) {
      const text = m[2].trim();
      items.push({ level: m[1].length, text, id: slugify(text) });
    }
  }
  return items;
}

function makeHeading(
  tag: "h1" | "h2" | "h3" | "h4",
  className: string
) {
  return function HeadingComponent({ children }: { children?: React.ReactNode }) {
    const text = Array.isArray(children)
      ? children.map((c) => (typeof c === "string" ? c : "")).join("")
      : String(children ?? "");
    const id = slugify(text);
    const Tag = tag;
    return <Tag id={id} className={className}>{children}</Tag>;
  };
}

export function DocsView({ initialSlug }: DocsViewProps = {}) {
  const router = useRouter();
  const activeSlug = initialSlug || DOC_NAV[0]?.items[0]?.slug || "";
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [toc, setToc] = useState<TocItem[]>([]);
  const [activeId, setActiveId] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(DOC_NAV.map((g) => [g.group, true]))
  );
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activeSlug) return;
    setLoading(true);
    setContent("");
    setToc([]);
    setActiveId("");
    fetchDoc(activeSlug)
      .then((d) => {
        // strip HTML comments (diagram-source blocks) before rendering
        const stripped = d.content.replace(/<!--[\s\S]*?-->/g, "");
        setContent(stripped);
        setToc(extractToc(stripped));
      })
      .catch(() => setContent(""))
      .finally(() => setLoading(false));
  }, [activeSlug]);

  // track active heading on scroll
  const onScroll = useCallback(() => {
    if (!scrollRef.current) return;
    const container = scrollRef.current;
    const offset = container.getBoundingClientRect().top;
    const headings = container.querySelectorAll<HTMLElement>("h1,h2,h3");
    let current = "";
    for (const el of Array.from(headings)) {
      if (el.getBoundingClientRect().top - offset <= 32) {
        current = el.id;
      }
    }
    setActiveId(current);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [onScroll, content]);

  const scrollToId = (id: string) => {
    const el = scrollRef.current?.querySelector(`#${CSS.escape(id)}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const toggleGroup = (group: string) => {
    setExpandedGroups((prev) => ({ ...prev, [group]: !prev[group] }));
  };

  const navigate = (slug: string) => {
    router.push(`/docs/${slug}`);
  };

  return (
    <div className="flex h-full bg-background overflow-hidden">
      {/* Left nav */}
      <div className="w-56 border-r bg-muted/20 flex flex-col shrink-0 overflow-y-auto">
        <div className="p-4 border-b">
          <h2 className="font-semibold text-sm flex items-center gap-2">
            <Image src={`${process.env.NEXT_PUBLIC_BASE_PATH || ''}/logo-sidebar.png`} alt="Ethan Agent" width={20} height={20} className="rounded-full" />
            Ethan Agent
          </h2>
        </div>
        <nav className="flex-1 py-2">
          {DOC_NAV.map((group) => (
            <div key={group.group} className="mb-1">
              <button
                onClick={() => toggleGroup(group.group)}
                className="w-full flex items-center justify-between px-4 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <span>{group.group}</span>
                {expandedGroups[group.group] ? (
                  <ChevronDown className="h-3 w-3" />
                ) : (
                  <ChevronRight className="h-3 w-3" />
                )}
              </button>
              {expandedGroups[group.group] &&
                group.items.map((item) => (
                  <button
                    key={item.slug}
                    onClick={() => navigate(item.slug)}
                    className={`w-full text-left px-6 py-1.5 text-sm transition-colors border-l-2 ${
                      activeSlug === item.slug
                        ? "border-primary text-foreground font-medium bg-muted/40"
                        : "border-transparent text-muted-foreground hover:text-foreground hover:bg-muted/20"
                    }`}
                  >
                    {item.label}
                  </button>
                ))}
            </div>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : content ? (
          <div className="max-w-3xl mx-auto px-8 py-8">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: makeHeading("h1", "text-2xl font-bold mt-0 mb-4 pb-2 border-b border-border"),
                h2: makeHeading("h2", "text-xl font-semibold mt-8 mb-3"),
                h3: makeHeading("h3", "text-base font-semibold mt-5 mb-2"),
                h4: makeHeading("h4", "text-sm font-semibold mt-3 mb-1"),
                p: ({ children }) => <p className="my-2 leading-relaxed text-sm">{children}</p>,
                ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1 text-sm">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1 text-sm">{children}</ol>,
                li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                em: ({ children }) => <em className="italic">{children}</em>,
                code: ({ className, children }) => {
                  const match = /language-(\w+)/.exec(className || "");
                  const raw = String(children);
                  // fenced block with language → syntax highlighter
                  if (match) {
                    return (
                      <CodeBlock
                        language={match[1]}
                        code={raw.replace(/\n$/, "")}
                      />
                    );
                  }
                  // fenced block without language (has newline) → plain pre block
                  if (raw.includes("\n")) {
                    return <PlainCodeBlock code={raw.replace(/\n$/, "")} />;
                  }
                  // inline code
                  return (
                    <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">
                      {children}
                    </code>
                  );
                },
                pre: ({ children }) => <>{children}</>,
                blockquote: ({ children }) => (
                  <blockquote className="border-l-2 border-primary/40 pl-4 text-muted-foreground my-3 text-sm">
                    {children}
                  </blockquote>
                ),
                hr: () => <hr className="border-border my-6" />,
                a: ({ href, children }) => (
                  <a
                    href={href}
                    className="text-primary underline underline-offset-2 hover:opacity-80"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {children}
                  </a>
                ),
                table: ({ children }) => (
                  <div className="overflow-x-auto my-3">
                    <table className="text-sm w-full border-collapse">{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th className="border border-border px-3 py-1.5 bg-muted text-left font-medium">
                    {children}
                  </th>
                ),
                td: ({ children }) => (
                  <td className="border border-border px-3 py-1.5">{children}</td>
                ),
                img: ({ src, alt }) => {
                  const srcStr = typeof src === "string" ? src : "";
                  const resolved = resolveDocsImageUrl(srcStr);
                  return (
                    <img
                      src={resolved}
                      alt={alt ?? ""}
                      className="max-w-full rounded-lg my-4 border border-border"
                    />
                  );
                },
              }}
            >
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            文档即将完善
          </div>
        )}
      </div>

      {/* Right TOC */}
      {toc.length > 0 && (
        <div className="w-52 shrink-0 border-l bg-muted/10 overflow-y-auto hidden xl:block">
          <div className="p-4 pb-2">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              本页目录
            </p>
          </div>
          <nav className="px-3 pb-8">
            {toc.map((item, i) => (
              <button
                key={`${item.id}-${i}`}
                onClick={() => scrollToId(item.id)}
                className={`w-full text-left py-1 text-xs transition-colors rounded px-2 ${
                  item.level === 1 ? "" : item.level === 2 ? "pl-4" : "pl-7"
                } ${
                  activeId === item.id
                    ? "text-foreground font-medium bg-muted/60"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/30"
                }`}
              >
                {item.text}
              </button>
            ))}
          </nav>
        </div>
      )}
    </div>
  );
}
