import { describe, expect, it } from 'vitest';
import {
  dedupeKey,
  excludeOpenTabs,
  filterToday,
  normalizeClosedAt,
  searchTabsWithHistory,
  toClosedEntries,
  type ClosedTabEntry,
} from './tab-history';
import type { BrowserSessionTab } from '../../shared';

function tab(tabId: number, url: string, title = ''): BrowserSessionTab {
  return { tabId, windowId: 1, url, title };
}

function closed(tabId: number, url: string, hoursAgo: number, title = ''): ClosedTabEntry {
  // 固定一个基准时刻，避免测试跨零点时抖动
  const now = new Date('2026-09-24T15:00:00').getTime();
  return { tab: tab(tabId, url, title), closedAt: now - hoursAgo * 3600_000 };
}

const TODAY = new Date('2026-09-24T15:00:00').getTime();

describe('dedupeKey', () => {
  it('忽略 hash', () => {
    expect(dedupeKey('https://a.com/x#p1')).toBe(dedupeKey('https://a.com/x#p2'));
  });

  it('根路径的末尾斜杠视为同一页', () => {
    expect(dedupeKey('https://a.com/')).toBe(dedupeKey('https://a.com'));
  });

  it('非根路径的末尾斜杠不吞掉', () => {
    expect(dedupeKey('https://a.com/x/')).not.toBe(dedupeKey('https://a.com/x'));
  });

  it('query 不同视为不同页', () => {
    expect(dedupeKey('https://a.com/s?q=1')).not.toBe(dedupeKey('https://a.com/s?q=2'));
  });

  it('非标准 URL 原样返回', () => {
    expect(dedupeKey('chrome://extensions')).toBe('chrome://extensions');
  });

  it('空值返回空串', () => {
    expect(dedupeKey(undefined)).toBe('');
    expect(dedupeKey('')).toBe('');
  });
});

describe('excludeOpenTabs', () => {
  it('去掉现在还开着的', () => {
    const out = excludeOpenTabs(
      [closed(9, 'https://a.com/', 1), closed(8, 'https://b.com/', 1)],
      [tab(1, 'https://a.com')],
    );
    expect(out.map(c => c.tab.tabId)).toEqual([8]);
  });

  it('去重时忽略 hash', () => {
    const out = excludeOpenTabs(
      [closed(9, 'https://a.com/x#sec', 1)],
      [tab(1, 'https://a.com/x')],
    );
    expect(out).toEqual([]);
  });

  it('同一条历史里重复的 URL 只留一次', () => {
    const out = excludeOpenTabs(
      [closed(9, 'https://a.com/', 1), closed(8, 'https://a.com/#x', 2)],
      [],
    );
    expect(out).toHaveLength(1);
  });

  it('没有 url 的条目直接丢掉', () => {
    const out = excludeOpenTabs([{ tab: tab(9, ''), closedAt: TODAY }, closed(8, 'https://b.com', 1)], []);
    expect(out.map(c => c.tab.tabId)).toEqual([8]);
  });
});

describe('filterToday', () => {
  it('保留今天关闭的', () => {
    const out = filterToday([closed(9, 'https://a.com', 2)], TODAY);
    expect(out).toHaveLength(1);
  });

  it('丢掉昨天及更早关闭的', () => {
    // 15:00 往前推 20 小时 = 昨天 19:00
    const out = filterToday([closed(9, 'https://a.com', 20)], TODAY);
    expect(out).toEqual([]);
  });

  it('保留当天 00:00 之后的边界点', () => {
    const midnight = new Date('2026-09-24T00:00:00').getTime();
    const out = filterToday([{ tab: tab(9, 'https://a.com'), closedAt: midnight }], TODAY);
    expect(out).toHaveLength(1);
  });

  it('丢掉 00:00 之前的一毫秒', () => {
    const justBefore = new Date('2026-09-24T00:00:00').getTime() - 1;
    const out = filterToday([{ tab: tab(9, 'https://a.com'), closedAt: justBefore }], TODAY);
    expect(out).toEqual([]);
  });
});

describe('searchTabsWithHistory', () => {
  const openTabs = [tab(1, 'https://github.com/foo/bar', 'foo/bar: a repo')];
  const closedTabs = [
    closed(90, 'https://github.com/foo/issue', 1, 'Issue 42'),
    closed(91, 'https://news.example.com', 1, 'News'),
  ];

  it('开关关闭时不查历史', () => {
    const res = searchTabsWithHistory(openTabs, closedTabs, { query: 'issue' }, new Map(), TODAY);
    expect(res.matches).toEqual([]);
    expect(res.total).toBe(0);
  });

  it('开关关闭时结果都标 open', () => {
    const res = searchTabsWithHistory(openTabs, closedTabs, { query: 'repo' }, new Map(), TODAY);
    expect(res.matches).toHaveLength(1);
    expect(res.matches[0]!.source).toBe('open');
    expect(res.matches[0]!.closedAt).toBeUndefined();
  });

  it('开关打开时能搜到历史，并标 closed + 关闭时间', () => {
    const res = searchTabsWithHistory(
      openTabs,
      closedTabs,
      { query: 'issue', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches).toHaveLength(1);
    expect(res.matches[0]!.source).toBe('closed');
    expect(res.matches[0]!.tab.tabId).toBe(90);
    expect(typeof res.matches[0]!.closedAt).toBe('number');
  });

  it('开关打开时历史里「还开着」的不重复出现', () => {
    // github.com/foo/bar 现在开着，历史里也有一条同 URL
    const dup = closed(92, 'https://github.com/foo/bar#readme', 1, 'foo/bar: a repo');
    const res = searchTabsWithHistory(
      openTabs,
      [dup, ...closedTabs],
      { query: 'repo', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches).toHaveLength(1);
    expect(res.matches[0]!.source).toBe('open');
    expect(res.matches[0]!.tab.tabId).toBe(1);
  });

  it('开关打开时昨天的历史搜不到', () => {
    const res = searchTabsWithHistory(
      openTabs,
      [closed(93, 'https://old.example.com', 20, 'Old page')],
      { query: 'old', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches).toEqual([]);
  });

  it('同分时还开着的排在历史前面', () => {
    const both = [
      tab(1, 'https://a.com/shared', 'shared page'),
      tab(2, 'https://b.com/other', 'other'),
    ];
    const hist = [closed(90, 'https://c.com/shared', 1, 'shared page')];
    const res = searchTabsWithHistory(
      both,
      hist,
      { query: 'shared', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches.map(m => m.source)).toEqual(['open', 'closed']);
  });

  it('total / scanned 把历史也算进去', () => {
    // open 里 2 个参与扫描，历史里 1 个（另一个不是今天）
    const res = searchTabsWithHistory(
      openTabs,
      closedTabs,
      { query: 'foo', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.scanned).toBe(openTabs.length + closedTabs.length);
  });

  it('历史命中不计入 total 之外的截断判断', () => {
    const res = searchTabsWithHistory(
      openTabs,
      closedTabs,
      { query: 'issue', includeClosed: true, limit: 50 },
      new Map(),
      TODAY,
    );
    expect(res.truncated).toBe(false);
  });
});

describe('normalizeClosedAt', () => {
  it('秒级时间戳 ×1000', () => {
    // 2026-09-24T15:00:00Z 的秒级表示
    expect(normalizeClosedAt(Math.floor(TODAY / 1000))).toBe(Math.floor(TODAY / 1000) * 1000);
  });

  it('毫秒级时间戳原样返回', () => {
    expect(normalizeClosedAt(TODAY)).toBe(TODAY);
  });

  it('两种单位归一后都落在「今天」里', () => {
    const secs = Math.floor(TODAY / 1000);
    const fromSec = filterToday([{ tab: tab(1, 'https://a.com'), closedAt: normalizeClosedAt(secs) }], TODAY);
    const fromMs = filterToday([{ tab: tab(1, 'https://a.com'), closedAt: normalizeClosedAt(TODAY) }], TODAY);
    expect(fromSec).toHaveLength(1);
    expect(fromMs).toHaveLength(1);
  });

  it('脏数据返回 0（会被 filterToday 丢掉）', () => {
    expect(normalizeClosedAt(undefined)).toBe(0);
    expect(normalizeClosedAt(0)).toBe(0);
    expect(normalizeClosedAt(Number.NaN)).toBe(0);
  });
});

describe('合并后的 limit', () => {
  function manyOpen(n: number): BrowserSessionTab[] {
    return Array.from({ length: n }, (_, i) => tab(i + 1, `https://open${i}.com/page`, `page ${i}`));
  }
  function manyClosed(n: number): ClosedTabEntry[] {
    return Array.from({ length: n }, (_, i) =>
      closed(100 + i, `https://closed${i}.com/page`, 1, `page ${i}`),
    );
  }

  it('合并后条数不超过 limit（不会变成两批各 limit 条）', () => {
    const res = searchTabsWithHistory(
      manyOpen(8),
      manyClosed(8),
      { query: 'page', limit: 10, includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches.length).toBe(10);
  });

  it('被截断时 truncated 为 true', () => {
    const res = searchTabsWithHistory(
      manyOpen(8),
      manyClosed(8),
      { query: 'page', limit: 10, includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.truncated).toBe(true);
  });

  it('没截断时 truncated 为 false', () => {
    const res = searchTabsWithHistory(
      manyOpen(3),
      manyClosed(2),
      { query: 'page', limit: 10, includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches).toHaveLength(5);
    expect(res.truncated).toBe(false);
  });

  it('limit 未传时用默认上限（不会无限返回）', () => {
    const res = searchTabsWithHistory(
      manyOpen(30),
      manyClosed(30),
      { query: 'page', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches.length).toBeLessThanOrEqual(10);
  });
});

describe('toClosedEntries（真实 sessions 负载）', () => {
  it('已关闭的 tab 没有 id 也能转出来，不应该抛', () => {
    // 这就是线上真实的形状：tab 已经不存在，id/windowId 都取不到。
    // 之前这里走 toSessionTab → getTabId，会直接抛 "Missing Chrome tab id"，
    // 异常被调用方 catch 吞掉，于是「开关点了完全没反应」。
    const raw = [
      { lastModified: Math.floor(TODAY / 1000), tab: { url: 'https://a.com/x', title: 'A' } },
    ];
    const entries = toClosedEntries(raw);
    expect(entries).toHaveLength(1);
    expect(entries[0]!.tab.url).toBe('https://a.com/x');
    expect(entries[0]!.tab.title).toBe('A');
    expect(typeof entries[0]!.tab.tabId).toBe('number');
  });

  it('多条没有 id 时兜底 id 不重复（否则按 tabId 排序/去重会串）', () => {
    const raw = [
      { lastModified: Math.floor(TODAY / 1000), tab: { url: 'https://a.com/1', title: 'A' } },
      { lastModified: Math.floor(TODAY / 1000), tab: { url: 'https://a.com/2', title: 'B' } },
    ];
    const ids = toClosedEntries(raw).map(e => e.tab.tabId);
    expect(new Set(ids).size).toBe(2);
  });

  it('关闭整个窗口时窗口里的 tab 逐个展开', () => {
    const raw = [
      {
        lastModified: Math.floor(TODAY / 1000),
        window: { tabs: [{ url: 'https://a.com', title: 'A' }, { url: 'https://b.com', title: 'B' }] },
      },
    ];
    expect(toClosedEntries(raw).map(e => e.tab.title)).toEqual(['A', 'B']);
  });

  it('整条链路能真的搜到历史（不抛且命中）', () => {
    const raw = [
      { lastModified: Math.floor(TODAY / 1000), tab: { url: 'https://closed.com/spec', title: 'Spec' } },
    ];
    const res = searchTabsWithHistory(
      [tab(1, 'https://open.com', 'Open')],
      toClosedEntries(raw),
      { query: 'spec', includeClosed: true },
      new Map(),
      TODAY,
    );
    expect(res.matches).toHaveLength(1);
    expect(res.matches[0]!.source).toBe('closed');
  });
});
