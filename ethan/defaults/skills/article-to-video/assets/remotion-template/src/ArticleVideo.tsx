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
import type {Scene, Theme, VideoTimeline, Visual} from "./types";
import {Icon} from "./icons";

/* ── Helpers ─────────────────────────────────────────────── */

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;

/** Resolve the effective theme for a scene (scene override → global fallback). */
const useTheme = (scene: Scene, timeline: VideoTimeline): Theme =>
  scene.theme ? ({...timeline.theme, ...scene.theme} as Theme) : timeline.theme;

/** Map tone string to a theme color key. */
const toneColor = (tone: string | undefined, theme: Theme): string => {
  if (tone === "positive") return theme.positive;
  if (tone === "negative") return theme.negative;
  if (tone === "accent") return theme.accent;
  return theme.primary;
};

/** Parse numeric value from strings like "-15%", "92.7%", "3.5x". Returns NaN if none. */
const parseNumeric = (s: string): number => {
  const m = s.match(/-?[\d.]+/);
  return m ? parseFloat(m[0]) : NaN;
};

/** Extract non-numeric suffix from a string like "92.7%" → "%". */
const numericSuffix = (s: string): string => s.replace(/-?[\d.]+/, "");

/* ── Shared styles ───────────────────────────────────────── */

const panel = (surface: string): React.CSSProperties => ({
  borderRadius: 42,
  padding: 52,
  background: surface,
  border: "1px solid rgba(255,255,255,0.1)",
  boxShadow: "0 24px 80px rgba(0,0,0,0.3)",
});

const itemEntrance = (frame: number, index: number): React.CSSProperties => ({
  opacity: interpolate(frame, [index * 6, index * 6 + 10], [0, 1], clamp),
  transform: `translateY(${interpolate(frame, [index * 6, index * 6 + 12], [28, 0], clamp)}px)`,
});

/* ── Visual renderers ────────────────────────────────────── */

const VisualStat: React.FC<{visual: Extract<Visual, {type: "stat"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});
  const num = parseNumeric(visual.value);
  const suffix = numericSuffix(visual.value);
  const decimals = (visual.value.match(/\.(\d+)/) || ["", ""])[1].length;
  const display = isNaN(num)
    ? visual.value
    : `${Number(interpolate(frame, [0, 25], [0, num], clamp).toFixed(decimals))}${suffix}`;

  return (
    <div style={{textAlign: "center", transform: `scale(${0.86 + enter * 0.14})`}}>
      <div style={{position: "absolute", width: 320, height: 320, borderRadius: "50%", background: `${theme.primary}15`, filter: "blur(60px)", left: "50%", top: "50%", transform: "translate(-50%, -50%)"}} />
      <div style={{fontSize: 160, lineHeight: 1, fontWeight: 900, color: theme.primary, textShadow: `0 0 40px ${theme.primary}40`, position: "relative"}}>{display}</div>
      <div style={{fontSize: 40, marginTop: 28, color: theme.textMuted, fontWeight: 600, position: "relative"}}>{visual.label}</div>
    </div>
  );
};

const VisualQuote: React.FC<{visual: Extract<Visual, {type: "quote"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});

  return (
    <div style={{...panel(theme.surface), transform: `scale(${0.94 + enter * 0.06})`, borderLeft: `4px solid ${theme.accent}`}}>
      <div style={{fontSize: 96, color: theme.secondary, lineHeight: 0.6}}>&ldquo;</div>
      <div style={{fontSize: 46, lineHeight: 1.45, fontWeight: 650, color: theme.text, marginTop: 12}}>{visual.quote}</div>
      {visual.attribution ? <div style={{fontSize: 30, marginTop: 30, color: theme.textMuted, textAlign: "right"}}>— {visual.attribution}</div> : null}
    </div>
  );
};

const VisualKineticText: React.FC<{visual: Extract<Visual, {type: "kinetic-text"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const colors = [theme.primary, theme.secondary, theme.accent];

  return (
    <div style={{display: "flex", flexDirection: "column", gap: 20, width: "100%"}}>
      {visual.keywords.slice(0, 5).map((kw, i) => (
        <div
          key={`${kw}-${i}`}
          style={{
            ...panel(theme.surface),
            ...itemEntrance(frame, i),
            padding: "28px 38px",
            background: `${colors[i % colors.length]}18`,
            borderLeft: `4px solid ${colors[i % colors.length]}`,
            color: theme.text,
            fontSize: 52,
            fontWeight: 800,
            display: "flex",
            alignItems: "center",
            gap: 24,
          }}
        >
          <span style={{color: colors[i % colors.length], fontSize: 44}}>{kw}</span>
        </div>
      ))}
    </div>
  );
};

const VisualSteps: React.FC<{visual: Extract<Visual, {type: "steps"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();

  return (
    <div style={{display: "flex", flexDirection: "column", gap: 16, width: "100%", position: "relative"}}>
      <div style={{position: "absolute", left: 48, top: 30, bottom: 30, width: 2, background: `linear-gradient(${theme.primary}, ${theme.secondary})`, opacity: 0.3}} />
      {visual.items.slice(0, 5).map((item, i) => (
        <div
          key={`${item}-${i}`}
          style={{
            ...panel(theme.surface),
            ...itemEntrance(frame, i),
            padding: "22px 32px 22px 80px",
            display: "flex",
            alignItems: "center",
            gap: 18,
            position: "relative",
          }}
        >
          <div style={{position: "absolute", left: 24, width: 48, height: 48, borderRadius: 24, background: `linear-gradient(135deg, ${theme.primary}, ${theme.secondary})`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 22, fontWeight: 800}}>
            {i + 1}
          </div>
          <span style={{color: theme.text, fontSize: 38, fontWeight: 650, flex: 1}}>{item}</span>
        </div>
      ))}
    </div>
  );
};

const VisualSummary: React.FC<{visual: Extract<Visual, {type: "summary"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();

  return (
    <div style={{display: "flex", flexDirection: "column", gap: 18, width: "100%"}}>
      {visual.items.slice(0, 5).map((item, i) => (
        <div
          key={`${item}-${i}`}
          style={{
            ...panel(theme.surface),
            ...itemEntrance(frame, i),
            padding: "24px 34px",
            background: `${theme.accent}12`,
            display: "flex",
            alignItems: "center",
            gap: 20,
          }}
        >
          <div style={{width: 14, height: 14, borderRadius: 7, background: theme.accent, flexShrink: 0}} />
          <span style={{color: theme.text, fontSize: 38, fontWeight: 650}}>{item}</span>
        </div>
      ))}
    </div>
  );
};

const VisualIconCard: React.FC<{visual: Extract<Visual, {type: "icon-card"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 14, stiffness: 100}});

  return (
    <div style={{...panel(theme.surface), textAlign: "center", transform: `scale(${0.9 + enter * 0.1})`, borderTop: `3px solid ${theme.accent}`, maxWidth: 600, margin: "0 auto"}}>
      <div style={{marginBottom: 24, transform: `scale(${0.8 + enter * 0.2})`}}>
        <Icon name={visual.icon} size={72} color={theme.accent} />
      </div>
      <div style={{fontSize: 52, fontWeight: 800, color: theme.text, lineHeight: 1.2}}>{visual.title}</div>
      {visual.subtitle ? <div style={{fontSize: 34, color: theme.textMuted, marginTop: 16, lineHeight: 1.4}}>{visual.subtitle}</div> : null}
    </div>
  );
};

const VisualComparison: React.FC<{visual: Extract<Visual, {type: "comparison"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const renderSide = (data: {label: string; items: string[]; tone: string}, delay: number) => {
    const enter = spring({frame: Math.max(0, frame - delay), fps, config: {damping: 16, stiffness: 120}});
    const color = toneColor(data.tone, theme);
    return (
      <div style={{...panel(theme.surface), flex: 1, transform: `scale(${0.92 + enter * 0.08})`, borderTop: `3px solid ${color}`, opacity: interpolate(frame, [delay, delay + 10], [0, 1], clamp)}}>
        <div style={{fontSize: 36, fontWeight: 800, color, marginBottom: 18}}>{data.label}</div>
        {data.items.map((item, i) => (
          <div key={`${item}-${i}`} style={{...itemEntrance(frame, i + delay / 6), fontSize: 32, color: theme.text, padding: "10px 0", borderBottom: i < data.items.length - 1 ? `1px solid ${theme.text}15` : "none"}}>
            {item}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div style={{display: "flex", flexDirection: "column", gap: 20, width: "100%"}}>
      {renderSide(visual.left, 0)}
      <div style={{textAlign: "center", fontSize: 36, fontWeight: 800, color: theme.textMuted, opacity: 0.5, margin: "-4px 0"}}>VS</div>
      {renderSide(visual.right, 12)}
    </div>
  );
};

const VisualTimeline: React.FC<{visual: Extract<Visual, {type: "timeline"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <div style={{display: "flex", flexDirection: "column", gap: 14, width: "100%", position: "relative"}}>
      <div style={{position: "absolute", left: 23, top: 24, bottom: 24, width: 3, background: `linear-gradient(${theme.primary}, ${theme.secondary})`, opacity: 0.4, borderRadius: 2}} />
      {visual.items.slice(0, 6).map((item, i) => {
        const color = toneColor(item.tone, theme);
        const enter = spring({frame: Math.max(0, frame - i * 5), fps, config: {damping: 16, stiffness: 120}});
        return (
          <div key={`${item.label}-${i}`} style={{display: "flex", alignItems: "flex-start", gap: 20, ...itemEntrance(frame, i)}}>
            <div style={{width: 48, height: 48, borderRadius: 24, background: `${color}25`, border: `2px solid ${color}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transform: `scale(${0.8 + enter * 0.2})`}}>
              <div style={{width: 16, height: 16, borderRadius: 8, background: color}} />
            </div>
            <div style={{...panel(theme.surface), flex: 1, padding: "18px 28px", borderLeft: `3px solid ${color}`}}>
              <div style={{fontSize: 36, fontWeight: 700, color: theme.text}}>{item.label}</div>
              {item.description ? <div style={{fontSize: 28, color: theme.textMuted, marginTop: 6, lineHeight: 1.3}}>{item.description}</div> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
};

const VisualCallout: React.FC<{visual: Extract<Visual, {type: "callout"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 14, stiffness: 100}});
  const color = toneColor(visual.tone, theme);

  return (
    <div style={{...panel(theme.surface), textAlign: "center", transform: `scale(${0.92 + enter * 0.08})`, borderLeft: `5px solid ${color}`, maxWidth: 700, margin: "0 auto"}}>
      {visual.icon ? (
        <div style={{marginBottom: 20}}>
          <Icon name={visual.icon} size={64} color={color} />
        </div>
      ) : null}
      <div style={{fontSize: 46, fontWeight: 700, color: theme.text, lineHeight: 1.35}}>{visual.text}</div>
    </div>
  );
};

const VisualQuestion: React.FC<{visual: Extract<Visual, {type: "question"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 12, stiffness: 80}});

  return (
    <div style={{textAlign: "center", position: "relative", transform: `scale(${0.88 + enter * 0.12})`}}>
      <div style={{fontSize: 280, fontWeight: 900, color: theme.accent, opacity: 0.12, position: "absolute", left: "50%", top: "50%", transform: `translate(-50%, -55%) rotate(${interpolate(frame, [0, 20], [-8, 0], clamp)}deg)`}}>
        ?
      </div>
      <div style={{fontSize: 52, fontWeight: 800, color: theme.text, lineHeight: 1.3, position: "relative", maxWidth: 700, margin: "0 auto"}}>
        {visual.question}
      </div>
      {visual.hint ? (
        <div style={{fontSize: 34, color: theme.textMuted, marginTop: 28, position: "relative", opacity: interpolate(frame, [15, 25], [0, 1], clamp)}}>
          {visual.hint}
        </div>
      ) : null}
    </div>
  );
};

const VisualDefinition: React.FC<{visual: Extract<Visual, {type: "definition"}>; theme: Theme}> = ({visual, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});

  return (
    <div style={{...panel(theme.surface), transform: `scale(${0.92 + enter * 0.08})`, borderTop: `3px solid ${theme.accent}`, maxWidth: 700, margin: "0 auto"}}>
      <div style={{fontSize: 56, fontWeight: 800, color: theme.primary, marginBottom: 20}}>{visual.term}</div>
      <div style={{fontSize: 38, color: theme.text, lineHeight: 1.45, fontWeight: 500}}>{visual.definition}</div>
      {visual.example ? (
        <div style={{marginTop: 24, padding: "16px 24px", background: `${theme.accent}10`, borderRadius: 16, borderLeft: `3px solid ${theme.accent}`}}>
          <div style={{fontSize: 28, color: theme.textMuted, fontStyle: "italic"}}>💡 {visual.example}</div>
        </div>
      ) : null}
    </div>
  );
};

/* ── VisualContent dispatcher ────────────────────────────── */

const VisualContent: React.FC<{visual: Visual; theme: Theme}> = ({visual, theme}) => {
  switch (visual.type) {
    case "stat":
      return <VisualStat visual={visual} theme={theme} />;
    case "quote":
      return <VisualQuote visual={visual} theme={theme} />;
    case "kinetic-text":
      return <VisualKineticText visual={visual} theme={theme} />;
    case "steps":
      return <VisualSteps visual={visual} theme={theme} />;
    case "summary":
      return <VisualSummary visual={visual} theme={theme} />;
    case "icon-card":
      return <VisualIconCard visual={visual} theme={theme} />;
    case "comparison":
      return <VisualComparison visual={visual} theme={theme} />;
    case "timeline":
      return <VisualTimeline visual={visual} theme={theme} />;
    case "callout":
      return <VisualCallout visual={visual} theme={theme} />;
    case "question":
      return <VisualQuestion visual={visual} theme={theme} />;
    case "definition":
      return <VisualDefinition visual={visual} theme={theme} />;
  }
};

/* ── SceneView ───────────────────────────────────────────── */

const SceneView: React.FC<{scene: Scene; timeline: VideoTimeline; index: number}> = ({scene, timeline, index}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = useTheme(scene, timeline);
  const dur = (scene.durationMs / 1000) * fps;
  const fade = interpolate(frame, [0, 9, Math.max(10, dur - 9), dur], [0, 1, 1, 0], clamp);
  const rise = interpolate(frame, [0, 18], [44, 0], clamp);

  return (
    <AbsoluteFill style={{opacity: fade, padding: "108px 78px 280px", color: theme.text}}>
      <div style={{fontSize: 25, letterSpacing: 5, color: theme.secondary, fontWeight: 800}}>
        {String(index + 1).padStart(2, "0")} / {String(timeline.scenes.length).padStart(2, "0")}
      </div>
      <h1 style={{fontSize: 74, lineHeight: 1.12, margin: "34px 0 22px", transform: `translateY(${rise}px)`, maxWidth: 920, color: theme.primary}}>
        {scene.headline}
      </h1>
      {scene.body ? <p style={{fontSize: 34, lineHeight: 1.5, margin: 0, color: theme.textMuted, maxWidth: 900}}>{scene.body}</p> : null}
      <div style={{flex: 1, display: "flex", alignItems: "center", justifyContent: "center", marginTop: 44}}>
        <VisualContent visual={scene.visual} theme={theme} />
      </div>
    </AbsoluteFill>
  );
};

/* ── ArticleVideo (top-level) ────────────────────────────── */

export const ArticleVideo: React.FC<VideoTimeline> = (timeline) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const currentMs = (frame / fps) * 1000;
  const caption = timeline.captions.find((c) => currentMs >= c.startMs && currentMs < c.endMs);
  const progress = Math.min(1, currentMs / timeline.totalDurationMs);
  const {theme} = timeline;

  /* Animated background blobs */
  const blob1X = 15 + Math.sin(frame * 0.008) * 3;
  const blob1Y = 15 + Math.cos(frame * 0.01) * 3;
  const blob2X = 85 + Math.cos(frame * 0.006) * 4;
  const blob2Y = 75 + Math.sin(frame * 0.009) * 3;
  const bgAngle = interpolate(frame, [0, durationInFrames], [135, 145], clamp);

  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(${bgAngle}deg, ${theme.background}, ${theme.backgroundEnd || theme.background})`,
        fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif",
        overflow: "hidden",
      }}
    >
      {/* Animated radial glow — top-left */}
      <div style={{position: "absolute", width: "60%", height: "60%", left: `${blob1X}%`, top: `${blob1Y}%`, transform: "translate(-50%, -50%)", background: `radial-gradient(circle, ${theme.primary}20, transparent 60%)`, filter: "blur(40px)", pointerEvents: "none"}} />
      {/* Animated radial glow — bottom-right */}
      <div style={{position: "absolute", width: "50%", height: "50%", left: `${blob2X}%`, top: `${blob2Y}%`, transform: "translate(-50%, -50%)", background: `radial-gradient(circle, ${theme.secondary}18, transparent 60%)`, filter: "blur(50px)", pointerEvents: "none"}} />

      {/* Progress bar */}
      <div style={{position: "absolute", top: 0, left: 0, height: 6, width: `${progress * 100}%`, background: `linear-gradient(90deg, ${theme.primary}, ${theme.secondary})`, zIndex: 10}} />

      {/* Scenes */}
      {timeline.scenes.map((scene, index) => {
        const from = Math.round((scene.startMs / 1000) * timeline.fps);
        const dur = Math.max(1, Math.ceil((scene.durationMs / 1000) * timeline.fps));
        return (
          <Sequence key={scene.id} from={from} durationInFrames={dur} premountFor={timeline.fps}>
            <SceneView scene={scene} timeline={timeline} index={index} />
            <Audio src={staticFile(scene.audio)} />
          </Sequence>
        );
      })}

      {/* Caption bar */}
      <div style={{position: "absolute", left: 58, right: 58, bottom: 72, minHeight: 122, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 20}}>
        {caption ? (
          <div style={{background: `${theme.background}dd`, border: `1px solid ${theme.text}20`, borderRadius: 26, padding: "22px 34px", color: theme.text, fontSize: 38, lineHeight: 1.45, fontWeight: 700, textAlign: "center", boxShadow: `0 18px 60px ${theme.background}80`, backdropFilter: "blur(12px)"}}>
            {caption.text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
