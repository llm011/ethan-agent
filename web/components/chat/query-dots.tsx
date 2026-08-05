"use client";

import { useState, useRef } from "react";
import type { Message } from "@ethan/shared/chat/types";

interface QueryDotsProps {
  messages: Message[];
  scrollRef: React.RefObject<HTMLDivElement | null>;
}

export function QueryDots({ messages, scrollRef }: QueryDotsProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const dotsRef = useRef<HTMLDivElement>(null);

  const userMessages = messages
    .map((m, i) => ({ msg: m, idx: i }))
    .filter(({ msg }) => msg.role === "user");

  if (userMessages.length < 2) return null;

  const handleClick = (msgIdx: number) => {
    const container = scrollRef.current;
    if (!container) return;
    const el = container.querySelector(`[data-msg-idx="${msgIdx}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  // 动态 gap：消息多时紧凑（gap 基于视觉间距，hit area 由 button h-4 提供）
  const gap = userMessages.length > 20 ? 0 : userMessages.length > 10 ? 0.5 : 1;

  return (
    <div
      ref={dotsRef}
      className="absolute left-0 top-0 bottom-0 w-7 z-20 flex flex-col items-center justify-center overflow-hidden pointer-events-none"
      style={{ gap: `${gap * 4}px` }}
    >
      {userMessages.map(({ msg, idx }, dotIdx) => (
        <div
          key={idx}
          className="relative group/dot pointer-events-auto flex items-center"
          onMouseEnter={() => setHoverIdx(dotIdx)}
          onMouseLeave={() => setHoverIdx(null)}
        >
          <button
            type="button"
            onClick={() => handleClick(idx)}
            className="h-4 w-4 flex items-center justify-center cursor-pointer group/btn"
          >
            <span className="block h-[7px] w-[7px] rounded-full bg-muted-foreground/50 group-hover/btn:bg-primary group-hover/btn:scale-[1.8] transition-all duration-150" />
          </button>
          {hoverIdx === dotIdx && (
            <div
              className="absolute left-5 top-1/2 -translate-y-1/2 px-2.5 py-1.5 rounded-lg bg-foreground text-background text-xs leading-snug max-w-[240px] line-clamp-2 whitespace-pre-wrap shadow-lg pointer-events-none z-50"
            >
              {msg.content || "(空)"}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
