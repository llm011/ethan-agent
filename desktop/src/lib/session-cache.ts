/**
 * Session 消息本地缓存 — 桌面端切换会话时先渲染缓存，后台 SWR 刷新。
 *
 * 策略：
 * - 以 sessionId 为 key，存完整 SessionDetail（messages / title / model 等）
 * - LRU 限制条目数（MAX_ENTRIES），防止 localStorage 膨胀
 * - TTL 控制新鲜度：未过期直接渲染；过期仍渲染但标记 stale → 后台 refetch
 * - 写入时机：fetchSession 成功、streaming 完成、发送新消息
 *
 * 注意：桌面端 Tauri webview localStorage 没有 5MB 限制，
 * 但单条会话消息量大时仍需留意，故限制 MAX_ENTRIES 而非无限缓存。
 */

import { mergeOlderMessagesIntoCache } from "@ethan/shared/chat/history";
import type { SessionDetail } from "./api-sessions";

const CACHE_PREFIX = "ethan_session:";
const INDEX_KEY = "ethan_session_index"; // LRU order
const MAX_ENTRIES = 20; // 最多缓存 20 条会话
const TTL_MS = 5 * 60 * 1000; // 5 分钟

interface CacheEntry {
  detail: SessionDetail;
  cachedAt: number;
}

/** 读取 LRU 索引（sessionId 数组，头部是最近访问的） */
function readIndex(): string[] {
  try {
    const raw = localStorage.getItem(INDEX_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function writeIndex(ids: string[]): void {
  try {
    localStorage.setItem(INDEX_KEY, JSON.stringify(ids));
  } catch {}
}

/** 将 sessionId 移到 LRU 头部 */
function touchIndex(id: string): void {
  const idx = readIndex().filter((x) => x !== id);
  idx.unshift(id);
  // 淘汰超出 MAX_ENTRIES 的尾部条目
  while (idx.length > MAX_ENTRIES) {
    const evicted = idx.pop()!;
    try {
      localStorage.removeItem(CACHE_PREFIX + evicted);
    } catch {}
  }
  writeIndex(idx);
}

/** 读取会话缓存。返回 null 表示未命中。 */
export function readSessionCache(sessionId: string): { detail: SessionDetail; stale: boolean } | null {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + sessionId);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    const stale = Date.now() - entry.cachedAt > TTL_MS;
    return { detail: entry.detail, stale };
  } catch {
    return null;
  }
}

/** 写入会话缓存（覆盖）。 */
export function writeSessionCache(sessionId: string, detail: SessionDetail): void {
  try {
    const entry: CacheEntry = { detail, cachedAt: Date.now() };
    localStorage.setItem(CACHE_PREFIX + sessionId, JSON.stringify(entry));
    touchIndex(sessionId);
  } catch {
    // localStorage 写入失败时静默降级
  }
}

/** 更新缓存中的 messages（追加/替换），保留其他字段。 */
export function updateSessionCacheMessages(
  sessionId: string,
  updater: (prev: SessionDetail) => SessionDetail,
): void {
  const cached = readSessionCache(sessionId);
  if (!cached) return;
  try {
    const updated = updater(cached.detail);
    writeSessionCache(sessionId, updated);
  } catch {}
}

/**
 * 把一页消息并入**已有**的全量缓存；没有缓存则什么都不做。
 *
 * 缓存语义是「整个会话」。分页结果只有最近 N 条，直接 writeSessionCache 会把全量
 * 缓存降级成残页（离线打开长会话只剩 30 条，更早历史永久不可达）。所以分页路径
 * 只**合并**、不覆盖：
 * - 按 id 合并进旧 messages（新页优先，覆盖流式期间的中间态）
 * - 裁剪到全量缓存原本的最旧 id 以内，避免把「缓存覆盖到 id=5」悄悄扩成「到 id=1
 *   但中间 2..4 缺失」，那会让离线阅读出现空洞
 * - 没有缓存时保持没有——宁可离线无缓存，也不要一份残缺缓存
 */
export function mergeSessionPageIntoCache(sessionId: string, page: SessionDetail): void {
  const cached = readSessionCache(sessionId);
  if (!cached) return;
  // 合并规则是纯函数，收在 @ethan/shared 里（两端共用 + 单测），这里只管存储
  const merged = mergeOlderMessagesIntoCache(cached.detail.messages, page.messages);
  if (!merged) return;
  try {
    writeSessionCache(sessionId, { ...cached.detail, ...page, messages: merged });
  } catch {}
}

/** 删除指定会话的缓存。 */
export function deleteSessionCache(sessionId: string): void {
  try {
    localStorage.removeItem(CACHE_PREFIX + sessionId);
    const idx = readIndex().filter((x) => x !== sessionId);
    writeIndex(idx);
  } catch {}
}

/** 清除所有会话缓存。 */
export function clearSessionCache(): void {
  const idx = readIndex();
  for (const id of idx) {
    try {
      localStorage.removeItem(CACHE_PREFIX + id);
    } catch {}
  }
  writeIndex([]);
}
