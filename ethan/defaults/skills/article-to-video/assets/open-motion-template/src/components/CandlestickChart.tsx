import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "@open-motion/core";
import type {Candle, Theme, Visual} from "../types";
import {toneColor} from "../types";

const clamp = {extrapolateLeft: "clamp" as const, extrapolateRight: "clamp" as const};

// 确定性伪随机（mulberry32）：由场景 id 做种子，同一 manifest 重渲染产出完全相同的帧。
const seedFrom = (text: string): number => {
  let hash = 2166136261;
  for (const ch of text) {
    hash ^= ch.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
};

const mulberry32 = (seed: number) => {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
};

// closes → 合成 OHLC：开盘取前收（首根在前收附近抖动），上下影按整体波幅比例抖动。
const synthesizeCandles = (closes: number[], sceneId: string): Candle[] => {
  const rand = mulberry32(seedFrom(sceneId));
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = Math.max(1e-9, max - min);
  return closes.map((close, index) => {
    const open = index > 0 ? closes[index - 1] : close * (0.99 + rand() * 0.02);
    const high = Math.max(open, close) + rand() * range * 0.008;
    const low = Math.min(open, close) - rand() * range * 0.008;
    return {o: open, h: high, l: low, c: close};
  });
};

const formatPrice = (value: number): string =>
  Math.abs(value) >= 10000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(Math.abs(value) < 10 ? 2 : 1);

// 估算 marker 文本宽度（CJK≈1em，ASCII≈0.56em），把芯片加宽到能容纳文字。
// 不做 DOM measure，保持帧驱动确定性。
const labelWidthPx = (label: string, fontSize: number): number => {
  let width = 0;
  for (const ch of label) {
    width += /[⺀-鿿　-〿＀-￯—–]/.test(ch) ? fontSize : fontSize * 0.56;
  }
  return width;
};

const W = 920;
const H = 640;
// 上下 padding 必须容得下一个完整 marker 芯片（38 高 + 引线间距），
// 否则标注打在最高/最低蜡烛上时会被 SVG 视口裁掉。
const PAD_X = 18;
const PAD_TOP = 68;
const PAD_BOTTOM = 72;

export const CandlestickChart: React.FC<{
  visual: Visual;
  theme: Theme;
  sceneId: string;
  sceneFrames: number;
}> = ({visual, theme, sceneId, sceneFrames}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const candles = visual.candles ?? synthesizeCandles(visual.closes ?? [], sceneId);
  const n = Math.max(1, candles.length);

  const lows = candles.map((c) => c.l);
  const highs = candles.map((c) => c.h);
  for (const band of Object.values(visual.bands ?? {})) {
    lows.push(...band);
    highs.push(...band);
  }
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const pad = (max - min) * 0.06 || 1e-9;
  const y = (value: number) => PAD_TOP + (1 - (value - (min - pad)) / (max - min + 2 * pad)) * (H - PAD_TOP - PAD_BOTTOM);
  const stepX = (W - PAD_X * 2) / n;
  const cx = (index: number) => PAD_X + index * stepX + stepX / 2;
  const bodyW = Math.max(3, stepX * 0.62);

  const upColor = toneColor(theme, "positive"); // 红涨
  const downColor = toneColor(theme, "negative"); // 绿跌

  // 揭示动画：左到右擦除，占场景前 40% 帧；clipPath 宽度即已揭示区域。
  const revealFrames = Math.max(12, Math.round(sceneFrames * 0.4));
  const reveal = interpolate(frame, [0, revealFrames], [0, W], clamp);
  const revealFrameAt = (index: number) => ((index + 0.5) / n) * revealFrames;

  const gridValues = Array.from({length: 4}, (_, i) => min - pad + ((max - min + 2 * pad) * (i + 0.5)) / 4);

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{maxWidth: "100%"}}>
      <defs>
        <clipPath id={`reveal-${sceneId}`}>
          <rect x={0} y={0} width={reveal} height={H} />
        </clipPath>
      </defs>
      {/* 网格与价格刻度（全程可见，不随揭示） */}
      {gridValues.map((value, i) => (
        <g key={i}>
          <line x1={PAD_X} x2={W - PAD_X} y1={y(value)} y2={y(value)} stroke="rgba(255,255,255,0.10)" strokeDasharray="4 6" />
          <text x={W - PAD_X - 6} y={y(value) - 6} fill={theme.text} opacity={0.45} fontSize={19} textAnchor="end">
            {formatPrice(value)}
          </text>
        </g>
      ))}
      <g clipPath={`url(#reveal-${sceneId})`}>
        {/* 布林带等轨道线 */}
        {(["upper", "middle", "lower"] as const).map((bandName) => {
          const band = visual.bands?.[bandName];
          if (!band || band.length !== n) return null;
          const points = band.map((value, i) => `${cx(i)},${y(value)}`).join(" ");
          return (
            <polyline
              key={bandName}
              points={points}
              fill="none"
              stroke={bandName === "middle" ? theme.secondary : toneColor(theme, "accent")}
              strokeWidth={bandName === "middle" ? 2.5 : 2}
              strokeDasharray={bandName === "middle" ? "none" : "7 5"}
              opacity={0.85}
            />
          );
        })}
        {/* 蜡烛 */}
        {candles.map((candle, i) => {
          const up = candle.c >= candle.o;
          const color = up ? upColor : downColor;
          const bodyTop = y(Math.max(candle.o, candle.c));
          const bodyBottom = y(Math.min(candle.o, candle.c));
          return (
            <g key={i}>
              <line x1={cx(i)} x2={cx(i)} y1={y(candle.h)} y2={y(candle.l)} stroke={color} strokeWidth={2} />
              <rect
                x={cx(i) - bodyW / 2}
                y={bodyTop}
                width={bodyW}
                height={Math.max(2.5, bodyBottom - bodyTop)}
                fill={up ? color : color}
                opacity={up ? 0.95 : 0.9}
                rx={1.5}
              />
            </g>
          );
        })}
      </g>
      {/* 标记：在其蜡烛被揭示后 +6 帧弹簧弹出 */}
      {(visual.markers ?? []).map((marker, mi) => {
        if (marker.index >= n) return null;
        const candle = candles[marker.index];
        const pop = spring({
          frame: Math.max(0, frame - (revealFrameAt(marker.index) + 6)),
          fps,
          config: {damping: 13, stiffness: 160},
        });
        if (pop <= 0) return null;
        const anchorY = marker.position === "above" ? y(candle.h) - 14 : y(candle.l) + 14;
        const chipY = marker.position === "above" ? anchorY - 46 : anchorY + 12;
        const color = toneColor(theme, marker.tone);
        // 芯片宽度随文本自适应：深色文字溢出芯片到深背景上会不可读（不是被裁剪）。
        const chipW = Math.max(116, Math.ceil(labelWidthPx(marker.label, 23)) + 36);
        // 宽芯片贴近图表左右缘时会被 SVG 视口裁掉：把芯片中心钳进视口，引线仍锚在蜡烛上。
        const candleX = cx(marker.index);
        const chipOffset = Math.min(Math.max(0, 4 - (candleX - chipW / 2)), W - 4 - (candleX + chipW / 2));
        return (
          <g key={mi} opacity={pop} transform={`translate(${candleX}, 0) scale(${0.5 + pop * 0.5})`} style={{transformOrigin: `${candleX}px ${anchorY}px`}}>
            <line x1={0} x2={0} y1={anchorY} y2={chipY + (marker.position === "above" ? 34 : 0)} stroke={color} strokeWidth={2} />
            <g transform={`translate(${chipOffset}, 0) rotate(-1.5, 0, ${chipY + 17})`}>
              <rect x={-chipW / 2} y={chipY} width={chipW} height={38} rx={9} fill={color} />
              <text x={0} y={chipY + 27} textAnchor="middle" fontSize={23} fontWeight={800} fill="#1A1A1A">
                {marker.label}
              </text>
            </g>
          </g>
        );
      })}
    </svg>
  );
};
