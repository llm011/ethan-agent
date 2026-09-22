/**
 * tab「打开时间」账本。
 *
 * Chrome **不暴露** tab 的打开时间：`tab.lastAccessed` 是「最近一次被访问」，
 * 一个昨天打开、今天点过一下的 tab 会被它报成今天。要按「昨天及更早打开的」
 * 这个判据做自动休息，就必须自己记。
 *
 * 记账时机：`chrome.tabs.onCreated`。存量（本版本装上之前就开着的 tab）没记录，
 * 由调用方回退到 `lastAccessed` —— 两者都只会让判断**更保守**（更旧才动手），
 * 不会把今天的 tab 误判成昨天的。
 *
 * tab id 只在浏览器会话内唯一，浏览器重启后会重置，所以账本必须跟着会话清：
 * 每次 service worker 启动时用当前真实存在的 tab 集合裁剪一遍。
 */
const STORAGE_KEY = 'tabOpenTimes';

/** tabId → 打开时间（ms epoch）。 */
type OpenTimeMap = Record<string, number>;

let cache: Map<number, number> | null = null;

function fromRecord(record: OpenTimeMap): Map<number, number> {
  const out = new Map<number, number>();
  for (const [k, v] of Object.entries(record)) {
    const id = Number(k);
    if (Number.isFinite(id) && typeof v === 'number' && v > 0) out.set(id, v);
  }
  return out;
}

function toRecord(map: Map<number, number>): OpenTimeMap {
  const out: OpenTimeMap = {};
  for (const [k, v] of map) out[String(k)] = v;
  return out;
}

async function load(): Promise<Map<number, number>> {
  if (cache) return cache;
  try {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    cache = fromRecord((stored[STORAGE_KEY] as OpenTimeMap | undefined) ?? {});
  } catch {
    // storage 不可用：本次会话退化为「全都没有记录」，调用方回退到 lastAccessed。
    cache = new Map();
  }
  return cache;
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;

function schedulePersist(): void {
  // onCreated 可能连着触发（恢复一整批 tab），合并成一次写入。
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    persistTimer = null;
    void persistNow();
  }, 500);
}

async function persistNow(): Promise<void> {
  if (!cache) return;
  try {
    await chrome.storage.local.set({ [STORAGE_KEY]: toRecord(cache) });
  } catch {
    // 写失败不影响本次会话的内存账本；下次 SW 重启会退回 lastAccessed。
  }
}

/** 记下某个 tab 的打开时间。 */
export async function recordTabOpened(
  tabId: number,
  at: number = Date.now(),
): Promise<void> {
  const map = await load();
  map.set(tabId, at);
  schedulePersist();
}

/** 某个 tab 被关掉了，从账本里去掉。 */
export async function forgetTab(tabId: number): Promise<void> {
  const map = await load();
  if (map.delete(tabId)) schedulePersist();
}

/** 取某个 tab 的打开时间；没有记录返回 undefined。 */
export async function getTabOpenedAt(
  tabId: number,
): Promise<number | undefined> {
  const map = await load();
  return map.get(tabId);
}

/**
 * 用「当前真实存在的 tab」裁剪账本，并给没有记录的补上一条。
 *
 * 两件事都要做：
 * - 删掉已不存在的 tabId，避免浏览器重启后 id 复用导致把新 tab 当成旧的；
 * - 给没记录的存量 tab 补一条 **现在** 的时间 —— 不能补成很久以前，
 *   否则刚装上的那一刻会把一堆老 tab 全判成「昨天的」而集体休息。
 *   补成「现在」的代价是：这些存量 tab 要等到明天才会被自动休息，方向是安全的。
 */
export async function reconcileOpenTimes(
  liveTabIds: number[],
): Promise<void> {
  const map = await load();
  const live = new Set(liveTabIds);
  let changed = false;
  for (const id of Array.from(map.keys())) {
    if (!live.has(id)) {
      map.delete(id);
      changed = true;
    }
  }
  const now = Date.now();
  for (const id of liveTabIds) {
    if (!map.has(id)) {
      map.set(id, now);
      changed = true;
    }
  }
  if (changed) schedulePersist();
}

/** 仅供测试/诊断：拿到当前整张账本。 */
export async function snapshotOpenTimes(): Promise<Map<number, number>> {
  return new Map(await load());
}
