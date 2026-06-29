"use client";

import { useRef, useEffect, useCallback } from "react";
import { MessageBubble } from "./message-bubble";
import type { Message } from "./types";

interface MessageListProps {
  messages: Message[];
  streaming: boolean;
  onQuote?: (msg: Message) => void;
  onCardAction?: (text: string) => void;
}

export function MessageList({ messages, streaming, onQuote, onCardAction }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-4">
      <div className="max-w-3xl mx-auto space-y-4">
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <p>Start a conversation</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            msg={msg}
            isStreaming={streaming}
            isLast={i === messages.length - 1}
            onQuote={onQuote}
            onCardAction={onCardAction}
          />
        ))}
      </div>
    </div>
  );
}
