import React from "react";
import ReactDOM from "react-dom/client";
import { Composition, CompositionProvider } from "@open-motion/core";
import { ArticleVideo } from "./ArticleVideo";
import type { VideoTimeline } from "./types";

const defaults: VideoTimeline = {
  title: "Article to Video",
  summary: "",
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
    accent: "#FACC15",
    positive: "#EF4444",
    negative: "#22C55E",
  },
  scenes: [],
  captions: [],
};

const Root: React.FC = () => {
  const isRendering = typeof window !== "undefined" && typeof (window as any).__OPEN_MOTION_FRAME__ === "number";
  const frame = isRendering ? (window as any).__OPEN_MOTION_FRAME__ : 0;

  // During rendering: provide CompositionProvider context; during preview: show minimal UI
  if (isRendering) {
    const inputProps = (window as any).__OPEN_MOTION_INPUT_PROPS__ || defaults;
    const config = {
      width: inputProps.width || defaults.width,
      height: inputProps.height || defaults.height,
      fps: inputProps.fps || defaults.fps,
      durationInFrames: Math.max(1, Math.ceil(((inputProps.totalDurationMs || defaults.totalDurationMs) / 1000) * (inputProps.fps || defaults.fps))),
    };

    return (
      <CompositionProvider config={config} frame={frame} inputProps={inputProps}>
        <ArticleVideo {...inputProps} />
      </CompositionProvider>
    );
  }

  // Dev/preview mode: just register the composition for discoverability
  return (
    <>
      <Composition
        id="ArticleVideo"
        component={ArticleVideo}
        durationInFrames={90}
        fps={30}
        width={defaults.width || 1080}
        height={defaults.height || 1920}
        defaultProps={defaults}
        calculateMetadata={({ props }) => ({
          durationInFrames: Math.max(1, Math.ceil((props.totalDurationMs / 1000) * props.fps)),
          width: props.width,
          height: props.height,
          fps: props.fps,
        })}
      />
      <div style={{ padding: 40, fontFamily: "system-ui, sans-serif" }}>
        <p>Open Motion preview — run <code>node render.mjs</code> to produce the final video.</p>
      </div>
    </>
  );
};

ReactDOM.createRoot(document.getElementById("root")!).render(<Root />);
