"use client";

import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchDoc } from "@/lib/api";
import { DOC_NAV } from "@/lib/docs-nav";
import { Loader2, ChevronDown, ChevronRight } from "lucide-react";

interface DocsViewProps {
  initialSlug?: string;
}

export function DocsView({ initialSlug }: DocsViewProps = {}) {
  const [activeSlug, setActiveSlug] = useState(initialSlug || DOC_NAV[0]?.items[0]?.slug || "");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(DOC_NAV.map(g => [g.group, true]))
  );

  useEffect(() => {
    if (!activeSlug) return;
    setLoading(true);
    fetchDoc(activeSlug)
      .then(d => setContent(d.content))
      .catch(() => setContent(""))
      .finally(() => setLoading(false));
  }, [activeSlug]);

  const toggleGroup = (group: string) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  return (
    <div className="flex h-full bg-background overflow-hidden">
      {/* Sidebar */}
      <div className="w-56 border-r bg-muted/20 flex flex-col shrink-0 overflow-y-auto">
        <div className="p-4 border-b">
          <h2 className="font-semibold text-sm">文档</h2>
        </div>
        <nav className="flex-1 py-2">
          {DOC_NAV.map(group => (
            <div key={group.group} className="mb-1">
              <button
                onClick={() => toggleGroup(group.group)}
                className="w-full flex items-center justify-between px-4 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <span>{group.group}</span>
                {expandedGroups[group.group]
                  ? <ChevronDown className="h-3 w-3" />
                  : <ChevronRight className="h-3 w-3" />}
              </button>
              {expandedGroups[group.group] && group.items.map(item => (
                <button
                  key={item.slug}
                  onClick={() => setActiveSlug(item.slug)}
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
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : content ? (
          <div className="max-w-3xl mx-auto px-8 py-8">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => <h1 className="text-2xl font-bold mt-0 mb-4 pb-2 border-b border-border">{children}</h1>,
                h2: ({ children }) => <h2 className="text-xl font-semibold mt-8 mb-3">{children}</h2>,
                h3: ({ children }) => <h3 className="text-base font-semibold mt-5 mb-2">{children}</h3>,
                h4: ({ children }) => <h4 className="text-sm font-semibold mt-3 mb-1">{children}</h4>,
                p: ({ children }) => <p className="my-2 leading-relaxed text-sm">{children}</p>,
                ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1 text-sm">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1 text-sm">{children}</ol>,
                li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                em: ({ children }) => <em className="italic">{children}</em>,
                code: ({ className, children }) => {
                  const isBlock = !!className;
                  return isBlock
                    ? <code className={`${className} text-xs font-mono`}>{children}</code>
                    : <code className="bg-muted px-1.5 py-0.5 rounded text-xs font-mono">{children}</code>;
                },
                pre: ({ children }) => <pre className="bg-muted rounded-lg p-4 overflow-x-auto text-xs my-3 leading-relaxed">{children}</pre>,
                blockquote: ({ children }) => <blockquote className="border-l-2 border-primary/40 pl-4 text-muted-foreground my-3 text-sm">{children}</blockquote>,
                hr: () => <hr className="border-border my-6" />,
                a: ({ href, children }) => <a href={href} className="text-primary underline underline-offset-2 hover:opacity-80" target="_blank" rel="noopener noreferrer">{children}</a>,
                table: ({ children }) => <div className="overflow-x-auto my-3"><table className="text-sm w-full border-collapse">{children}</table></div>,
                th: ({ children }) => <th className="border border-border px-3 py-1.5 bg-muted text-left font-medium">{children}</th>,
                td: ({ children }) => <td className="border border-border px-3 py-1.5">{children}</td>,
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
    </div>
  );
}
