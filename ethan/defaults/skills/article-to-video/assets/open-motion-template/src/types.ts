export type Visual = {
  type: "kinetic-text" | "steps" | "stat" | "quote" | "summary";
  keywords?: string[];
  items?: string[];
  value?: string;
  label?: string;
  quote?: string;
  attribution?: string;
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
};

export type VideoTimeline = {
  title: string;
  summary: string;
  width: number;
  height: number;
  fps: number;
  totalDurationMs: number;
  theme: Theme;
  scenes: Scene[];
  captions: Caption[];
};
