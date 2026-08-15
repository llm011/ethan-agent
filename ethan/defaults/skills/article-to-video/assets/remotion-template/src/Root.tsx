import React from "react";
import {CalculateMetadataFunction, Composition} from "remotion";
import {ArticleVideo} from "./ArticleVideo";
import type {VideoTimeline} from "./types";

const defaults: VideoTimeline = {
  title: "Article to Video",
  summary: "",
  mode: "general",
  width: 1080,
  height: 1920,
  fps: 30,
  totalDurationMs: 3000,
  theme: {
    background: "#081120",
    surface: "#111D32",
    primary: "#6EE7F9",
    secondary: "#A78BFA",
    text: "#F8FAFC",
    accent: "#F59E0B",
    positive: "#10B981",
    negative: "#EF4444",
    textMuted: "#94A3B8",
    backgroundEnd: "#1a0a2e",
  },
  scenes: [],
  captions: [],
};

const calculateMetadata: CalculateMetadataFunction<VideoTimeline> = ({props}) => ({
  durationInFrames: Math.max(1, Math.ceil((props.totalDurationMs / 1000) * props.fps)),
  width: props.width,
  height: props.height,
  fps: props.fps,
  props,
  defaultCodec: "h264",
  defaultOutName: "final",
});

export const Root: React.FC = () => (
  <Composition
    id="ArticleVideo"
    component={ArticleVideo}
    durationInFrames={90}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={defaults}
    calculateMetadata={calculateMetadata}
  />
);
