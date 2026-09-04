"use client";

import { useState, useRef, useLayoutEffect, useEffect } from "react";
import { createPortal } from "react-dom";
import type { Message } from "@ethan/shared/chat/types";

interface QueryDotsProps {
  messages: Message[];
  scrollRef: React.RefObject<HTMLDivElement | null>;
}

interface TooltipPos {
  top: number;   // viewport 坐标，垂直中心
  left: number;  // viewport 坐标，按钮右边缘
  text: string;
}

export function QueryDots({ messages, scrollRef }: QueryDotsProps) {
  const [tooltip, setTooltip] = useState<TooltipPos | null>(null);
  // hideTimer：鼠标从按钮移到 tooltip 的 8px 间隙过渡期保留 tooltip
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dotsRef = useRef<HTMLDivElement>(null);

  const userMessages = messages
    .map((m, i) => ({ msg: m, idx: i }))
    .filter(({ msg }) => msg.role === "user");

  // 动态 gap：消息多时紧凑
  const gap = userMessages.length > 20 ? 0 : userMessages.length > 10 ? 0.5 : 1;

  const clearHideTimer = () => {
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  };

  const scheduleHide = () => {
    clearHideTimer();
    hideTimerRef.current = setTimeout(() => setTooltip(null), 150);
  };

  useEffect(() => {
    return () => clearHideTimer();
  }, []);

  useLayoutEffect(() => {
    if (!tooltip) return;
    // 滚动时关闭 tooltip，避免位置错位
    const container = scrollRef.current;
    if (!container) return;
    const onScroll = () => setTooltip(null);
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, [tooltip, scrollRef]);

  if (userMessages.length < 2) return null;

  const handleClick = (msgIdx: number) => {
    const container = scrollRef.current;
    if (!container) return;
    const el = container.querySelector(`[data-msg-idx="${msgIdx}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  const showTooltip = (e: React.MouseEvent<HTMLButtonElement>, text: string) => {
    clearHideTimer();
    const rect = e.currentTarget.getBoundingClientRect();
    setTooltip({
      top: rect.top + rect.height / 2,
      left: rect.right + 8,
      text: text || "(空)",
    });
  };

  return (
    <>
      <div
        ref={dotsRef}
        className="absolute left-0 top-0 bottom-0 w-7 z-20 flex flex-col items-center justify-center pointer-events-none overflow-hidden"
        style={{ gap: `${gap * 4}px` }}
      >
        {userMessages.map(({ msg, idx }) => (
          <button
            key={idx}
            type="button"
            onClick={() => handleClick(idx)}
            onMouseEnter={(e) => showTooltip(e, msg.content)}
            onMouseLeave={scheduleHide}
            className="pointer-events-auto h-4 w-4 flex items-center justify-center cursor-pointer group/btn shrink-0"
          >
            <span className="block h-[7px] w-[7px] rounded-full bg-muted-foreground/50 group-hover/btn:bg-primary group-hover/btn:scale-[1.8] transition-all duration-150" />
          </button>
        ))}
      </div>

      {tooltip && createPortal(
        <div
          className="fixed z-[9999] w-[576px] max-h-64 px-2.5 py-1.5 rounded-lg bg-foreground text-background text-xs leading-snug shadow-lg overflow-y-auto break-words whitespace-normal"
          style={{
            top: tooltip.top,
            left: tooltip.left,
            transform: "translateY(-50%)",
          }}
          onMouseEnter={clearHideTimer}
          onMouseLeave={scheduleHide}
        >
          {tooltip.text}
        </div>,
        document.body,
      )}
    </>
  );
}
