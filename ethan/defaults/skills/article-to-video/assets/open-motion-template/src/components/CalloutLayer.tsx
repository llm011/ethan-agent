import React from "react";
import {spring, useCurrentFrame, useVideoConfig} from "@open-motion/core";
import type {Callout, Theme} from "../types";
import {toneColor} from "../types";

// 黄色关键词标注（晓玉说同款）：场景头部下方横向排列，交错弹簧弹入 + 轻微脉动。
// 全部帧驱动，禁用 CSS animation。
export const CalloutLayer: React.FC<{callouts: Callout[]; theme: Theme}> = ({callouts, theme}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <div style={{display: "flex", gap: 18, flexWrap: "wrap", marginTop: 26, maxWidth: 640}}>
      {callouts.slice(0, 3).map((callout, index) => {
        const pop = spring({
          frame: Math.max(0, frame - index * 8),
          fps,
          config: {damping: 12, stiffness: 170},
        });
        const pulse = 1 + 0.02 * Math.sin(frame / 12 + index);
        const color = toneColor(theme, callout.tone);
        return (
          <div
            key={`${callout.text}-${index}`}
            style={{
              opacity: pop,
              transform: `scale(${(0.6 + pop * 0.4) * pulse}) rotate(${index % 2 === 0 ? -1.5 : 1.2}deg)`,
              background: color,
              color: "#1A1A1A",
              fontSize: 34,
              fontWeight: 900,
              padding: "12px 26px",
              borderRadius: 14,
              boxShadow: "0 14px 40px rgba(0,0,0,0.4)",
              letterSpacing: 1,
              whiteSpace: "nowrap",
            }}
          >
            {callout.text}
          </div>
        );
      })}
    </div>
  );
};
