import { useState } from "react";
import { ExternalLink } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@ethan/shared/ui/sheet";

// 搜索结果卡片数据结构（web_search 工具产出）
export interface SearchResultCard {
  type: "search_result";
  title: string;
  url: string;
  snippet: string;
  engine: string;        // google/bing/duckduckgo/searxng/tavily/rss
  published: string;     // 新闻才有，如 "2024-01-01"
  source: string;        // RSS 来源（Google News/百度新闻）
}

interface SearchCardCarouselProps {
  cards: SearchResultCard[];
}

// 从 URL 中提取域名，失败则回退原 URL
function getHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

// 搜索结果横向滚动卡片：每张卡片点击后弹出 Sheet 展示完整详情
export function SearchCardCarousel({ cards }: SearchCardCarouselProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const current = openIndex != null ? cards[openIndex] : null;

  return (
    <>
      <div className="flex gap-2 overflow-x-auto pb-2">
        {cards.map((card, i) => (
          <button
            key={`${card.url}-${i}`}
            type="button"
            onClick={() => setOpenIndex(i)}
            className="text-left bg-muted/50 border border-border/50 rounded-lg p-3 min-w-[280px] max-w-[280px] flex-shrink-0 hover:bg-muted hover:border-border transition-colors cursor-pointer"
          >
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="inline-flex items-center rounded bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">
                {card.engine}
              </span>
              {card.source && (
                <span className="text-[10px] text-muted-foreground truncate">{card.source}</span>
              )}
            </div>
            <div className="text-sm font-medium line-clamp-2 leading-snug mb-1">
              {card.title}
            </div>
            <div className="text-xs text-muted-foreground line-clamp-3 leading-relaxed mb-1.5">
              {card.snippet}
            </div>
            <div className="text-[10px] text-muted-foreground/70 truncate">
              {getHostname(card.url)}
            </div>
          </button>
        ))}
      </div>

      <Sheet open={openIndex != null} onOpenChange={(o) => { if (!o) setOpenIndex(null); }}>
        <SheetContent side="right" className="sm:max-w-md">
          {current && (
            <>
              <SheetHeader>
                <SheetTitle className="leading-snug">{current.title}</SheetTitle>
                <SheetDescription className="truncate">
                  {getHostname(current.url)}
                </SheetDescription>
              </SheetHeader>
              <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-3 text-sm">
                {current.snippet && (
                  <div className="text-foreground/90 leading-relaxed whitespace-pre-wrap">
                    {current.snippet}
                  </div>
                )}
                <div className="space-y-1.5 text-xs text-muted-foreground border-t border-border/50 pt-3">
                  <div className="flex gap-2">
                    <span className="font-medium text-muted-foreground/80 shrink-0">引擎</span>
                    <span className="inline-flex items-center rounded bg-primary/10 text-primary px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide">
                      {current.engine}
                    </span>
                  </div>
                  {current.published && (
                    <div className="flex gap-2">
                      <span className="font-medium text-muted-foreground/80 shrink-0">发布</span>
                      <span>{current.published}</span>
                    </div>
                  )}
                  {current.source && (
                    <div className="flex gap-2">
                      <span className="font-medium text-muted-foreground/80 shrink-0">来源</span>
                      <span>{current.source}</span>
                    </div>
                  )}
                  <div className="flex gap-2">
                    <span className="font-medium text-muted-foreground/80 shrink-0">链接</span>
                    <a
                      href={current.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline break-all"
                    >
                      {current.url}
                    </a>
                  </div>
                </div>
                <a
                  href={current.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  打开链接
                </a>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
