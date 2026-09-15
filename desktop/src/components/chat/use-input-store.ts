/**
 * 输入框状态机 — 按 session 缓存 draft 文字和排队消息队列。
 * 切换会话时保存当前状态，切回来时恢复。
 * 持久化到 localStorage：桌面端应用更新/重启（WebView 重新创建）后草稿仍在 ——
 * 之前用 sessionStorage，更新完一重启输入框内容就没了。
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
  /** 输入框当前附件（贴图等）。仅随内存快照保存/恢复（会话切换），不落 localStorage */
  files: PendingFile[];
}

const STORAGE_KEY = "ethan_input_store";

const emptyState = (): InputState => ({ draft: "", queue: [], files: [] });

let nextQueueId = 1;
export function genQueueId() {
  return `q_${Date.now()}_${nextQueueId++}`;
}

// --- localStorage 持久化 ---

function parseStore(raw: string): Map<string | null, InputState> {
  const obj = JSON.parse(raw) as Record<string, Partial<InputState>>;
  // JSON 里 null key 会变成 "null" 字符串
  const map = new Map<string | null, InputState>();
  for (const [k, v] of Object.entries(obj)) {
    // files 不入 storage（见 persistStore），读取时兜底为空
    map.set(k === "__null__" ? null : k, {
      draft: v.draft ?? "",
      queue: v.queue ?? [],
      files: [],
    });
  }
  return map;
}

function loadStore(): Map<string | null, InputState> {
  if (typeof window === "undefined") return new Map();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return parseStore(raw);
    // 老版本存在 sessionStorage —— 迁移一次，避免升级后丢当前草稿
    const legacy = sessionStorage.getItem(STORAGE_KEY);
    if (legacy) {
      const map = parseStore(legacy);
      sessionStorage.removeItem(STORAGE_KEY);
      return map;
    }
    return new Map();
  } catch {
    return new Map();
  }
}

function persistStore(store: Map<string | null, InputState>) {
  if (typeof window === "undefined") return;
  try {
    const obj: Record<string, Pick<InputState, "draft" | "queue">> = {};
    for (const [k, v] of store.entries()) {
      // 只保存非空状态
      if (v.draft || v.queue.length > 0) {
        // files 不入 localStorage：贴图是 base64 dataUrl，单张即可能 1~2MB，
        // ~5MB 配额下整体 JSON.stringify 会失败，连累 draft/queue 一起丢。
        // files 只随内存快照在会话切换间保存/恢复（应用重启后不恢复）。
        obj[k === null ? "__null__" : k] = { draft: v.draft, queue: v.queue };
      }
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(obj));
  } catch {
    // quota exceeded or private mode — ignore
  }
}

/**
 * useInputStore: 管理每个 session 的输入框草稿和消息队列。
 * - switchTo(sessionId): 保存当前 session 状态，切换到目标 session 并恢复
 * - draft / setDraft: 当前输入文字
 * - queue / addToQueue / removeFromQueue / editInQueue / reorderQueue: 排队消息管理
 * - 持久化到 localStorage，应用重启（含更新重启）后恢复
 */
export function useInputStore() {
  // 存储所有 session 的状态快照（从 localStorage 恢复）
  const storeRef = useRef<Map<string | null, InputState>>(loadStore());
  const currentSessionRef = useRef<string | null>(null);

  // 最新值快照：所有「读当前值再写回」的逻辑（switchTo 保存当前会话、排队入队等）
  // 都必须读它而不是闭包里的 state —— React 的 state 提交是异步的，恢复草稿的
  // setDraftState 还没生效时，任何基于旧闭包的写回都会把刚恢复的内容抹掉
  //（StrictMode 下 effect 双调用时必现：刚 restore 的草稿立刻被挂载时的空快照覆盖）。
  const latestRef = useRef<InputState>(storeRef.current.get(null) ?? emptyState());

  // 初始化时从 storage 恢复当前 session 状态
  const [draft, setDraftState] = useState(latestRef.current.draft);
  const [queue, setQueue] = useState(latestRef.current.queue);
  const [files, setFilesState] = useState(latestRef.current.files);

  // 把最新快照写入当前会话槽位并落盘（写穿：不经过 effect，没有异步提交窗口）
  const flush = useCallback(() => {
    storeRef.current.set(currentSessionRef.current, latestRef.current);
    persistStore(storeRef.current);
  }, []);

  // 窗口失焦时自动保存草稿（防止切走应用时丢失未发送的输入）
  const saveCurrentRef = useRef(flush);
  saveCurrentRef.current = flush;
  useEffect(() => {
    const onBlur = () => saveCurrentRef.current();
    window.addEventListener("blur", onBlur, { passive: true });
    return () => window.removeEventListener("blur", onBlur);
  }, []);

  // 保存当前状态到 store（写穿 latestRef，无需 override —— latestRef 总是最新的）
  const saveCurrent = useCallback(() => {
    flush();
  }, [flush]);

  // 切换会话
  const switchTo = useCallback((sessionId: string | null, _currentDraft?: string) => {
    // 同会话重复切换是幂等空操作：路由参数未变时 load effect 可能重跑（以及
    // StrictMode 的 effect 双调用），此时传入的输入框快照可能还是恢复前的旧值，
    // 拿它覆盖会丢刚恢复的草稿。
    if (currentSessionRef.current === sessionId) return;
    // 保存当前 session 状态（latestRef 保证是已应用的最新值，不依赖 React 提交时机）
    storeRef.current.set(currentSessionRef.current, latestRef.current);
    // 切换
    currentSessionRef.current = sessionId;
    // 恢复目标 session 状态
    const saved = storeRef.current.get(sessionId) ?? emptyState();
    latestRef.current = saved;
    setDraftState(saved.draft);
    setQueue(saved.queue);
    setFilesState(saved.files);
    // 持久化
    persistStore(storeRef.current);
  }, []);

  const setDraft = useCallback((text: string) => {
    latestRef.current = { ...latestRef.current, draft: text };
    flush();
    setDraftState(text);
  }, [flush]);

  const setFiles = useCallback((next: PendingFile[]) => {
    latestRef.current = { ...latestRef.current, files: next };
    // files 只存内存快照（见 persistStore 注释），不落盘
    storeRef.current.set(currentSessionRef.current, latestRef.current);
    setFilesState(next);
  }, []);

  const addToQueue = useCallback((text: string, images?: PendingFile[]) => {
    const item: QueuedMessage = {
      id: genQueueId(),
      text,
      images: images && images.length > 0 ? images : undefined,
    };
    latestRef.current = { ...latestRef.current, queue: [...latestRef.current.queue, item] };
    flush();
    setQueue(latestRef.current.queue);
    return item;
  }, [flush]);

  const removeFromQueue = useCallback((id: string) => {
    latestRef.current = { ...latestRef.current, queue: latestRef.current.queue.filter((m) => m.id !== id) };
    flush();
    setQueue(latestRef.current.queue);
  }, [flush]);

  const editInQueue = useCallback((id: string, text: string) => {
    latestRef.current = { ...latestRef.current, queue: latestRef.current.queue.map((m) => (m.id === id ? { ...m, text } : m)) };
    flush();
    setQueue(latestRef.current.queue);
  }, [flush]);

  const reorderQueue = useCallback((fromIndex: number, toIndex: number) => {
    const next = [...latestRef.current.queue];
    const [moved] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, moved);
    latestRef.current = { ...latestRef.current, queue: next };
    flush();
    setQueue(next);
  }, [flush]);

  // 清空当前队列（对话结束后消费队列时用）
  const clearQueue = useCallback(() => {
    latestRef.current = { ...latestRef.current, queue: [] };
    flush();
    setQueue([]);
  }, [flush]);

  // 获取并清空队列（用于对话结束时批量发送）
  const drainQueue = useCallback((): QueuedMessage[] => {
    const drained = latestRef.current.queue;
    if (drained.length === 0) return [];
    latestRef.current = { ...latestRef.current, queue: [] };
    flush();
    setQueue([]);
    return drained;
  }, [flush]);

  const getQueueForSession = useCallback((sessionId: string | null): QueuedMessage[] => {
    return storeRef.current.get(sessionId)?.queue ?? [];
  }, []);

  const removeFromQueueForSession = useCallback((sessionId: string | null, id: string) => {
    const state = storeRef.current.get(sessionId);
    if (!state) return;
    const next = { ...state, queue: state.queue.filter((m) => m.id !== id) };
    storeRef.current.set(sessionId, next);
    persistStore(storeRef.current);
    if (sessionId === currentSessionRef.current) {
      latestRef.current = next;
      setQueue(next.queue);
    }
  }, []);

  return {
    draft,
    setDraft,
    files,
    setFiles,
    queue,
    addToQueue,
    removeFromQueue,
    editInQueue,
    reorderQueue,
    clearQueue,
    drainQueue,
    switchTo,
    saveCurrent,
    getQueueForSession,
    removeFromQueueForSession,
  };
}
