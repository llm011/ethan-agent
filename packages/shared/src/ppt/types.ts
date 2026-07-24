// ppt-generate deck JSON 的宽松类型定义（与 references/schema.md 对应，预览用 best-effort）

export interface PptRun {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  sub?: boolean;
  sup?: boolean;
  fontSize?: number;
  color?: string;
  fontName?: string;
}

export interface PptParagraph {
  align?: "left" | "center" | "right" | "justify";
  lineHeight?: number;
  spaceBefore?: number;
  spaceAfter?: number;
  bullet?: false | "bullet" | "number";
  runs: PptRun[];
}

export interface PptOutline {
  style?: string;
  width?: number;
  color?: string;
}

export interface PptElement {
  id: string;
  type: "text" | "image" | "shape" | "line" | "chart" | "table" | "latex" | string;
  left?: number;
  top?: number;
  width?: number;
  height?: number;
  rotate?: number;
  opacity?: number;
  // text
  textType?: string;
  paragraphs?: PptParagraph[];
  vAlign?: "top" | "middle" | "bottom";
  inset?: [number, number, number, number];
  fill?: string | null;
  gradient?: { type?: string; rotate?: number; colors: { pos: number; color: string }[] } | null;
  outline?: PptOutline | null;
  vertical?: boolean;
  // image
  src?: string;
  fit?: "cover" | "contain" | "fill";
  radius?: number;
  flipH?: boolean;
  flipV?: boolean;
  // shape
  shape?: string;
  shadow?: { h?: number; v?: number; blur?: number; color?: string } | null;
  text?: { align?: "top" | "middle" | "bottom"; paragraphs: PptParagraph[] } | null;
  // line
  start?: [number, number];
  end?: [number, number];
  style?: "solid" | "dashed" | "dotted";
  color?: string;
  points?: [string, string];
  // chart
  chartType?: string;
  data?: { labels: string[]; legends?: string[]; series: number[][] };
  options?: { stack?: boolean; lineSmooth?: boolean };
  themeColors?: string[];
  // table
  colWidths?: number[];
  cellMinHeight?: number;
  theme?: { color?: string; rowHeader?: boolean };
  data_rows?: unknown;
  // latex
  latex?: string;
  fontSize?: number;
  align?: "left" | "center" | "right";
  // table data 实际在 data 字段（chart 也用 data，运行时判别）
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export interface PptSlideData {
  id: string;
  type?: string;
  background?:
    | { type: "solid"; color: string }
    | { type: "gradient"; gradient: { type?: string; rotate?: number; colors: { pos: number; color: string }[] } }
    | { type: "image"; image: { src: string; size?: string } };
  remark?: string;
  elements: PptElement[];
}

export interface PptTheme {
  backgroundColor?: string;
  themeColors?: string[];
  fontColor?: string;
  fontName?: string;
  latinFontName?: string;
  outline?: PptOutline;
  typography?: Record<string, { fontSize?: number; color?: string; bold?: boolean }>;
}

export const DEFAULT_THEME: Required<Pick<PptTheme, "backgroundColor" | "themeColors" | "fontColor" | "fontName">> & PptTheme = {
  backgroundColor: "#FFFFFF",
  themeColors: ["#1E40AF", "#3B82F6", "#93C5FD", "#F59E0B", "#10B981"],
  fontColor: "#1F2937",
  fontName: "Microsoft YaHei, PingFang SC, sans-serif",
  typography: {
    title: { fontSize: 28, color: "#111827", bold: true },
    subtitle: { fontSize: 16, color: "#4B5563" },
    content: { fontSize: 14 },
    item: { fontSize: 14 },
    itemTitle: { fontSize: 16, color: "#111827", bold: true },
    notes: { fontSize: 10, color: "#9CA3AF" },
    header: { fontSize: 10, color: "#6B7280" },
    footer: { fontSize: 10, color: "#6B7280" },
    partNumber: { fontSize: 60, bold: true },
    itemNumber: { fontSize: 16, bold: true },
  },
};

export const CANVAS_W = 1000;
export const CANVAS_H = 562.5;
