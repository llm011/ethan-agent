"use client";
/* SWR 风格的资源缓存 hook：读缓存立即渲染 + 后台 refetch + bust 失效。
 *
 * 用法：
 *   const { data, loading, error, refresh } = useCachedResource(
 *     "models",                  // cache key
 *     () => fetchModels(),       // fetcher
 *     { ttlMs: 60_000 },         // 1 分钟 TTL
 *   );
 *
 * 行为：
 * - 首次挂载：读缓存命中 → 立即返回 data（loading=false）
 *             缓存未命中或过期 → loading=true，fetch 完返回
 * - 缓存命中但过期（stale）：立即返回旧值（loading=false），后台 refetch
 *   完成后用新值替换（用户无感知刷新）
 * - bustCache(key) 被调用：立即标记 stale，后台 refetch
 * - 多组件共享同一 key：每个组件都能拿到最新值（bust 事件广播）
 *
 * 适用：A 类准静态数据（models/modes/agentSettings/onboarding）。
 * 不适用：流式数据、需要严格一致性的数据（会话 messages）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { readCache, writeCache, onBust, deleteCache } from "./local-cache";

/* 浅比较两个值是否相等（用于避免后台 refetch 返回相同数据时触发 re-render）。
 * models/modes/settings 这些数据内容通常不变，但每次 fetch 返回的是新对象引用，
 * 不做比较会导致每次后台 refetch 都触发 4 次 setData → 4 次 ChatView re-render。
 */
function shallowEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (a == null || b == null) return false;
  if (typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    const aa = a as unknown[];
    const bb = b as unknown[];
    if (aa.length !== bb.length) return false;
    for (let i = 0; i < aa.length; i++) {
      if (aa[i] !== bb[i]) return false;
    }
    return true;
  }
  const objA = a as Record<string, unknown>;
  const objB = b as Record<string, unknown>;
  const keysA = Object.keys(objA);
  const keysB = Object.keys(objB);
  if (keysA.length !== keysB.length) return false;
  for (const k of keysA) {
    if (objA[k] !== objB[k]) return false;
  }
  return true;
}

export interface UseCachedResourceOptions {
  /** 缓存有效期。过期后仍返回旧值，但会触发后台 refetch。默认 60 秒。 */
  ttlMs?: number;
  /** 是否启用 SWR（缓存过期时仍返回旧值）。默认 true。false = 过期就当无缓存。 */
  swr?: boolean;
  /** 是否在窗口重新可见时 refetch。默认 true。 */
  refetchOnVisible?: boolean;
}

export interface CachedResource<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  /** 手动刷新（绕过缓存，强制 fetch 并更新） */
  refresh: () => Promise<void>;
}

// 全局去重：同一个 key 同时有多个组件挂载时，只发一次 fetch
const _inflight = new Map<string, Promise<unknown>>();

export function useCachedResource<T>(
  cacheKey: string,
  fetcher: () => Promise<T>,
  options: UseCachedResourceOptions = {},
): CachedResource<T> {
  const { ttlMs = 60_000, swr = true, refetchOnVisible = true } = options;
  const [data, setData] = useState<T | null>(() => {
    const cached = readCache<T>(cacheKey);
    return cached ? cached.value : null;
  });
  const [loading, setLoading] = useState<boolean>(() => {
    const cached = readCache<T>(cacheKey);
    // 无缓存或（过期且不启用 SWR）→ loading
    if (!cached) return true;
    if (cached.stale && !swr) return true;
    return false;
  });
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const doFetch = useCallback(async (): Promise<void> => {
    // 去重：同一 key 同时多次调用时复用 inflight promise
    const existing = _inflight.get(cacheKey);
    if (existing) {
      try {
        const v = await existing as T;
        setData(v);
        setError(null);
      } catch (e) {
        // 已有 inflight 失败，不重复报错（首次挂载的组件会处理）
      }
      return;
    }
    const p = (async () => {
      try {
        const v = await fetcherRef.current();
        writeCache(cacheKey, v, ttlMs);
        // 浅比较：如果数据和当前 state 相同（内容不变，只是引用变了），
        // 不触发 re-render。后台 refetch 每 60s 跑一次，大多数时候数据没变。
        setData((prev) => shallowEqual(prev, v) ? prev : v);
        setError(null);
      } catch (e) {
        // fetch 失败时保留旧缓存值（不清除），仅设置 error
        // 这样网络抖动时用户仍能看到上次的数据
        setError(e instanceof Error ? e : new Error(String(e)));
      } finally {
        _inflight.delete(cacheKey);
      }
    })();
    _inflight.set(cacheKey, p);
    await p;
  }, [cacheKey, ttlMs]);

  // 挂载 + cacheKey 变化时决定是否 fetch
  useEffect(() => {
    const cached = readCache<T>(cacheKey);
    if (!cached) {
      // 无缓存：必须 fetch，loading=true
      setLoading(true);
      void doFetch().finally(() => setLoading(false));
    } else if (cached.stale) {
      // 过期：SWR 模式立即返回旧值（loading 保持 false），后台 refetch
      // 非 SWR 模式：loading=true，等 fetch 完
      if (!swr) {
        setLoading(true);
        void doFetch().finally(() => setLoading(false));
      } else {
        void doFetch(); // 后台静默刷新，不打扰用户
      }
    }
    // 未过期：什么都不做，缓存命中即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey]);

  // 订阅 bust 事件：被 bustCache(key) 失效时立即 refetch
  useEffect(() => {
    const unsub = onBust((bustedKey) => {
      if (bustedKey === cacheKey || bustedKey === "") {
        void doFetch();
      }
    });
    return unsub;
  }, [cacheKey, doFetch]);

  // 窗口重新可见时 refetch（用户切走再切回桌面端，立即拿最新数据）
  useEffect(() => {
    if (!refetchOnVisible) return;
    const handler = () => {
      if (!document.hidden) {
        const cached = readCache<T>(cacheKey);
        // 仅在过期时 refetch，避免无意义的请求
        if (!cached || cached.stale) {
          void doFetch();
        }
      }
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [cacheKey, doFetch, refetchOnVisible]);

  const refresh = useCallback(async () => {
    deleteCache(cacheKey);
    setLoading(true);
    try {
      await doFetch();
    } finally {
      setLoading(false);
    }
  }, [doFetch]);

  return { data, loading, error, refresh };
}
