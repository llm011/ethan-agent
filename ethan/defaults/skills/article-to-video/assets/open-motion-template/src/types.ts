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
  // accent/positive/negative 由 video_pipeline 的 DEFAULT_THEME 保证注入，不是可选
  accent: string;
  positive: string;
  negative: string;
};

// 姿势的面部变体（可选"活人感"素材）：blink = 闭眼帧，talk = 张嘴说话帧。
// pipeline 从 character.json 的 variants 注入；缺了退化为静态立绘（渐进增强）。
export type PoseVariants = {blink?: string; talk?: string};

// 虚拟人角色包（由 video_pipeline 从资产库解析后注入 timeline）
export type Presenter = {
  id: string;
  position: "right" | "left";
  scale: number;
  defaultPose: string;
  cutout: boolean;
  poses: Record<string, string>; // 姿势名 → public 相对路径（presenters/<id>/poses/<name>.png）
  variants?: Record<string, PoseVariants>; // 姿势名 → 变体路径（presenters/<id>/poses/<pose>-<variant>.png）
  // render.mjs stills 模式导出 clean-plate 时置 true：只藏立绘图层，
  // 不动 SceneView 的硬车道 padding —— 两张静帧的文字/数据位置才逐像素对齐。
  forceHidden?: boolean;
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
  layout?: Partial<PresenterLayout>;
  presenter?: Presenter;
  scenes: Scene[];
  captions: Caption[];
};

// tone 色板由 video_pipeline 的 DEFAULT_THEME 注入（金融主题 positive=红涨、
// negative=绿跌，A 股约定）。缺失说明时间线不是 pipeline 产物 —— 抛错好过静默用错颜色。
export const toneColor = (theme: Theme, tone: Tone): string => {
  const color = theme[tone];
  if (!color) {
    throw new Error(`timeline theme is missing "${tone}" (video_pipeline DEFAULT_THEME injects it)`);
  }
  return color;
};

// ── 立绘硬车道 ──
// presenter 可见时，立绘被 CSS 约束在屏幕边缘 ceil(laneWidth × scale) px 宽的车道内
// （img 宽/高双轴 100% + objectFit contain，与姿势图宽高比无关）；内容区按同一
// 宽度收 padding。两侧永不相交 —— 不遮挡是布局保证的，不靠作者小心。
//
// 单源在 video_pipeline.py：build_timeline 把这套几何注入 timeline.layout；
// 以下常量只作为旧时间线（无 layout 字段）的回退值，改动必须与 Python 侧同步。
export const PRESENTER_LANE_WIDTH = 440;
export const PRESENTER_LANE_GAP = 24; // 内容列与车道之间的留白
export const PRESENTER_EDGE_INSET = 30; // 车道距屏幕边缘的距离
export const CONTENT_SIDE_PADDING = 78; // 无立绘时内容列的左右 padding

// 字幕区几何：立绘底部 = 字幕 bottom + 字幕最小高度 + 两者之间留白（72+122+46=240）。
export const CAPTION_BOTTOM_PX = 72;
export const CAPTION_MIN_HEIGHT_PX = 122;
export const CAPTION_LANE_GAP_PX = 46;
export const PRESENTER_BOTTOM_PX = CAPTION_BOTTOM_PX + CAPTION_MIN_HEIGHT_PX + CAPTION_LANE_GAP_PX;

export type PresenterLayout = {
  presenterLaneWidth: number;
  presenterLaneGap: number;
  presenterEdgeInset: number;
  contentSidePadding: number;
};

// 布局解析：优先 timeline.layout（pipeline 注入），旧时间线回退到上面的同步常量。
export const resolveLayout = (timeline: {layout?: Partial<PresenterLayout>}): PresenterLayout => ({
  presenterLaneWidth: timeline.layout?.presenterLaneWidth ?? PRESENTER_LANE_WIDTH,
  presenterLaneGap: timeline.layout?.presenterLaneGap ?? PRESENTER_LANE_GAP,
  presenterEdgeInset: timeline.layout?.presenterEdgeInset ?? PRESENTER_EDGE_INSET,
  contentSidePadding: timeline.layout?.contentSidePadding ?? CONTENT_SIDE_PADDING,
});

export const presenterLanePx = (laneWidth: number, scale: number): number => Math.ceil(laneWidth * scale);
