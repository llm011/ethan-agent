/**
 * 输入框状态机 — 按 session 缓存 draft 文字和排队消息队列。
 * 切换会话时保存当前状态，切回来时恢复。
 */

import { useCallback, useRef, useState } from "react";

export interface QueuedMessage {
  id: string;
  text: string;
}

interface InputState {
  draft: string;
  queue: QueuedMessage[];
}

const emptyState = (): InputState => ({ draft: "", queue: [] });

let nextQueueId = 1;
export function genQueueId() {
  return `q_${Date.now()}_${nextQueueId++}`;
}

/**
 * useInputStore: 管理每个 session 的输入框草稿和消息队列。
 * - switchTo(sessionId): 保存当前 session 状态，切换到目标 session 并恢复
 * - draft / setDraft: 当前输入文字
 * - queue / addToQueue / removeFromQueue / editInQueue / reorderQueue: 排队消息管理
 */
export function useInputStore() {
  // 存储所有 session 的状态快照
  const storeRef = useRef<Map<string | null, InputState>>(new Map());
  const currentSessionRef = useRef<string | null>(null);

  const [draft, setDraftState] = useState("");
  const [queue, setQueue] = useState<QueuedMessage[]>([]);

  // 保存当前状态到 store
  const saveCurrent = useCallback((draftOverride?: string, queueOverride?: QueuedMessage[]) => {
    const key = currentSessionRef.current;
    storeRef.current.set(key, {
      draft: draftOverride ?? draft,
      queue: queueOverride ?? queue,
    });
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
  }, [draft, queue]);

  const setDraft = useCallback((text: string) => {
    setDraftState(text);
  }, []);

  const addToQueue = useCallback((text: string) => {
    const item: QueuedMessage = { id: genQueueId(), text };
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
