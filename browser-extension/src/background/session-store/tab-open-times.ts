/**
 * tab「打开时间」账本。
 *
 * Chrome **不暴露** tab 的打开时间：`tab.lastAccessed` 是「最近一次被访问」，
 * 一个昨天打开、今天点过一下的 tab 会被它报成今天。要按「昨天及更早打开的」
 * 这个判据做自动休息，就必须自己记。
 *
 * 记账时机：`chrome.tabs.onCreated`。存量（本版本装上之前就开着的 tab）没有记录，
 * 判据那边把「没有记录」当「今天」处理 —— 拿不到证据就不动手，方向保守。
 * 不用 `tab.lastAccessed` 兜底：它是「最近访问」且对后台 tab 长时间不刷新，
 * 偏旧，会把昨天开着、正在填表的 tab 判成「昨天的」而 discard。
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

/**
 * 读账本。读失败**不缓存**空表：一次瞬时失败就把 cache 钉成空的，本次会话后续
 * 所有查询都会报「没有记录」（判据那边按「今天」处理，安全），但如果此时恰好
 * 有写操作，就会把空表覆盖回 storage，把真实记录冲掉。所以失败只让这一次
 * 调用拿到空表，下次再来读。
 */
async function load(): Promise<Map<number, number>> {
  if (cache) return cache;
  try {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    cache = fromRecord((stored[STORAGE_KEY] as OpenTimeMap | undefined) ?? {});
  } catch {
    return new Map();
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

/**
 * 立刻把待写内容落盘。
 *
 * 给「SW 要被回收了」这一类时机用：上面那个 500ms 防抖定时器会随 SW 一起消失，
 * 没触发就等于这次记录丢了 —— 而丢一条 onCreated 记录的后果不只是少一条数据，
 * 是那个 tab 之后再也轮不到自动休息（见 reconcileOpenTimes 的说明）。
 */
export async function flushOpenTimes(): Promise<void> {
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
  await persistNow();
}

async function persistNow(): Promise<void> {
  // cache 还是 null 说明从没成功读过账本，这时写下去只会把已有记录冲掉。
  if (!cache) return;
  try {
    await chrome.storage.local.set({ [STORAGE_KEY]: toRecord(cache) });
  } catch {
    // 写失败不影响本次会话的内存账本；代价是这次修改丢了，下次 SW 重启后
    // 这些 tab 会被当成「没有记录」（判据按「今天」处理，方向保守）。
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
 * 用「当前真实存在的 tab」裁剪账本。
 *
 * 只做一件事：删掉已不存在的 tabId。不做「给没记录的补一条」——
 * 补出来的时间只能是「现在」，而没记录不代表 tab 是刚打开的（可能是 onCreated
 * 那条记录还没落盘 SW 就被回收了，或者只是这一版装上之前就开着的）。补成
 * 「现在」会让这个 tab 每次 SW 重启都重新变成「今天打开的」，于是**永远**轮不到
 * 自动休息。宁可缺记录：判据那边把 undefined 当「今天」处理，方向是安全的。
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
  if (changed) schedulePersist();
}

/** 仅供测试/诊断：拿到当前整张账本。 */
export async function snapshotOpenTimes(): Promise<Map<number, number>> {
  return new Map(await load());
}
