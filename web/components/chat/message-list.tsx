"use client";

import { useRef, useEffect, useCallback, useState } from "react";
import { ArrowDown } from "lucide-react";
import { MessageBubble } from "./message-bubble";
import { QueryDots } from "./query-dots";
import type { Message } from "@ethan/shared/chat/types";
import type { Annotation } from "@/lib/api";

// 首屏显示的消息数量（约 5 轮对话 = 10 条消息）
const INITIAL_VISIBLE = 10;
// 每次向上加载更多的条数
const LOAD_MORE_COUNT = 10;

interface MessageListProps {
  messages: Message[];
  streaming: boolean;
  sessionId?: string | null;
  onQuote?: (msg: Message) => void;
  onCardAction?: (text: string) => void;
  onRead?: (msg: Message) => void;
  onShare?: (msg: Message) => void;
  onDelete?: (msg: Message) => void;
  onInject?: (content: string) => Promise<{ ok: boolean; error?: string }>;
  annotationsByMessage?: Record<number, Annotation[]>;
}

export function MessageList({ messages, streaming, sessionId, onQuote, onCardAction, onRead, onShare, onDelete, onInject, annotationsByMessage }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  // 当前可见消息数（从末尾算）；消息列表变短（切换会话）时重置
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const prevLenRef = useRef(messages.length);
  // 记录上一次的 user 消息数量，用于识别"用户刚发送了消息"
  // （不能用 messages 末尾 role 判断：consumeStream 会立即 push 空 assistant 占位，
  // React 18 batching 后末尾是 assistant，导致 lastIsUser 误判）
  const prevUserCountRef = useRef(0);

  // 滚动到底部按钮相关状态
  // isAtBottom: 实时反映用户是否在底部（用于控制按钮显示/隐藏）
  // stickToBottom: 用户点了"滚到底部"按钮后置 true，让后续新消息持续强制滚到底，
  //   直到用户手动向上滚才解除（实现"跟随对话在底部"）
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [stickToBottom, setStickToBottom] = useState(false);
  // 区分"程序触发的滚动"和"用户手动滚动"：程序滚动时不解除 stickToBottom
  const programmaticScrollRef = useRef(false);

  // 会话切换（消息减少）时重置 visibleCount
  useEffect(() => {
    if (messages.length < prevLenRef.current) {
      setVisibleCount(INITIAL_VISIBLE);
      // 切会话时同步重置 user 计数基线，避免误触发"新 user 消息"
      prevUserCountRef.current = messages.filter(m => m.role === "user").length;
      // 切会话重置锁定状态
      setStickToBottom(false);
      setIsAtBottom(true);
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
      programmaticScrollRef.current = true;
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  // 监听滚动：实时更新 isAtBottom；用户手动向上滚时解除 stickToBottom
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const near = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      setIsAtBottom(near);
      // 程序触发的滚动不解除锁定
      if (programmaticScrollRef.current) {
        if (near) programmaticScrollRef.current = false;
        return;
      }
      // 用户手动向上滚 → 解除锁定
      if (!near && stickToBottom) {
        setStickToBottom(false);
      }
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [stickToBottom]);

  // 新消息到达时自动滚到底部
  // - 用户发送的新消息（user 数量增加）：强制滚到底部（无论当前滚动位置）
  //   不能用 messages 末尾 role 判断：consumeStream 会立即 push 空 assistant 占位，
  //   React 18 batching 后末尾是 assistant，导致 lastIsUser 误判，用户在中间时不滚动
  // - stickToBottom=true：用户点了"滚到底部"按钮，持续跟随
  // - 助手流式更新：仅当用户在底部附近时跟随滚动，避免打断向上翻阅
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const userCount = messages.filter(m => m.role === "user").length;
    const hasNewUserMessage = userCount > prevUserCountRef.current;
    prevUserCountRef.current = userCount;
    if (hasNewUserMessage || stickToBottom) {
      // 等下一帧 DOM 渲染完成再滚，避免 scrollHeight 还是旧值
      requestAnimationFrame(() => scrollToBottom());
      return;
    }
    // 如果用户已经滚到接近底部（80px 阈值），自动跟随
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (isNearBottom) {
      requestAnimationFrame(() => scrollToBottom());
    }
  }, [messages, scrollToBottom, stickToBottom]);

  const handleScrollToBottom = useCallback(() => {
    scrollToBottom();
    setStickToBottom(true);
    setIsAtBottom(true);
  }, [scrollToBottom]);

  return (
    <div className="relative flex-1 min-h-0">
    <QueryDots messages={messages} scrollRef={scrollRef} />
    <div ref={scrollRef} className="absolute inset-0 overflow-y-auto p-4 pl-7">
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
          <div key={msg.id ?? `idx-${startIdx + i}`} data-msg-idx={startIdx + i}>
          <MessageBubble
            msg={msg}
            isStreaming={streaming}
            isLast={startIdx + i === messages.length - 1}
            sessionId={sessionId}
            onQuote={onQuote}
            onCardAction={onCardAction}
            onRead={onRead}
            onShare={onShare}
            onDelete={onDelete}
            onInject={onInject}
            annotations={msg.id != null ? annotationsByMessage?.[msg.id] : undefined}
          />
          </div>
        ))}
      </div>
    </div>

      {/* 滚动到底部按钮：不在底部时显示；点击后锁定跟随新消息 */}
      {messages.length > 0 && !isAtBottom && (
        <button
          type="button"
          onClick={handleScrollToBottom}
          className={`absolute bottom-4 right-4 z-10 flex items-center justify-center h-9 w-9 rounded-full border bg-background/95 backdrop-blur shadow-md hover:bg-accent transition-colors ${stickToBottom ? "text-primary" : "text-muted-foreground"}`}
          title={stickToBottom ? "已锁定跟随底部（向上滚解除）" : "滚动到底部并跟随"}
        >
          <ArrowDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
