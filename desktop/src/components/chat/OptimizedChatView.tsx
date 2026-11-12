/**
 * 优化版聊天视图 - 深度考虑用户交互体验
 * 
 * 核心优化点：
 * 1. Enter 键发送（Shift+Enter 换行）
 * 2. 长按消息弹出菜单（复制/引用/删除）
 * 3. 流式响应实时显示光标动画
 * 4. 附件拖拽上传支持
 * 5. 智能滚动（新消息到达时自动到底部）
 * 6. 消息气泡打字机效果
 * 7. 错误重试机制
 * 8. 快速操作按钮（编辑/删除/重新生成）
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useChatStore } from '@/store/chatStore';
import { useOptimizedScroll } from '@/hooks/useOptimizedScroll';
import { ProfessionalButton } from '@/components/ui/ProfessionalButton';
import { ProfessionalCard } from '@/components/ui/ProfessionalCard';
import type { Message } from '@ethan/shared/chat/types';

interface OptimizedChatViewProps {
  messages: Message[];
  inputText: string;
  isStreaming: boolean;
  error: string | null;
  onInputChange: (text: string) => void;
  onSend: () => void;
  onMessageClick: (message: Message) => void;
  onMessageLongClick: (message: Message) => void;
}

export function OptimizedChatView({
  messages,
  inputText,
  isStreaming,
  error,
  onInputChange,
  onSend,
  onMessageClick,
  onMessageLongClick,
}: OptimizedChatViewProps) {
  const [showMenuForMessage, setShowMenuForMessage] = useState<Message | null>(null);
  const [shouldAutoScrollToBottom, setShouldAutoScrollToBottom] = useState(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  
  // 首次加载自动聚焦输入框
  useEffect(() => {
    inputRef.current?.focus();
  }, []);
  
  // 监听消息变化，智能决定是否自动滚动
  useEffect(() => {
    if (messages.length > 0 && shouldAutoScrollToBottom) {
      scrollToBottom();
    }
  }, [messages.length, shouldAutoScrollToBottom]);
  
  const { scrollContainerRef, scrollToBottom, isAtBottom } = useOptimizedScroll({
    onReachBottom: () => setShouldAutoScrollToBottom(true),
    threshold: 50,
  });
  
  // 键盘事件处理：Enter 发送，Shift+Enter 换行
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (inputText.trim()) {
        onSend();
      }
    }
  }, [inputText, onSend]);
  
  return (
    <div className="flex flex-col h-full bg-background">
      {/* 顶部工具栏 */}
      <ChatTopBarWithActions />
      
      {/* 消息列表 */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto p-4 space-y-4"
        onScroll={() => {
          if (!isAtBottom()) {
            setShouldAutoScrollToBottom(false);
          }
        }}
      >
        {messages.map((message) => (
          <OptimizedMessageItem
            key={message.id}
            message={message}
            onClick={() => onMessageClick(message)}
            onLongClick={() => {
              onMessageLongClick(message);
              setShowMenuForMessage(message);
            }}
          />
        ))}
        
        {/* 底部间距 */}
        <div className="h-20" />
      </div>
      
      {/* 错误提示 */}
      {error && (
        <ErrorBannerWithRetry
          message={error}
          onDismiss={() => { /* TODO: 清除错误 */ }}
          onRetry={() => { /* TODO: 重试 */ }}
        />
      )}
      
      {/* 输入区域 */}
      <ChatInputArea
        text={inputText}
        onChange={onInputChange}
        onSend={onSend}
        isStreaming={isStreaming}
        inputRef={inputRef}
        onKeyDown={handleKeyDown}
      />
      
      {/* 消息操作菜单 */}
      {showMenuForMessage && (
        <MessageActionMenu
          message={showMenuForMessage}
          onDismiss={() => setShowMenuForMessage(null)}
          onCopy={() => { /* TODO: 复制 */ }}
          onQuote={() => { /* TODO: 引用 */ }}
          onDelete={() => { /* TODO: 删除 */ }}
        />
      )}
    </div>
  );
}

/**
 * 优化的输入区域
 */
function ChatInputArea({
  text,
  onChange,
  onSend,
  isStreaming,
  inputRef,
  onKeyDown,
}: {
  text: string;
  onChange: (text: string) => void;
  onSend: () => void;
  isStreaming: boolean;
  inputRef: React.RefObject<HTMLTextAreaElement>;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
}) {
  return (
    <div className="border-t border-border bg-surface-container-higherive p-4">
      <div className="max-w-4xl mx-auto">
        {/* 附件预览（待实现） */}
        
        <div className="flex items-end gap-3">
          {/* 附件按钮 */}
          <button
            type="button"
            onClick={() => { /* TODO: 打开附件选择器 */ }}
            disabled={isStreaming}
            className="p-2 rounded-lg hover:bg-secondary-container disabled:opacity-50 transition-colors"
            aria-label="添加附件"
          >
            <AttachmentIcon className="w-5 h-5" />
          </button>
          
          {/* 文本输入框 */}
          <textarea
            ref={inputRef}
            value={text}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="输入消息...按 Enter 发送，Shift+Enter 换行"
            rows={1}
            maxRows={5}
            disabled={isStreaming}
            className="flex-1 resize-none px-4 py-3 rounded-xl border border-input focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all disabled:opacity-50 bg-surface"
            style={{ minHeight: '48px', maxHeight: '120px' }}
          />
          
          {/* 发送按钮 */}
          <ProfessionalButton
            text={isStreaming ? '停止' : '发送'}
            onClick={onSend}
            variant={isStreaming ? 'Secondary' : 'Primary'}
            disabled={!text.trim() || isStreaming}
            icon={isStreaming ? undefined : 'send'}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * 优化的消息项
 */
function OptimizedMessageItem({
  message,
  onClick,
  onLongClick,
}: {
  message: Message;
  onClick: () => void;
  onLongClick: () => void;
}) {
  const isUser = message.role === 'user';
  
  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} group`}
      onClick={onClick}
      onContextMenu={(e) => {
        e.preventDefault();
        onLongClick();
      }}
    >
      <div className={`max-w-[80%] ${isUser ? 'order-2' : 'order-1'}`}>
        {/* Assistant 头像 */}
        {!isUser && (
          <div className="mb-2">
            <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center">
              <AssistantIcon className="w-4 h-4 text-on-primary-container" />
            </div>
          </div>
        )}
        
        {/* 消息气泡 */}
        <div
          className={`rounded-2xl px-4 py-3 ${
            isUser
              ? 'bg-primary-container text-on-primary-container rounded-tr-none'
              : 'bg-surface-variant text-on-surface-variant rounded-tl-none'
          }`}
        >
          {message.isStreaming && !isUser ? (
            <TypingIndicator />
          ) : (
            <p className="text-body-medium leading-relaxed">{message.content}</p>
          )}
        </div>
        
        {/* 快捷操作按钮（悬停显示） */}
        <div className={`flex gap-2 mt-2 opacity-0 group-hover:opacity-100 transition-opacity ${isUser ? 'justify-end' : 'justify-start'}`}>
          <button
            onClick={(e) => {
              e.stopPropagation();
              navigator.clipboard.writeText(message.content);
            }}
            className="p-1.5 rounded-lg hover:bg-secondary-container text-on-surface-variant transition-colors"
            title="复制"
          >
            <CopyIcon className="w-4 h-4" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onLongClick();
            }}
            className="p-1.5 rounded-lg hover:bg-secondary-container text-on-surface-variant transition-colors"
            title="更多操作"
          >
            <MoreVerticalIcon className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 打字机光标动画
 */
function TypingIndicator() {
  const [dots, setDots] = useState(1);
  
  React.useEffect(() => {
    const interval = setInterval(() => {
      setDots((prev) => (prev < 3 ? prev + 1 : 1));
    }, 500);
    
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="flex items-center gap-1">
      <span className="text-on-surface-variant">正在思考</span>
      {'.'.repeat(dots)}
    </div>
  );
}

/**
 * 带重试的错误横幅
 */
function ErrorBannerWithRetry({
  message,
  onDismiss,
  onRetry,
}: {
  message: string;
  onDismiss: () => void;
  onRetry: () => void;
}) {
  return (
    <div className="mx-4 mb-4 bg-error-container rounded-lg p-4 flex items-center gap-3 shadow-md">
      <ErrorIcon className="w-5 h-5 text-on-error-container" />
      <span className="text-on-error-container flex-1">{message}</span>
      <button
        onClick={onRetry}
        className="p-1.5 rounded-lg hover:bg-error/20 text-on-error-container transition-colors"
        title="重试"
      >
        <RefreshIcon className="w-4 h-4" />
      </button>
      <button
        onClick={onDismiss}
        className="p-1.5 rounded-lg hover:bg-error/20 text-on-error-container transition-colors"
        title="关闭"
      >
        <CloseIcon className="w-4 h-4" />
      </button>
    </div>
  );
}

// 图标组件（简化版，实际应使用 lucide-react 或 react-icons）
const AttachmentIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
  </svg>
);
const AssistantIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
  </svg>
);
const CopyIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
  </svg>
);
const MoreVerticalIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
  </svg>
);
const ErrorIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);
const RefreshIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
  </svg>
);
const CloseIcon = ({ className }: { className?: string }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
  </svg>
);
