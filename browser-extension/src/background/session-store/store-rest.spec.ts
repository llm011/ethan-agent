/**
 * organizeTabs 里 rest 相关分支的集成测试。
 *
 * 判据逻辑本身在 tab-rest.spec.ts 里单测；这里钉的是**接线**：
 * 哪些 tab 真的走到了 chrome.tabs.discard、哪些被保护名单拦下、
 * 以及 restMode='off' 时自动档确实不动手。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const discarded: number[] = [];

/** 每个 tabId 对应的假 tab。 */
let TABS: Map<number, Record<string, unknown>> = new Map();

function makeTab(over: Record<string, unknown> & { id: number }) {
  return {
    windowId: 1,
    groupId: -1,
    active: false,
    audible: false,
    pinned: false,
    discarded: false,
    autoDiscardable: true,
    url: 'https://example.com/a',
    title: 'A',
    ...over,
  };
}

vi.mock('chrome', () => ({}));

// 在 import store 之前把全局 chrome 装好 —— 模块顶层会读 chrome.tabs。
(globalThis as unknown as { chrome: unknown }).chrome = {
  tabs: {
    get: (id: number, cb: (t: unknown) => void) => {
      const t = TABS.get(id);
      if (!t) {
        // 模拟 chrome.runtime.lastError
        (globalThis as unknown as { chrome: { runtime: { lastError: unknown } } }).chrome.runtime.lastError = {
          message: `No tab with id: ${id}.`,
        };
        cb(undefined);
        return;
      }
      (globalThis as unknown as { chrome: { runtime: { lastError: unknown } } }).chrome.runtime.lastError = undefined;
      cb(t);
    },
    query: (info: unknown, cb: (t: unknown[]) => void) => {
      const q = (info ?? {}) as { groupId?: number };
      const all = Array.from(TABS.values());
      cb(
        q.groupId === undefined
          ? all
          : all.filter(t => t.groupId === q.groupId),
      );
    },
    discard: (id: number, cb: (t: unknown) => void) => {
      const t = TABS.get(id);
      if (!t) {
        cb(undefined);
        return;
      }
      // 真实 Chrome 不会 discard 活跃 tab；这里如实模拟，好让测试暴露依赖它的实现。
      if (t.active) {
        cb(undefined);
        return;
      }
      discarded.push(id);
      cb({ ...t, discarded: true });
    },
    onRemoved: { addListener: () => {} },
    onCreated: { addListener: () => {} },
    onUpdated: { addListener: () => {} },
  },
  runtime: { lastError: undefined as unknown },
  storage: {
    local: { get: async () => ({}), set: async () => {} },
  },
  tabGroups: { query: (_f: unknown, cb: (g: unknown[]) => void) => cb([]) },
  debugger: { onDetach: { addListener: () => {} } },
};

// 每个用例都用一个全新的 store 实例（避免单例状态串味）
async function freshStore() {
  const mod = await import('./store');
  return new mod.BrowserSessionStore();
}

/** 造一个 session 占住 groupId，供 liveSessionTabIds 使用。 */
function seedSession(store: unknown, groupId: number) {
  // sessions 是 protected，测试里只能绕过类型访问。
  (store as { sessions: Map<string, unknown> }).sessions.set('s1', {
    sessionId: 's1',
    groupId,
    windowId: 1,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  });
}

const YESTERDAY = Date.now() - 26 * 60 * 60 * 1000;

beforeEach(() => {
  discarded.length = 0;
  TABS = new Map();
});

describe('organizeTabs rest 分支', () => {
  it('显式 rest 会 discard 这些 tab', async () => {
    TABS.set(10, makeTab({ id: 10 }));
    TABS.set(11, makeTab({ id: 11 }));
    const store = await freshStore();

    const out = await store.organizeTabs({
      ops: [{ op: 'rest', tabs: [10, 11] }],
    });

    expect(discarded.sort()).toEqual([10, 11]);
    expect(out.applied.rest.rested.sort()).toEqual([10, 11]);
    expect(out.applied.rest.restSkipped).toEqual([]);
  });

  it('活跃 tab 即使被显式点名也不 discard（Chrome 也不会让你 discard）', async () => {
    TABS.set(10, makeTab({ id: 10, active: true }));
    TABS.set(11, makeTab({ id: 11 }));
    const store = await freshStore();

    const out = await store.organizeTabs({
      ops: [{ op: 'rest', tabs: [10, 11] }],
    });

    expect(discarded).toEqual([11]);
    expect(out.applied.rest.restSkipped).toEqual([
      { tabId: 10, reason: '是当前正在看的标签' },
    ]);
  });

  it('出声的、固定的 tab 不动', async () => {
    TABS.set(10, makeTab({ id: 10, audible: true }));
    TABS.set(11, makeTab({ id: 11, pinned: true }));
    TABS.set(12, makeTab({ id: 12 }));
    const store = await freshStore();

    const out = await store.organizeTabs({
      ops: [{ op: 'rest', tabs: [10, 11, 12] }],
    });

    expect(discarded).toEqual([12]);
    // 按 tabId 比而不是按 reason 字符串排序：中文的 locale 排序结果和字面量
    // 顺序不一致，用 code point 排出来的次序跟写在这里的两行对不上。
    expect(out.applied.rest.restSkipped).toEqual([
      { tabId: 10, reason: '正在播放声音' },
      { tabId: 11, reason: '已被固定' },
    ]);
  });

  it('正被 session 占用的 tab 不动（会打断正在跑的流程）', async () => {
    TABS.set(10, makeTab({ id: 10, groupId: 5 }));
    TABS.set(11, makeTab({ id: 11, groupId: -1 }));
    const store = await freshStore();
    seedSession(store, 5);

    const out = await store.organizeTabs({
      ops: [{ op: 'rest', tabs: [10, 11] }],
    });

    expect(discarded).toEqual([11]);
    expect(out.applied.rest.restSkipped).toEqual([
      { tabId: 10, reason: '正被 Ethan 会话或调试器使用' },
    ]);
  });

  it('不存在的 tab 记进 restFailed', async () => {
    TABS.set(11, makeTab({ id: 11 }));
    const store = await freshStore();

    const out = await store.organizeTabs({
      ops: [{ op: 'rest', tabs: [999, 11] }],
    });

    expect(discarded).toEqual([11]);
    expect(out.applied.rest.restFailed).toHaveLength(1);
    expect(out.applied.rest.restFailed[0].tabId).toBe(999);
  });
});

describe('rest_auto 与开关', () => {
  it('restMode=off 时自动档一个都不动，并说明原因', async () => {
    TABS.set(10, makeTab({ id: 10, groupId: 5 }));
    TABS.set(11, makeTab({ id: 11, groupId: 5 }));
    const store = await freshStore();

    const out = await store.organizeTabs({
      ops: [{ op: 'rest_auto', groupId: 5 }],
      restMode: 'off',
    });

    expect(discarded).toEqual([]);
    expect(out.applied.rest.restSkipped).toHaveLength(2);
  });

  it('rest_group 是显式指令，不受 restMode=off 影响', async () => {
    TABS.set(10, makeTab({ id: 10, groupId: 5 }));
    const store = await freshStore();

    const out = await store.organizeTabs({
      ops: [{ op: 'rest_group', groupId: 5 }],
      restMode: 'off',
    });

    expect(discarded).toEqual([10]);
    expect(out.applied.rest.rested).toEqual([10]);
  });

  it('rest_auto 在组已不存在时不做任何事', async () => {
    const store = await freshStore();
    const out = await store.organizeTabs({
      ops: [{ op: 'rest_auto', groupId: 77 }],
    });
    expect(discarded).toEqual([]);
    expect(out.applied.rest.rested).toEqual([]);
  });
});
