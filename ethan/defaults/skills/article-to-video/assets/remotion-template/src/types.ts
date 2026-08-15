export type VisualType =
  | "kinetic-text"
  | "steps"
  | "stat"
  | "quote"
  | "summary"
  | "icon-card"
  | "comparison"
  | "timeline"
  | "callout"
  | "question"
  | "definition";

export type ComparisonSide = {
  label: string;
  items: string[];
  tone: "positive" | "negative" | "neutral";
};

export type TimelineItem = {
  label: string;
  description: string;
  tone: "positive" | "negative" | "neutral";
};

export type ToneColor = "positive" | "negative" | "neutral" | "accent";

export type Visual =
  | { type: "kinetic-text"; keywords: string[] }
  | { type: "steps"; items: string[] }
  | { type: "stat"; value: string; label: string }
  | { type: "quote"; quote: string; attribution: string }
  | { type: "summary"; items: string[] }
  | { type: "icon-card"; icon: string; title: string; subtitle: string }
  | { type: "comparison"; left: ComparisonSide; right: ComparisonSide }
  | { type: "timeline"; items: TimelineItem[] }
  | { type: "callout"; text: string; tone: ToneColor; icon: string }
  | { type: "question"; question: string; hint: string }
  | { type: "definition"; term: string; definition: string; example: string };

export type Theme = {
  background: string;
  surface: string;
  primary: string;
  secondary: string;
  text: string;
  accent: string;
  positive: string;
  negative: string;
  textMuted: string;
  backgroundEnd: string;
};

export type Scene = {
  id: string;
  headline: string;
  body: string;
  narration: string;
  audio: string;
  startMs: number;
  durationMs: number;
  visual: Visual;
  theme?: Partial<Theme>;
};

export type Caption = {
  text: string;
  startMs: number;
  endMs: number;
};

export type VideoTimeline = {
  title: string;
  summary: string;
  mode: string;
  width: number;
  height: number;
  fps: number;
  totalDurationMs: number;
  theme: Theme;
  scenes: Scene[];
  captions: Caption[];
};
