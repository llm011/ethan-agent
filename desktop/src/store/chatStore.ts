/**
 * 专业级聊天状态管理 - Zustand
 * 
 * 优势：
 * 1. 响应式更新，只触发必要的重渲染
 * 2. 时间旅行调试支持
 * 3. 中间件扩展（持久化、devtools）
 * 4. 性能优于 Context + useState
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type { Message, Usage, Quote } from '@ethan/shared/chat/types';
import type { ModelEntry, ModeEntry } from '@/lib/api-base';
import type { BackgroundTask } from '@/lib/api-misc';

interface ChatState {
  // 核心状态
  messages: Message[];
  streaming: boolean;
  isLoading: boolean;
  error: string | null;
  
  // 会话信息
  activeSessionId: string | null;
  sessionTitle: string;
  sessionUsage: Usage;
  
  // UI 状态
  quote: Quote | null;
  models: ModelEntry[];
  selectedModel: string;
  modes: ModeEntry[];
  selectedMode: string;
  
  // 附件
  attachments: File[];
  
  // 后台任务
  bgTasks: BackgroundTask[];
  
  // 分页
  hasOlder: boolean;
  loadingOlder: boolean;
  
  // Actions
  setMessages: (messages: Message[]) => void;
  addMessage: (message: Message) => void;
  updateMessage: (id: string, updates: Partial<Message>) => void;
  removeMessage: (id: string) => void;
  
  setStreaming: (streaming: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  
  setActiveSession: (sessionId: string | null) => void;
  setSessionTitle: (title: string) => void;
  setSessionUsage: (usage: Usage) => void;
  
  setQuote: (quote: Quote | null) => void;
  setModels: (models: ModelEntry[]) => void;
  setSelectedModel: (model: string) => void;
  setModes: (modes: ModeEntry[]) => void;
  setSelectedMode: (mode: string) => void;
  
  addAttachment: (file: File) => void;
  removeAttachment: (index: number) => void;
  clearAttachments: () => void;
  
  setBgTasks: (tasks: BackgroundTask[]) => void;
  addBgTask: (task: BackgroundTask) => void;
  removeBgTask: (taskId: string) => void;
  
  setHasOlder: (hasOlder: boolean) => void;
  setLoadingOlder: (loading: boolean) => void;
}

export const useChatStore = create<ChatState>()(
  devtools(
    persist(
      (set, get) => ({
        // 初始状态
        messages: [],
        streaming: false,
        isLoading: false,
        error: null,
        activeSessionId: null,
        sessionTitle: '',
        sessionUsage: { input: 0, output: 0, cache: 0 },
        quote: null,
        models: [],
        selectedModel: '',
        modes: [],
        selectedMode: '',
        attachments: [],
        bgTasks: [],
        hasOlder: false,
        loadingOlder: false,
        
        // Actions
        setMessages: (messages) => set({ messages }),
        addMessage: (message) => set((state) => ({
          messages: [...state.messages, message],
        })),
        updateMessage: (id, updates) => set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, ...updates } : msg
          ),
        })),
        removeMessage: (id) => set((state) => ({
          messages: state.messages.filter((msg) => msg.id !== id),
        })),
        
        setStreaming: (streaming) => set({ streaming }),
        setLoading: (isLoading) => set({ isLoading }),
        setError: (error) => set({ error }),
        
        setActiveSession: (activeSessionId) => set({ activeSessionId }),
        setSessionTitle: (sessionTitle) => set({ sessionTitle }),
        setSessionUsage: (sessionUsage) => set({ sessionUsage }),
        
        setQuote: (quote) => set({ quote }),
        setModels: (models) => set({ models }),
        setSelectedModel: (selectedModel) => set({ selectedModel }),
        setModes: (modes) => set({ modes }),
        setSelectedMode: (selectedMode) => set({ selectedMode }),
        
        addAttachment: (file) => set((state) => ({
          attachments: [...state.attachments, file],
        })),
        removeAttachment: (index) => set((state) => ({
          attachments: state.attachments.filter((_, i) => i !== index),
        })),
        clearAttachments: () => set({ attachments: [] }),
        
        setBgTasks: (bgTasks) => set({ bgTasks }),
        addBgTask: (task) => set((state) => ({
          bgTasks: [...state.bgTasks, task],
        })),
        removeBgTask: (taskId) => set((state) => ({
          bgTasks: state.bgTasks.filter((t) => t.id !== taskId),
        })),
        
        setHasOlder: (hasOlder) => set({ hasOlder }),
        setLoadingOlder: (loadingOlder) => set({ loadingOlder }),
      }),
      {
        name: 'chat-storage',
        partialize: (state) => ({
          selectedModel: state.selectedModel,
          selectedMode: state.selectedMode,
        }),
      }
    )
  )
);
