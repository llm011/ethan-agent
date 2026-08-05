/** 离线数据层：IndexedDB + LRU 会话缓存。
 * 用 IndexedDB 而非 localStorage，避免 5MB 上限（IndexedDB 可存数百 MB）。
 * 所有操作静默失败（reject → resolve null），绝不抛错影响主流程。
 */

import type { SessionDetail, SessionInfo } from "./api-sessions";

const DB_NAME = "ethan-offline";
const DB_VERSION = 1;
const STORE_SESSIONS = "sessions";
const STORE_LISTS = "session-lists";

const MAX_SESSION_DETAILS = 30;
const MAX_LISTS = 10;

/** 会话详情记录：{id, detail, accessedAt} */
interface SessionRecord {
  id: string;
  detail: SessionDetail;
  accessedAt: number;
}

/** 列表查询记录：{key, sessions, accessedAt} */
interface ListRecord {
  key: string;
  sessions: SessionInfo[];
  accessedAt: number;
}

/** 打开/升级 IndexedDB，SSR 或失败时返回 null。 */
function getDB(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    if (typeof indexedDB === "undefined") {
      resolve(null);
      return;
    }
    try {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_SESSIONS)) {
          db.createObjectStore(STORE_SESSIONS, { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains(STORE_LISTS)) {
          db.createObjectStore(STORE_LISTS, { keyPath: "key" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

/** 通用 store 操作封装，错误自动 resolve null。 */
function withStore<T>(
  storeName: string,
  mode: IDBTransactionMode,
  fn: (store: IDBObjectStore) => IDBRequest | Promise<T>,
): Promise<T | null> {
  return getDB().then(
    (db) =>
      new Promise<T | null>((resolve) => {
        if (!db) {
          resolve(null);
          return;
        }
        try {
          const tx = db.transaction(storeName, mode);
          const store = tx.objectStore(storeName);
          const result = fn(store);
          if (result instanceof Promise) {
            result.then(resolve, () => resolve(null));
          } else {
            result.onsuccess = () => resolve((result as IDBRequest).result as T);
            result.onerror = () => resolve(null);
          }
        } catch {
          resolve(null);
        }
      }),
  );
}

/** LRU 淘汰：按 accessedAt 升序，删除超出上限的最旧记录。
 * 不走 withStore：withStore 会覆盖 getAll.onsuccess，导致淘汰逻辑永不执行。
 * 改用独立事务，靠 tx.oncomplete resolve。
 */
function evictLRU(storeName: string, max: number): Promise<void> {
  return new Promise((resolve) => {
    getDB().then((db) => {
      if (!db) {
        resolve();
        return;
      }
      try {
        const tx = db.transaction(storeName, "readwrite");
        const store = tx.objectStore(storeName);
        const getAll = store.getAll();
        getAll.onsuccess = () => {
          const records = (getAll.result as Array<{ accessedAt: number; id?: string; key?: string }>) || [];
          if (records.length <= max) return;
          const sorted = [...records].sort((a, b) => a.accessedAt - b.accessedAt);
          const toDelete = sorted.slice(0, records.length - max);
          for (const r of toDelete) {
            const pk = r.id ?? r.key;
            if (pk !== undefined) store.delete(pk);
          }
        };
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
      } catch {
        resolve();
      }
    });
  });
}

/** 读取会话详情；命中时更新 accessedAt（LRU touch）。 */
export async function readSessionDetail(sessionId: string): Promise<SessionDetail | null> {
  const record = await withStore<SessionRecord>(STORE_SESSIONS, "readonly", (store) => store.get(sessionId));
  if (!record) return null;
  // LRU touch：异步更新 accessedAt，失败不影响读取
  withStore(STORE_SESSIONS, "readwrite", (store) => {
    record.accessedAt = Date.now();
    return store.put(record);
  });
  return record.detail;
}

/** 写入会话详情，并触发 LRU 淘汰。 */
export async function writeSessionDetail(sessionId: string, detail: SessionDetail): Promise<void> {
  const record: SessionRecord = { id: sessionId, detail, accessedAt: Date.now() };
  await withStore(STORE_SESSIONS, "readwrite", (store) => store.put(record));
  evictLRU(STORE_SESSIONS, MAX_SESSION_DETAILS);
}

/** 基于旧值更新会话详情；不存在则跳过。 */
export async function updateSessionDetail(
  sessionId: string,
  updater: (prev: SessionDetail) => SessionDetail,
): Promise<void> {
  const record = await withStore<SessionRecord>(STORE_SESSIONS, "readonly", (store) => store.get(sessionId));
  if (!record) return;
  const next: SessionRecord = { id: sessionId, detail: updater(record.detail), accessedAt: Date.now() };
  await withStore(STORE_SESSIONS, "readwrite", (store) => store.put(next));
}

/** 删除单个会话详情。 */
export async function deleteSessionDetail(sessionId: string): Promise<void> {
  await withStore(STORE_SESSIONS, "readwrite", (store) => store.delete(sessionId));
}

/** 构造列表查询的缓存 key。 */
export function makeListKey(params: {
  limit?: number;
  offset?: number;
  q?: string;
  source?: string;
  mode?: string;
  hideHeartbeat?: boolean;
  hideScheduled?: boolean;
  titlePrefixes?: string;
}): string {
  const parts = [
    `l=${params.limit ?? 50}`,
    `o=${params.offset ?? 0}`,
    `q=${params.q ?? ""}`,
    `s=${params.source ?? ""}`,
    `m=${params.mode ?? ""}`,
    `hb=${params.hideHeartbeat ? "1" : "0"}`,
    `hs=${params.hideScheduled ? "1" : "0"}`,
    `tp=${params.titlePrefixes ?? ""}`,
  ];
  return parts.join("|");
}

/** 读取列表查询缓存；命中时更新 accessedAt。 */
export async function readSessionList(key: string): Promise<SessionInfo[] | null> {
  const record = await withStore<ListRecord>(STORE_LISTS, "readonly", (store) => store.get(key));
  if (!record) return null;
  withStore(STORE_LISTS, "readwrite", (store) => {
    record.accessedAt = Date.now();
    return store.put(record);
  });
  return record.sessions;
}

/** 写入列表查询缓存，并触发 LRU 淘汰。 */
export async function writeSessionList(key: string, sessions: SessionInfo[]): Promise<void> {
  const record: ListRecord = { key, sessions, accessedAt: Date.now() };
  await withStore(STORE_LISTS, "readwrite", (store) => store.put(record));
  evictLRU(STORE_LISTS, MAX_LISTS);
}

/** 是否处于离线状态。SSR 环境下返回 false（不影响逻辑，仅控制缓存降级）。 */
export function isOffline(): boolean {
  if (typeof navigator === "undefined") return false;
  return !navigator.onLine;
}
