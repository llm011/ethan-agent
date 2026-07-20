"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import { MessageBubble } from "./message-bubble";
import type { Message } from "./types";
import type { Annotation } from "@/lib/api";

// 首屏显示的消息数量（约 5 轮对话 = 10 条消息）
const INITIAL_VISIBLE = 10;
// 每次向上加载更多的条数
const LOAD_MORE_COUNT = 10;

interface MessageListProps {
  messages: Message[];
  streaming: boolean;
  onQuote?: (msg: Message) => void;
  onCardAction?: (text: string) => void;
  onRead?: (msg: Message) => void;
  onShare?: (msg: Message) => void;
  annotationsByMessage?: Record<number, Annotation[]>;
}

export function MessageList({ messages, streaming, onQuote, onCardAction, onRead, onShare, annotationsByMessage }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // 当前可见消息数（从末尾算）；消息列表变短（切换会话）时重置
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const prevLenRef = useRef(messages.length);

  // 会话切换（消息减少）时重置 visibleCount
  useEffect(() => {
    if (messages.length < prevLenRef.current) {
      setVisibleCount(INITIAL_VISIBLE);
    }
    prevLenRef.current = messages.length;
  }, [messages.length]);

  const hasMore = messages.length > visibleCount;
  const startIdx = hasMore ? messages.length - visibleCount : 0;
  const visibleMessages = messages.slice(startIdx);

  // 向上滚动触顶时加载更多（IntersectionObserver 监听哨兵元素）
  useEffect(() => {
    const container = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!container || !sentinel || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          const prevScrollHeight = container.scrollHeight;
          setVisibleCount((c) => Math.min(c + LOAD_MORE_COUNT, messages.length));
          requestAnimationFrame(() => {
            const newScrollHeight = container.scrollHeight;
            container.scrollTop += newScrollHeight - prevScrollHeight;
          });
        }
      },
      { root: container, threshold: 0, rootMargin: "100px 0px 0px 0px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, messages.length]);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  // 新消息到达时自动滚到底部（仅当用户在底部附近时）
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (isNearBottom) scrollToBottom();
  }, [messages, scrollToBottom]);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
      <div className="max-w-3xl mx-auto space-y-6">
        {/* 顶部加载更多指示器 */}
        {hasMore && (
          <div ref={sentinelRef} className="flex items-center justify-center py-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/50" />
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/50 [animation-delay:150ms]" />
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/50 [animation-delay:300ms]" />
              <span className="ml-1">加载更多对话…</span>
            </div>
          </div>
        )}

        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <p>Start a conversation</p>
          </div>
        )}
        {visibleMessages.map((msg, i) => (
          <MessageBubble
            key={msg.id ?? `idx-${startIdx + i}`}
            msg={msg}
            isStreaming={streaming}
            isLast={startIdx + i === messages.length - 1}
            onQuote={onQuote}
            onCardAction={onCardAction}
            onRead={onRead}
            onShare={onShare}
            annotations={msg.id != null ? annotationsByMessage?.[msg.id] : undefined}
          />
        ))}
      </div>
    </div>
  );
}
