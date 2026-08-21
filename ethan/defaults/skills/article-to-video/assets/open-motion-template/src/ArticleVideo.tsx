import React from "react";
import {
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "@open-motion/core";
import type {Scene, VideoTimeline, Visual, Theme} from "./types";
import {CAPTION_BOTTOM_PX, CAPTION_MIN_HEIGHT_PX, presenterLanePx, resolveLayout} from "./types";
import {CalloutLayer} from "./components/CalloutLayer";
import {CandlestickChart} from "./components/CandlestickChart";
import {PresenterLayer} from "./components/PresenterLayer";

// ⚠️ 帧驱动动画不变量：渲染器通过时间劫持 mock Date/rAF，CSS transition/animation
// 走墙钟不可控 —— 本文件及 components/ 下所有动画必须用 interpolate/spring/useCurrentFrame。

// Open Motion does not export AbsoluteFill — define inline
const AbsoluteFill: React.FC<{style?: React.CSSProperties; children?: React.ReactNode}> = ({style, children}) => (
  <div
    style={{
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: "100%",
      height: "100%",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      ...style,
    }}
  >
    {children}
  </div>
);

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};

// Simple LaTeX-like formula renderer for kinetic-text keywords
// Supports: ^{...}  _{...}  \times  \sqrt{...}  \cdot  \alpha-\omega  \sigma  etc.
// Also handles JSON escape corruption: \t→tab, \n→newline, etc.
const renderFormula = (text: string): React.ReactNode[] => {
  // Fix JSON escape corruption: \times → \times (tab char + imes → backslash + times)
  let fixed = text
    .replace(/\times/g, "\\times")   // \t (tab) + imes → \times
    .replace(/\tn/g, "\\tn")         // \t (tab) + n → \tn (not a real command, but preserve)
    .replace(/\r/g, "\\r")           // carriage return
    .replace(/\n/g, " ");            // newline → space

  const parts: React.ReactNode[] = [];
  let i = 0;
  while (i < fixed.length) {
    // Superscript: ^{...}  or ^X
    if (fixed[i] === "^") {
      if (fixed[i + 1] === "{") {
        const end = fixed.indexOf("}", i + 2);
        if (end !== -1) {
          parts.push(<sup key={i} style={{fontSize: "0.6em"}}>{renderFormula(fixed.slice(i + 2, end))}</sup>);
          i = end + 1;
          continue;
        }
      } else if (fixed[i + 1]) {
        parts.push(<sup key={i} style={{fontSize: "0.6em"}}>{fixed[i + 1]}</sup>);
        i += 2;
        continue;
      }
    }
    // Subscript: _{...}  or _X
    if (fixed[i] === "_") {
      if (fixed[i + 1] === "{") {
        const end = fixed.indexOf("}", i + 2);
        if (end !== -1) {
          parts.push(<sub key={i} style={{fontSize: "0.6em"}}>{renderFormula(fixed.slice(i + 2, end))}</sub>);
          i = end + 1;
          continue;
        }
      } else if (fixed[i + 1]) {
        parts.push(<sub key={i} style={{fontSize: "0.6em"}}>{fixed[i + 1]}</sub>);
        i += 2;
        continue;
      }
    }
    // LaTeX commands
    if (fixed[i] === "\\") {
      const rest = fixed.slice(i);
      // \command{arg} — match inner content allowing nested braces
      const cmdBrace = rest.match(/^\\([a-zA-Z]+)\{/);
      if (cmdBrace) {
        const cmd = cmdBrace[1];
        // Find matching closing brace (supports one level of nesting)
        let depth = 1;
        let j = i + cmdBrace[0].length;
        while (j < fixed.length && depth > 0) {
          if (fixed[j] === "{") depth++;
          if (fixed[j] === "}") depth--;
          j++;
        }
        const arg = fixed.slice(i + cmdBrace[0].length, j - 1);

        if (cmd === "sqrt") {
          // Render sqrt with continuous overline spanning all content
          parts.push(
            <span key={i} style={{fontStyle: "italic", display: "inline-flex", alignItems: "flex-end", position: "relative", whiteSpace: "nowrap"}}>
              <span style={{fontSize: "1.2em", marginRight: 1, alignSelf: "flex-start"}}>√</span>
              <span style={{borderTop: "2px solid currentColor", paddingLeft: 3, paddingRight: 3, display: "inline-block", minWidth: 30}}>
                {renderFormula(arg)}
              </span>
            </span>
          );
        } else if (cmd === "times") {
          parts.push(<span key={i}>×</span>);
        } else if (cmd === "cdot") {
          parts.push(<span key={i}>·</span>);
        } else if (cmd === "text") {
          parts.push(<span key={i} style={{fontStyle: "normal"}}>{arg}</span>);
        } else {
          parts.push(<span key={i} style={{fontStyle: "italic"}}>{renderFormula(arg)}</span>);
        }
        i = j;
        continue;
      }
      // Simple commands without braces
      const simpleCmd = rest.match(/^\\([a-zA-Z]+)/);
      if (simpleCmd) {
        const cmdMap: Record<string, string> = {
          times: "×", cdot: "·", sqrt: "√", alpha: "α", beta: "β", gamma: "γ",
          delta: "δ", sigma: "σ", omega: "ω", lambda: "λ", theta: "θ",
          pi: "π", phi: "φ", psi: "ψ", epsilon: "ε", mu: "μ",
          infty: "∞", partial: "∂", nabla: "∇", sum: "∑", prod: "∏",
          frac: "/", leq: "≤", geq: "≥", neq: "≠", approx: "≈",
          pm: "±", mp: "∓", cdots: "⋯", ldots: "…", vdots: "⋮",
          forall: "∀", exists: "∃", neg: "¬", land: "∧", lor: "∨",
          cup: "∪", cap: "∩", subset: "⊂", supset: "⊃", in: "∈",
          notin: "∉", rightarrow: "→", leftarrow: "←", Leftrightarrow: "⇔",
          Rightarrow: "⇒", Leftarrow: "⇐",
        };
        const sym = cmdMap[simpleCmd[1]];
        if (sym) {
          parts.push(<span key={i}>{sym}</span>);
          i += simpleCmd[0].length;
          continue;
        }
        parts.push(<span key={i} style={{fontStyle: "italic"}}>{`\\${simpleCmd[1]}`}</span>);
        i += simpleCmd[0].length;
        continue;
      }
    }
    // Default: plain text character
    parts.push(<span key={i}>{fixed[i]}</span>);
    i++;
  }
  return parts;
};

const panel: React.CSSProperties = {
  borderRadius: 42,
  padding: 52,
  border: "1px solid rgba(255,255,255,0.12)",
  boxShadow: "0 30px 100px rgba(0,0,0,0.35)",
  overflow: "hidden",
  wordBreak: "break-word" as const,
  maxWidth: "100%",
  boxSizing: "border-box" as const,
};

const VisualContent: React.FC<{
  visual: Visual;
  theme: Theme;
  sceneId: string;
  sceneFrames: number;
  withPresenter?: boolean;
}> = ({visual, theme, sceneId, sceneFrames, withPresenter = false}) => {
  const {primary, secondary, text} = theme;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 120}});
  const itemStyle = (index: number): React.CSSProperties => ({
    opacity: interpolate(frame, [index * 6, index * 6 + 10], [0, 1], clamp),
    transform: `translateY(${interpolate(frame, [index * 6, index * 6 + 12], [28, 0], clamp)}px)`,
  });

  if (visual.type === "candlestick") {
    return (
      <div style={{transform: `scale(${0.92 + enter * 0.08})`, opacity: enter}}>
        <CandlestickChart visual={visual} theme={theme} sceneId={sceneId} sceneFrames={sceneFrames} />
      </div>
    );
  }

  if (visual.type === "stat") {
    // Dynamically size stat value: shorter text → bigger font, longer text → smaller font
    // 无立绘：内容宽约 924px；有立绘：硬车道后内容列约 508px，字号整体降一档
    const valueLen = (visual.value || "").length;
    const statFontSize = withPresenter
      ? valueLen <= 4 ? 120 : valueLen <= 8 ? 96 : valueLen <= 12 ? 76 : valueLen <= 16 ? 60 : 46
      : valueLen <= 4 ? 170 : valueLen <= 8 ? 130 : valueLen <= 12 ? 100 : valueLen <= 16 ? 80 : 60;
    return (
      <div style={{textAlign: "center", transform: `scale(${0.86 + enter * 0.14})`, maxWidth: "100%"}}>
        <div style={{fontSize: statFontSize, lineHeight: 1, fontWeight: 900, color: primary, whiteSpace: "nowrap"}}>{visual.value}</div>
        <div style={{fontSize: withPresenter ? 34 : 42, marginTop: 28, color: text, opacity: 0.8}}>{visual.label}</div>
      </div>
    );
  }

  if (visual.type === "quote") {
    return (
      <div style={{...panel, background: "rgba(255,255,255,0.055)", transform: `scale(${0.94 + enter * 0.06})`}}>
        <div style={{fontSize: withPresenter ? 72 : 96, color: primary, lineHeight: 0.6}}>"</div>
        <div style={{fontSize: withPresenter ? 36 : 48, lineHeight: 1.45, fontWeight: 650, color: text}}>{visual.quote}</div>
        {visual.attribution ? <div style={{fontSize: withPresenter ? 26 : 30, marginTop: 30, color: secondary}}>— {visual.attribution}</div> : null}
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
            background: index === 0 ? `${primary}30` : "rgba(255,255,255,0.06)",
            borderLeft: index === 0 ? `4px solid ${primary}` : "4px solid transparent",
            color: index === 0 ? primary : (index % 2 === 1 ? secondary : text),
            fontSize: visual.type === "kinetic-text" ? (index === 0 ? 52 : 42) : 40,
            fontWeight: index === 0 ? 800 : 650,
            display: "flex",
            alignItems: "center",
            gap: 24,
          }}
        >
          {visual.type !== "kinetic-text" ? (
            <span style={{color: primary, minWidth: 52}}>{String(index + 1).padStart(2, "0")}</span>
          ) : null}
          <span>{visual.type === "kinetic-text" ? renderFormula(item) : item}</span>
        </div>
      ))}
    </div>
  );
};

const SceneView: React.FC<{scene: Scene; timeline: VideoTimeline; index: number}> = ({scene, timeline, index}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sceneFrames = Math.max(1, Math.ceil((scene.durationMs / 1000) * fps));
  const fade = interpolate(frame, [0, 9, Math.max(10, sceneFrames - 9), sceneFrames], [0, 1, 1, 0], clamp);
  const rise = interpolate(frame, [0, 18], [44, 0], clamp);
  const {theme} = timeline;
  // 有立绘时内容列让出立绘硬车道：车道侧 padding 加大到 边缘间距+车道宽+留白，
  // 车道内的立绘（CSS 双轴 contain，与姿势图宽高比无关）与内容列永不相交。
  // 布局几何单源在 video_pipeline.py（timeline.layout 注入），resolveLayout 负责回退。
  const layout = resolveLayout(timeline);
  const withPresenter = Boolean(timeline.presenter) && scene.presenter?.visible !== false;
  const lanePad = withPresenter
    ? layout.presenterEdgeInset + presenterLanePx(layout.presenterLaneWidth, timeline.presenter!.scale) + layout.presenterLaneGap
    : layout.contentSidePadding;
  const padLeft = withPresenter && timeline.presenter!.position === "left" ? lanePad : layout.contentSidePadding;
  const padRight = withPresenter && timeline.presenter!.position !== "left" ? lanePad : layout.contentSidePadding;

  return (
    <AbsoluteFill style={{opacity: fade, padding: `108px ${padRight}px 280px ${padLeft}px`, color: theme.text, overflow: "hidden", boxSizing: "border-box"}}>
      <div style={{fontSize: 25, letterSpacing: 5, color: theme.primary, fontWeight: 800}}>
        {String(index + 1).padStart(2, "0")} / {String(timeline.scenes.length).padStart(2, "0")}
      </div>
      <h1
        style={{
          fontSize: withPresenter ? 62 : 74,
          lineHeight: 1.12,
          margin: "34px 0 22px",
          transform: `translateY(${rise}px)`,
          maxWidth: withPresenter ? 620 : 920,
        }}
      >
        {scene.headline}
      </h1>
      {scene.body ? (
        <p style={{fontSize: withPresenter ? 30 : 34, lineHeight: 1.5, margin: 0, opacity: 0.72, maxWidth: withPresenter ? 620 : 900}}>
          {renderFormula(scene.body)}
        </p>
      ) : null}
      {scene.callouts && scene.callouts.length > 0 ? <CalloutLayer callouts={scene.callouts} theme={theme} /> : null}
      <div style={{flex: 1, display: "flex", alignItems: "center", justifyContent: withPresenter ? "flex-start" : "center", marginTop: 44, maxWidth: withPresenter ? 640 : undefined}}>
        <VisualContent visual={scene.visual} theme={theme} sceneId={scene.id} sceneFrames={sceneFrames} withPresenter={withPresenter} />
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
        background: `radial-gradient(circle at 15% 15%, ${theme.primary}40, transparent 35%), radial-gradient(circle at 90% 75%, ${theme.secondary}44, transparent 40%), ${theme.background}`,
        fontFamily: "Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif",
        overflow: "hidden",
      }}
    >
      <div style={{position: "absolute", top: 0, left: 0, height: 8, width: `${progress * 100}%`, background: `linear-gradient(90deg, ${theme.primary}, ${theme.secondary})`}} />
      {timeline.scenes.map((scene, index) => {
        const from = Math.round((scene.startMs / 1000) * timeline.fps);
        const durationInFrames = Math.max(1, Math.ceil((scene.durationMs / 1000) * timeline.fps));
        return (
          <Sequence key={scene.id} from={from} durationInFrames={durationInFrames}>
            <SceneView scene={scene} timeline={timeline} index={index} />
            {/* Audio assets collected by @open-motion/core into __OPEN_MOTION_AUDIO_ASSETS__
                renderFrames resolves src via publicDir. */}
            <Audio src={`/${scene.audio}`} />
          </Sequence>
        );
      })}
      {/* 虚拟人立绘：挂在根上（不进 Sequence），呼吸浮动跨场景连续；字幕之上、内容之下由 zIndex 控制 */}
      {timeline.presenter ? <PresenterLayer presenter={timeline.presenter} scenes={timeline.scenes} layout={resolveLayout(timeline)} /> : null}
      <div style={{position: "absolute", left: 58, right: 58, bottom: CAPTION_BOTTOM_PX, minHeight: CAPTION_MIN_HEIGHT_PX, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10}}>
        {caption ? (
          <div style={{background: "rgba(3,8,18,0.86)", border: "1px solid rgba(255,255,255,0.14)", borderRadius: 26, padding: "18px 30px", color: theme.text, fontSize: 32, lineHeight: 1.4, fontWeight: 600, textAlign: "center", maxWidth: "85%", boxShadow: "0 18px 60px rgba(0,0,0,0.4)"}}>
            {caption.text}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
