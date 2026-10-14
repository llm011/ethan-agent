/**
 * openTab 幂等去重测试。
 *
 * 钉的是用户遇到的 bug：上游在超时/断连「假失败」后重试同一个 open，而第一个 tab
 * 往往已经建好——不去重就每重试一次多开一个（同一地址被打开两三次）。
 * openTab 现在按规范化 URL 去重：同会话已有同 URL 的 tab 时复用并激活，不再新建。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

let TABS: Map<number, Record<string, unknown>> = new Map();
let NEXT_ID = 100;
const created: Array<Record<string, unknown>> = [];
const updated: Array<{ id: number; props: Record<string, unknown> }> = [];

vi.mock('chrome', () => ({}));

(globalThis as unknown as { chrome: unknown }).chrome = {
  tabs: {
    get: (id: number, cb: (t: unknown) => void) => {
      const t = TABS.get(id);
      const g = globalThis as unknown as { chrome: { runtime: { lastError: unknown } } };
      if (!t) {
        g.chrome.runtime.lastError = { message: `No tab with id: ${id}.` };
        cb(undefined);
        return;
      }
      g.chrome.runtime.lastError = undefined;
      cb(t);
    },
    query: (info: unknown, cb: (t: unknown[]) => void) => {
      const q = (info ?? {}) as { groupId?: number; windowId?: number };
      let all = Array.from(TABS.values());
      if (q.groupId !== undefined) all = all.filter(t => t.groupId === q.groupId);
      if (q.windowId !== undefined) all = all.filter(t => t.windowId === q.windowId);
      cb(all);
    },
    create: (props: Record<string, unknown>, cb: (t: unknown) => void) => {
      const id = NEXT_ID++;
      const tab = {
        id,
        windowId: props.windowId ?? 1,
        groupId: -1,
        active: props.active ?? false,
        url: props.url,
        title: String(props.url ?? ''),
      };
      TABS.set(id, tab);
      created.push(tab);
      (globalThis as unknown as { chrome: { runtime: { lastError: unknown } } }).chrome.runtime.lastError = undefined;
      cb(tab);
    },
    update: (id: number, props: Record<string, unknown>, cb: (t: unknown) => void) => {
      const t = TABS.get(id);
      updated.push({ id, props });
      if (t) {
        Object.assign(t, props);
      }
      (globalThis as unknown as { chrome: { runtime: { lastError: unknown } } }).chrome.runtime.lastError = undefined;
      cb(t);
    },
    group: (_opts: unknown, cb: (groupId: number) => void) => {
      const opts = (_opts ?? {}) as { groupId?: number; tabIds?: number[] };
      const gid = opts.groupId ?? 5;
      for (const tid of opts.tabIds ?? []) {
        const t = TABS.get(tid);
        if (t) t.groupId = gid;
      }
      cb(gid);
    },
    onRemoved: { addListener: () => {} },
    onCreated: { addListener: () => {} },
    onUpdated: { addListener: () => {} },
  },
  runtime: { lastError: undefined as unknown },
  storage: {
    local: {
      // 真实代码按 callback 风格调用（store-core 的 readStoredSessions/persist），
      // mock 必须回调，否则 persist 的 Promise 永不 resolve，openTab 会卡死（超时）。
      get: (_key: unknown, cb: (result: Record<string, unknown>) => void) => cb({}),
      set: (_items: unknown, cb: () => void) => cb(),
    },
  },
  tabGroups: {
    query: (_f: unknown, cb: (g: unknown[]) => void) => cb([]),
    update: (_id: number, _props: unknown, cb: () => void) => cb(),
  },
  debugger: { onDetach: { addListener: () => {} } },
};

async function freshStore() {
  const mod = await import('./store');
  return new mod.BrowserSessionStore();
}

function seedSession(store: unknown, groupId = 5, windowId = 1) {
  (store as { sessions: Map<string, unknown> }).sessions.set('s1', {
    sessionId: 's1',
    groupId,
    windowId,
    createdAt: Date.now(),
    updatedAt: Date.now(),
  });
  (store as { loaded: boolean }).loaded = true;
}

beforeEach(() => {
  TABS = new Map();
  NEXT_ID = 100;
  created.length = 0;
  updated.length = 0;
});

describe('openTab 幂等去重', () => {
  it('首次打开某 URL 会新建 tab', async () => {
    const store = await freshStore();
    seedSession(store);
    // session 组里先放一个占位 tab，reconcile 要求组非空
    TABS.set(1, { id: 1, windowId: 1, groupId: 5, active: true, url: 'https://seed', title: 'seed' });

    const out = await store.openTab({ sessionId: 's1', url: 'https://example.com/a' });

    expect(out.opened).toBe(true);
    expect(out.reused).toBeUndefined();
    expect(created).toHaveLength(1);
    expect(out.tab.url).toBe('https://example.com/a');
  });

  it('重试打开同一 URL 不再新建，复用已有 tab 并标记 reused', async () => {
    const store = await freshStore();
    seedSession(store);
    TABS.set(1, { id: 1, windowId: 1, groupId: 5, active: true, url: 'https://seed', title: 'seed' });

    const first = await store.openTab({ sessionId: 's1', url: 'https://example.com/a' });
    const firstTabId = first.tab.tabId;
    expect(created).toHaveLength(1);

    // 模拟「假失败后重试」：同一 URL 再 open 一次
    const second = await store.openTab({ sessionId: 's1', url: 'https://example.com/a' });

    expect(second.reused).toBe(true);
    expect(second.tab.tabId).toBe(firstTabId);
    expect(created).toHaveLength(1); // 关键：没有第二个 tab
  });

  it('URL 仅 hash / 末尾斜杠不同视为同一页，去重复用', async () => {
    const store = await freshStore();
    seedSession(store);
    TABS.set(1, { id: 1, windowId: 1, groupId: 5, active: true, url: 'https://seed', title: 'seed' });

    await store.openTab({ sessionId: 's1', url: 'https://example.com/a/' });
    const dup = await store.openTab({ sessionId: 's1', url: 'https://example.com/a#section' });

    expect(dup.reused).toBe(true);
    expect(created).toHaveLength(1);
  });

  it('active:true 复用时会激活已有 tab', async () => {
    const store = await freshStore();
    seedSession(store);
    TABS.set(1, { id: 1, windowId: 1, groupId: 5, active: true, url: 'https://seed', title: 'seed' });

    const first = await store.openTab({ sessionId: 's1', url: 'https://example.com/a' });
    await store.openTab({ sessionId: 's1', url: 'https://example.com/a', active: true });

    expect(updated.some(u => u.id === first.tab.tabId && u.props.active === true)).toBe(true);
    expect(created).toHaveLength(1);
  });

  it('不同 URL 仍各自新建', async () => {
    const store = await freshStore();
    seedSession(store);
    TABS.set(1, { id: 1, windowId: 1, groupId: 5, active: true, url: 'https://seed', title: 'seed' });

    await store.openTab({ sessionId: 's1', url: 'https://example.com/a' });
    await store.openTab({ sessionId: 's1', url: 'https://example.com/b' });

    expect(created).toHaveLength(2);
  });
});
