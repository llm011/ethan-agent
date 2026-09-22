/**
 * 打开时间账本。
 *
 * 这个账本是「昨天开的才自动休息」唯一的证据来源，所以判错的方向很关键：
 * - 把今天开的记成昨天 → 会 discard 掉用户正在填的表单（数据丢）；
 * - 把昨天开的记成今天 → 少省点内存（无害）。
 * 两个用例钉住「缺记录时不要瞎补」和「读失败不要把已有记录冲掉」。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

/** storage.local 的假实现，记录每次 set 的内容。 */
let STORE: Record<string, unknown> = {};
let setCalls: Record<string, unknown>[] = [];
let getFails = false;

vi.mock('chrome', () => ({}));

function installChrome() {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    storage: {
      local: {
        get: async (key: string) => {
          if (getFails) throw new Error('storage unavailable');
          return key in STORE ? { [key]: STORE[key] } : {};
        },
        set: async (items: Record<string, unknown>) => {
          setCalls.push(items);
          Object.assign(STORE, items);
        },
      },
    },
  };
}

/**
 * 每个用例都要一个全新的模块实例（模块里 cache/persistTimer 都是模块级状态）。
 * vi.resetModules() 会让下一次 import 重新求值。
 */
async function freshModule() {
  vi.resetModules();
  return import('./tab-open-times');
}

beforeEach(() => {
  STORE = {};
  setCalls = [];
  getFails = false;
  installChrome();
});

describe('reconcileOpenTimes', () => {
  it('裁掉已不存在的 tab，保留还有效的记录', async () => {
    STORE.tabOpenTimes = { '1': 111, '2': 222 };
    const m = await freshModule();

    await m.reconcileOpenTimes([2, 3]);

    const snapshot = await m.snapshotOpenTimes();
    expect(snapshot.has(1)).toBe(false);
    expect(snapshot.get(2)).toBe(222);
  });

  it('不给没记录的存量 tab 补时间（补了会让它永远轮不到休息）', async () => {
    const m = await freshModule();

    await m.reconcileOpenTimes([1, 2]);

    const snapshot = await m.snapshotOpenTimes();
    expect(snapshot.size).toBe(0);
    expect(await m.getTabOpenedAt(1)).toBeUndefined();
  });

  it('不会把已有记录覆盖成「现在」', async () => {
    const longAgo = Date.UTC(2020, 0, 1);
    STORE.tabOpenTimes = { '7': longAgo };
    const m = await freshModule();

    await m.reconcileOpenTimes([7]);

    expect(await m.getTabOpenedAt(7)).toBe(longAgo);
  });
});

describe('读失败时不清空已有记录', () => {
  it('get 抛错时不写 storage，避免空表覆盖真实记录', async () => {
    STORE.tabOpenTimes = { '9': 999 };
    const m = await freshModule();
    getFails = true;

    // 触发一次写路径：读失败 → 不该让空表落盘
    await m.recordTabOpened(10);
    await m.flushOpenTimes();

    expect(setCalls).toEqual([]);
    expect(STORE.tabOpenTimes).toEqual({ '9': 999 });
  });

  it('读恢复后仍能拿到原来的记录（失败没有把 cache 钉成空的）', async () => {
    STORE.tabOpenTimes = { '9': 999 };
    const m = await freshModule();

    getFails = true;
    expect(await m.getTabOpenedAt(9)).toBeUndefined();

    getFails = false;
    expect(await m.getTabOpenedAt(9)).toBe(999);
  });
});

describe('写入', () => {
  it('flushOpenTimes 立刻落盘，不等防抖定时器', async () => {
    const m = await freshModule();

    await m.recordTabOpened(5, 12345);
    expect(setCalls).toEqual([]); // 防抖还没触发

    await m.flushOpenTimes();
    expect(setCalls).toHaveLength(1);
    expect(STORE.tabOpenTimes).toEqual({ '5': 12345 });
  });

  it('forgetTab 之后 flush，记录被删掉', async () => {
    STORE.tabOpenTimes = { '5': 12345 };
    const m = await freshModule();

    await m.forgetTab(5);
    await m.flushOpenTimes();

    expect(STORE.tabOpenTimes).toEqual({});
  });
});
