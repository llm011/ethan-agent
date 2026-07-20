/* 本地缓存存储抽象：localStorage + JSON 序列化 + TTL。
 *
 * 桌面端不像浏览器受 localStorage 5MB 限制（Tauri webview 容量宽松），
 * 准静态数据（models/modes/agentSettings/onboarding）走这里比每次进页面
 * 都 fetch 快得多——首屏 0ms 渲染，后台 SWR 校验。
 *
 * 设计要点：
 * - 每条缓存结构：{ value, expires_at, fetched_at }
 * - 过期判定：expires_at < Date.now() 视为过期（读取时仍返回值，由 hook 决定是否后台 refetch）
 * - bust 机制：通过 CustomEvent 广播失效信号，所有订阅该 key 的 useCachedResource 标记 stale
 * - 跨 tab 同步：监听 storage 事件（多窗口场景，单窗口无影响）
 * - 写入容错：localStorage 满或不可用时静默降级（不影响功能，只是缓存失效）
 */

const CACHE_PREFIX = "ethan_cache:";
const BUST_EVENT = "ethan:cache-bust";

interface CacheEntry<T> {
  value: T;
  expires_at: number; // ms timestamp，0 表示立即过期
  fetched_at: number; // ms timestamp，用于调试
}

function key(k: string): string {
  return CACHE_PREFIX + k;
}

/** 读缓存。不存在或解析失败返回 null；过期也返回值（由调用方决定是否 refetch）。 */
export function readCache<T>(k: string): { value: T; stale: boolean; fetchedAt: number } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(key(k));
    if (!raw) return null;
    const entry = JSON.parse(raw) as CacheEntry<T>;
    return {
      value: entry.value,
      stale: entry.expires_at < Date.now(),
      fetchedAt: entry.fetched_at,
    };
  } catch {
    return null;
  }
}

/** 写缓存。ttlMs=0 表示立即过期（仍会写入，供下次 stale-while-revalidate 读）。 */
export function writeCache<T>(k: string, value: T, ttlMs: number): void {
  if (typeof window === "undefined") return;
  try {
    const entry: CacheEntry<T> = {
      value,
      expires_at: Date.now() + ttlMs,
      fetched_at: Date.now(),
    };
    localStorage.setItem(key(k), JSON.stringify(entry));
  } catch {
    // localStorage 满 / 不可用时静默降级
  }
}

/** 删除缓存。 */
export function deleteCache(k: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(key(k));
  } catch {}
}

/** 失效一个 key：删除缓存 + 广播 CustomEvent，所有订阅该 key 的 hook 立即标记 stale。
 *  写操作（如 addModel/updateAgentSettings）完成后调 bustCache 即可让所有
 *  useCachedResource("models", ...) 在下次读取时重新 fetch。
 */
export function bustCache(k: string): void {
  deleteCache(k);
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(BUST_EVENT, { detail: { key: k } }));
}

/** 订阅缓存失效事件。返回取消订阅函数。 */
export function onBust(cb: (key: string) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const handler = (e: Event) => {
    const ev = e as CustomEvent<{ key: string }>;
    cb(ev.detail?.key ?? "");
  };
  window.addEventListener(BUST_EVENT, handler);
  // 跨 tab 同步：storage 事件触发时也调一下 cb（key 为空表示全部失效）
  window.addEventListener("storage", handler as EventListener);
  return () => {
    window.removeEventListener(BUST_EVENT, handler);
    window.removeEventListener("storage", handler as EventListener);
  };
}
