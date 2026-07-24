/**
 * 输入框状态机 — 按 session 缓存 draft 文字和排队消息队列。
 * 切换会话时保存当前状态，切回来时恢复。
 * 持久化到 sessionStorage 以防页面刷新丢失。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { PendingFile } from "@ethan/shared/chat/types";

export interface QueuedMessage {
  id: string;
  text: string;
  images?: PendingFile[];
}

interface InputState {
  draft: string;
  queue: QueuedMessage[];
}

const STORAGE_KEY = "ethan_input_store";

const emptyState = (): InputState => ({ draft: "", queue: [] });

let nextQueueId = 1;
export function genQueueId() {
  return `q_${Date.now()}_${nextQueueId++}`;
}

// --- sessionStorage 持久化 ---

function loadStore(): Map<string | null, InputState> {
  if (typeof window === "undefined") return new Map();
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return new Map();
    const obj = JSON.parse(raw) as Record<string, InputState>;
    // JSON 里 null key 会变成 "null" 字符串
    const map = new Map<string | null, InputState>();
    for (const [k, v] of Object.entries(obj)) {
      map.set(k === "__null__" ? null : k, v);
    }
    return map;
  } catch {
    return new Map();
  }
}

function persistStore(store: Map<string | null, InputState>) {
  if (typeof window === "undefined") return;
  try {
    const obj: Record<string, InputState> = {};
    for (const [k, v] of store.entries()) {
      // 只保存非空状态
      if (v.draft || v.queue.length > 0) {
        obj[k === null ? "__null__" : k] = v;
      }
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    // quota exceeded or private mode — ignore
  }
}

/**
 * useInputStore: 管理每个 session 的输入框草稿和消息队列。
 * - switchTo(sessionId): 保存当前 session 状态，切换到目标 session 并恢复
 * - draft / setDraft: 当前输入文字
 * - queue / addToQueue / removeFromQueue / editInQueue / reorderQueue: 排队消息管理
 * - 自动持久化到 sessionStorage，页面刷新后恢复
 */
export function useInputStore() {
  // 存储所有 session 的状态快照（从 sessionStorage 恢复）
  const storeRef = useRef<Map<string | null, InputState>>(loadStore());
  const currentSessionRef = useRef<string | null>(null);

  // 初始化时从 storage 恢复当前 session 状态
  const [draft, setDraftState] = useState(() => {
    const saved = storeRef.current.get(null);
    return saved?.draft ?? "";
  });
  const [queue, setQueue] = useState<QueuedMessage[]>(() => {
    const saved = storeRef.current.get(null);
    return saved?.queue ?? [];
  });

  // 状态变化时持久化
  const persist = useCallback(() => {
    // 先更新当前 session 的快照
    storeRef.current.set(currentSessionRef.current, { draft, queue });
    persistStore(storeRef.current);
  }, [draft, queue]);

  useEffect(() => {
    persist();
  }, [persist]);

  // 保存当前状态到 store
  const saveCurrent = useCallback((draftOverride?: string, queueOverride?: QueuedMessage[]) => {
    const key = currentSessionRef.current;
    storeRef.current.set(key, {
      draft: draftOverride ?? draft,
      queue: queueOverride ?? queue,
    });
    persistStore(storeRef.current);
  }, [draft, queue]);

  // 切换会话
  const switchTo = useCallback((sessionId: string | null, currentDraft?: string) => {
    // 保存当前 session 状态（使用传入的 currentDraft 以获取最新值）
    storeRef.current.set(currentSessionRef.current, {
      draft: currentDraft ?? draft,
      queue,
    });
    // 切换
    currentSessionRef.current = sessionId;
    // 恢复目标 session 状态
    const saved = storeRef.current.get(sessionId) ?? emptyState();
    setDraftState(saved.draft);
    setQueue(saved.queue);
    // 持久化
    persistStore(storeRef.current);
  }, [draft, queue]);

  const setDraft = useCallback((text: string) => {
    setDraftState(text);
  }, []);

  const addToQueue = useCallback((text: string, images?: PendingFile[]) => {
    const item: QueuedMessage = {
      id: genQueueId(),
      text,
      images: images && images.length > 0 ? images : undefined,
    };
    setQueue((prev) => [...prev, item]);
    return item;
  }, []);

  const removeFromQueue = useCallback((id: string) => {
    setQueue((prev) => prev.filter((m) => m.id !== id));
  }, []);

  const editInQueue = useCallback((id: string, text: string) => {
    setQueue((prev) => prev.map((m) => (m.id === id ? { ...m, text } : m)));
  }, []);

  const reorderQueue = useCallback((fromIndex: number, toIndex: number) => {
    setQueue((prev) => {
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }, []);

  // 清空当前队列（对话结束后消费队列时用）
  const clearQueue = useCallback(() => {
    setQueue([]);
  }, []);

  // 获取并清空队列（用于对话结束时批量发送）
  const drainQueue = useCallback((): QueuedMessage[] => {
    let drained: QueuedMessage[] = [];
    setQueue((prev) => {
      drained = prev;
      return [];
    });
    return drained;
  }, []);

  return {
    draft,
    setDraft,
    queue,
    addToQueue,
    removeFromQueue,
    editInQueue,
    reorderQueue,
    clearQueue,
    drainQueue,
    switchTo,
    saveCurrent,
  };
}
