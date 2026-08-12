import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {Scene, VideoTimeline, Visual} from "./types";

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;

const panel: React.CSSProperties = {
  borderRadius: 42,
  padding: 52,
  border: "1px solid rgba(255,255,255,0.12)",
  boxShadow: "0 30px 100px rgba(0,0,0,0.35)",
};

const VisualContent: React.FC<{visual: Visual; primary: string; secondary: string; text: string}> = ({
  visual,
  primary,
  secondary,
  text,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});
  const itemStyle = (index: number): React.CSSProperties => ({
    opacity: interpolate(frame, [index * 6, index * 6 + 10], [0, 1], clamp),
    transform: `translateY(${interpolate(frame, [index * 6, index * 6 + 12], [28, 0], clamp)}px)`,
  });

  if (visual.type === "stat") {
    return (
      <div style={{textAlign: "center", transform: `scale(${0.86 + enter * 0.14})`}}>
        <div style={{fontSize: 170, lineHeight: 1, fontWeight: 900, color: primary}}>{visual.value}</div>
        <div style={{fontSize: 42, marginTop: 28, color: text, opacity: 0.8}}>{visual.label}</div>
      </div>
    );
  }

  if (visual.type === "quote") {
    return (
      <div style={{...panel, background: "rgba(255,255,255,0.055)", transform: `scale(${0.94 + enter * 0.06})`}}>
        <div style={{fontSize: 96, color: primary, lineHeight: 0.6}}>“</div>
        <div style={{fontSize: 48, lineHeight: 1.45, fontWeight: 650, color: text}}>{visual.quote}</div>
        {visual.attribution ? <div style={{fontSize: 30, marginTop: 30, color: secondary}}>— {visual.attribution}</div> : null}
      </div>
    );
  }

  const items = visual.type === "kinetic-text" ? visual.keywords ?? [] : visual.items ?? [];
  return (
    <div style={{display: "flex", flexDirection: "column", gap: 22, width: "100%"}}>
      {items.slice(0, 5).map((item, index) => (
        <div
          key={`${item}-${index}`}
          style={{
            ...panel,
            ...itemStyle(index),
            padding: "28px 38px",
            background: index === 0 ? `${primary}22` : "rgba(255,255,255,0.05)",
            color: text,
            fontSize: visual.type === "kinetic-text" ? 52 : 40,
            fontWeight: index === 0 ? 800 : 650,
            display: "flex",
            alignItems: "center",
            gap: 24,
          }}
        >
          {visual.type !== "kinetic-text" ? (
            <span style={{color: primary, minWidth: 52}}>{String(index + 1).padStart(2, "0")}</span>
          ) : null}
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
};

const SceneView: React.FC<{scene: Scene; timeline: VideoTimeline; index: number}> = ({scene, timeline, index}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const fade = interpolate(frame, [0, 9, Math.max(10, (scene.durationMs / 1000) * fps - 9), (scene.durationMs / 1000) * fps], [0, 1, 1, 0], clamp);
  const rise = interpolate(frame, [0, 18], [44, 0], clamp);
  const {theme} = timeline;

  return (
    <AbsoluteFill style={{opacity: fade, padding: "108px 78px 280px", color: theme.text}}>
      <div style={{fontSize: 25, letterSpacing: 5, color: theme.primary, fontWeight: 800}}>
        {String(index + 1).padStart(2, "0")} / {String(timeline.scenes.length).padStart(2, "0")}
      </div>
      <h1 style={{fontSize: 74, lineHeight: 1.12, margin: "34px 0 22px", transform: `translateY(${rise}px)`, maxWidth: 920}}>
        {scene.headline}
      </h1>
      {scene.body ? <p style={{fontSize: 34, lineHeight: 1.5, margin: 0, opacity: 0.72, maxWidth: 900}}>{scene.body}</p> : null}
      <div style={{flex: 1, display: "flex", alignItems: "center", justifyContent: "center", marginTop: 44}}>
        <VisualContent visual={scene.visual} primary={theme.primary} secondary={theme.secondary} text={theme.text} />
      </div>
    </AbsoluteFill>
  );
};

export const ArticleVideo: React.FC<VideoTimeline> = (timeline) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const currentMs = (frame / fps) * 1000;
  const caption = timeline.captions.find((item) => currentMs >= item.startMs && currentMs < item.endMs);
  const progress = Math.min(1, currentMs / timeline.totalDurationMs);
  const {theme} = timeline;

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 15% 15%, ${theme.primary}22, transparent 35%), radial-gradient(circle at 90% 75%, ${theme.secondary}24, transparent 40%), ${theme.background}`,
        fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif",
        overflow: "hidden",
      }}
    >
      <div style={{position: "absolute", top: 0, left: 0, height: 8, width: `${progress * 100}%`, background: `linear-gradient(90deg, ${theme.primary}, ${theme.secondary})`}} />
      {timeline.scenes.map((scene, index) => {
        const from = Math.round((scene.startMs / 1000) * timeline.fps);
        const durationInFrames = Math.max(1, Math.ceil((scene.durationMs / 1000) * timeline.fps));
        return (
          <Sequence key={scene.id} from={from} durationInFrames={durationInFrames} premountFor={timeline.fps}>
            <SceneView scene={scene} timeline={timeline} index={index} />
            <Audio src={staticFile(scene.audio)} />
          </Sequence>
        );
      })}
      <div style={{position: "absolute", left: 58, right: 58, bottom: 72, minHeight: 122, display: "flex", alignItems: "center", justifyContent: "center"}}>
        {caption ? (
          <div style={{background: "rgba(3,8,18,0.86)", border: "1px solid rgba(255,255,255,0.14)", borderRadius: 26, padding: "22px 34px", color: theme.text, fontSize: 38, lineHeight: 1.45, fontWeight: 700, textAlign: "center", boxShadow: "0 18px 60px rgba(0,0,0,0.4)"}}>
            {caption.text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
