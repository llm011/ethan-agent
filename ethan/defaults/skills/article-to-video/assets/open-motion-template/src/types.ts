export type Tone = "accent" | "positive" | "negative";

export type Candle = {o: number; h: number; l: number; c: number};

export type CandleMarker = {
  index: number;
  label: string;
  tone: Tone;
  position: "above" | "below";
};

export type Visual = {
  type: "kinetic-text" | "steps" | "stat" | "quote" | "summary" | "candlestick";
  keywords?: string[];
  items?: string[];
  value?: string;
  label?: string;
  quote?: string;
  attribution?: string;
  // candlestick
  closes?: number[];
  candles?: Candle[];
  bands?: {upper?: number[]; middle?: number[]; lower?: number[]};
  markers?: CandleMarker[];
};

export type Callout = {text: string; tone: Tone};

export type ScenePresenter = {pose?: string | null; visible?: boolean};

export type Scene = {
  id: string;
  headline: string;
  body: string;
  narration: string;
  audio: string;
  startMs: number;
  durationMs: number;
  visual: Visual;
  callouts?: Callout[];
  presenter?: ScenePresenter;
};

export type Caption = {
  text: string;
  startMs: number;
  endMs: number;
};

export type Theme = {
  background: string;
  surface: string;
  primary: string;
  secondary: string;
  text: string;
  accent?: string;
  positive?: string;
  negative?: string;
};

// 虚拟人角色包（由 video_pipeline 从资产库解析后注入 timeline）
export type Presenter = {
  id: string;
  position: "right" | "left";
  scale: number;
  defaultPose: string;
  cutout: boolean;
  poses: Record<string, string>; // 姿势名 → public 相对路径（presenters/<id>/poses/<name>.png）
};

export type VideoTimeline = {
  title: string;
  summary: string;
  width: number;
  height: number;
  fps: number;
  totalDurationMs: number;
  domain?: "general" | "finance" | "paper";
  theme: Theme;
  presenter?: Presenter;
  scenes: Scene[];
  captions: Caption[];
};

// tone 色板回退：金融主题里 positive=红（涨）、negative=绿（跌）（A 股约定）。
export const toneColor = (theme: Theme, tone: Tone): string =>
  tone === "accent"
    ? theme.accent ?? "#FACC15"
    : tone === "positive"
      ? theme.positive ?? "#EF4444"
      : theme.negative ?? "#22C55E";

// ── 立绘硬车道 ──
// presenter 可见时，立绘被 CSS 约束在屏幕边缘 ceil(LANE × scale) px 宽的车道内
// （img 宽/高双轴 100% + objectFit contain，与姿势图宽高比无关）；内容区按同一
// 宽度收 padding。两侧永不相交 —— 不遮挡是布局保证的，不靠作者小心。
export const PRESENTER_LANE_WIDTH = 440;
export const PRESENTER_LANE_GAP = 24; // 内容列与车道之间的留白
export const PRESENTER_EDGE_INSET = 30; // 车道距屏幕边缘的距离（与 PresenterLayer 的 left/right 一致）
export const presenterLanePx = (scale: number): number => Math.ceil(PRESENTER_LANE_WIDTH * scale);
