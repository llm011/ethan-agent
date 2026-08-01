// 阅读模式共享纯函数：标注类型、TOC 生成、阅读时间估算。
// 不依赖任何框架，桌面端（React）和插件端（content script）均可使用。
// 插件端因 Chrome 扩展限制不能 import shared 包，需复制本文件内容到插件目录。

// ========== 标注类型（与桌面端 HighlightSpan 对齐） ==========

export type AnnotationType = "highlight" | "underline" | "strike" | "comment" | "bookmark";
export type AnnotationColor = "yellow" | "blue" | "green" | "pink";

export interface AnnotationSpan {
  id: number;
  type: AnnotationType;
  color: AnnotationColor | null;
  start: number;
  end: number;
  quote?: string;
  note?: string | null;
}

// 标注类型 → 中文标签
export function annotationTypeLabel(t: AnnotationType): string {
  return (
    {
      highlight: "高亮",
      underline: "划线",
      strike: "删除线",
      comment: "批注",
      bookmark: "书签",
    } as Record<AnnotationType, string>
  )[t] ?? t;
}

// 标注颜色 → 背景色（oklch，与桌面端 reading-mode.tsx 对齐）
export function annotationColorBg(c: AnnotationColor | null): string {
  switch (c) {
    case "yellow":
      return "oklch(0.95 0.13 105 / 0.8)";
    case "blue":
      return "oklch(0.92 0.10 230 / 0.7)";
    case "green":
      return "oklch(0.94 0.12 150 / 0.7)";
    case "pink":
      return "oklch(0.93 0.11 350 / 0.7)";
    default:
      return "var(--muted-foreground)";
  }
}

// ========== TOC 生成 ==========

export interface TocItem {
  level: number;
  text: string;
  el: HTMLElement;
}

/**
 * 从正文根节点提取标题，生成 TOC。
 * 跳过空标题和过长标题（>80 字符，通常是误判）。
 */
export function generateToc(root: HTMLElement): TocItem[] {
  const items: TocItem[] = [];
  root.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((h) => {
    const el = h as HTMLElement;
    const text = el.textContent?.trim() || "";
    if (!text || text.length > 80) return;
    items.push({ level: parseInt(el.tagName[1]), text, el });
  });
  return items;
}

// ========== 阅读时间估算 ==========

/**
 * 按中文 400 字/分钟估算阅读时间（分钟）。
 * 中文阅读速度约 300-500 字/分钟，取中值 400。
 */
export function estimateReadTime(text: string): number {
  return Math.max(1, Math.ceil(text.length / 400));
}
