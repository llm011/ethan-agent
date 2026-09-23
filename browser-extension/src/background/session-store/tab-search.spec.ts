/**
 * tab 关键词搜索的匹配语义。
 *
 * 这层决定 agent 能不能找到用户说的那个 tab，判错的表现是「搜出来一堆无关的」
 * 或「明明开着却找不到」，所以把每个语义点（OR、大小写、字段权重、词边界、
 * 过滤、截断）都单独钉一个用例。
 */
import { describe, it, expect } from 'vitest';
import { parseKeywords, scoreTab, searchTabs, clampLimit } from './tab-search';
import type { BrowserSessionTab } from '../../shared';

const tab = (over: Partial<BrowserSessionTab> = {}): BrowserSessionTab => ({
  tabId: 1,
  windowId: 1,
  url: 'https://example.com/',
  title: 'Example',
  active: false,
  ...over,
});

describe('parseKeywords', () => {
  it('按空格切词并转小写', () => {
    expect(parseKeywords('GitHub Issue')).toEqual(['github', 'issue']);
  });

  it('忽略多余空格', () => {
    expect(parseKeywords('  a   b  ')).toEqual(['a', 'b']);
  });

  it('去重', () => {
    expect(parseKeywords('a A a')).toEqual(['a']);
  });

  it('空串/undefined 得到空数组', () => {
    expect(parseKeywords('')).toEqual([]);
    expect(parseKeywords(undefined)).toEqual([]);
  });
});

describe('scoreTab 字段与大小写', () => {
  it('大小写不敏感', () => {
    expect(scoreTab(tab({ title: 'GitHub' }), ['github'])).not.toBeNull();
    expect(scoreTab(tab({ title: 'github' }), ['GITHUB'.toLowerCase()])).not.toBeNull();
  });

  it('能命中 title（URL 里没有该词）', () => {
    const hit = scoreTab(
      tab({ title: '季度汇报', url: 'https://docs.example.com/abc123' }),
      ['季度'],
    );
    expect(hit).not.toBeNull();
    expect(hit!.matchedIn).toBe('title');
  });

  it('能命中 url', () => {
    const hit = scoreTab(tab({ title: '无关键词', url: 'https://github.com/x' }), ['github']);
    expect(hit).not.toBeNull();
    expect(hit!.matchedIn).toBe('url');
  });

  it('两处都命中时标记 both', () => {
    const hit = scoreTab(tab({ title: 'GitHub', url: 'https://github.com/' }), ['github']);
    expect(hit!.matchedIn).toBe('both');
  });

  it('title 权重高于 url', () => {
    const titleHit = scoreTab(tab({ title: 'github', url: 'https://other.com' }), ['github']);
    const urlHit = scoreTab(tab({ title: 'other', url: 'https://github.com' }), ['github']);
    expect(titleHit!.score).toBeGreaterThan(urlHit!.score);
  });

  it('词边界：hub.docker.com 的前缀命中优于 github.com 的子串命中', () => {
    const prefix = scoreTab(tab({ title: '', url: 'https://hub.docker.com' }), ['hub']);
    const substring = scoreTab(tab({ title: '', url: 'https://github.com' }), ['hub']);
    expect(prefix!.score).toBeGreaterThan(substring!.score);
  });

  it('子串命中（得 0 分加成）不能被当成未命中', () => {
    // 回归：scoreField 若用 0 兼作「未命中」哨兵，github.com 里搜 hub 会被漏掉。
    const hit = scoreTab(tab({ title: 'GitHub', url: 'https://github.com' }), ['hub']);
    expect(hit).not.toBeNull();
    expect(hit!.matchedKeywords).toEqual(['hub']);
  });

  it('未命中返回 null', () => {
    expect(scoreTab(tab({ title: 'Example', url: 'https://example.com' }), ['nope'])).toBeNull();
  });

  it('无关键词时一律算命中且分数为 0', () => {
    const hit = scoreTab(tab(), []);
    expect(hit).not.toBeNull();
    expect(hit!.score).toBe(0);
  });
});

describe('searchTabs 语义', () => {
  const tabs = [
    tab({ tabId: 1, title: 'GitHub Pull Requests', url: 'https://github.com/pulls' }),
    tab({ tabId: 2, title: 'GitHub Issue 123', url: 'https://github.com/issues/123' }),
    tab({ tabId: 3, title: '把 github 上的 issue 修一下', url: 'https://notes.example.com/x' }),
    tab({ tabId: 4, title: '无关页面', url: 'https://example.com/' }),
  ];

  it('多关键词是 OR：任一命中即返回', () => {
    const r = searchTabs(tabs, { query: 'github issue' });
    const ids = r.matches.map(m => m.tab.tabId).sort();
    // 1/2/3 都至少命中一个词；4 一个都没命中
    expect(ids).toEqual([1, 2, 3]);
  });

  it('命中词数多的排前面', () => {
    const r = searchTabs(tabs, { query: 'github issue' });
    // tab2 两个词都在 title+url 命中（分最高）；tab3 只命中 github
    expect(r.matches[0]!.tab.tabId).toBe(2);
    expect(r.matches[0]!.matchedKeywords.length).toBe(2);
    // tab3（只命中 github）排在 tab2 之后
    const ids = r.matches.map(m => m.tab.tabId);
    expect(ids.indexOf(3)).toBeGreaterThan(ids.indexOf(2));
  });

  it('matchedKeywords 去重且只含命中的词', () => {
    const r = searchTabs(tabs, { query: 'github nonexistent' });
    const first = r.matches.find(m => m.tab.tabId === 1)!;
    expect(first.matchedKeywords).toEqual(['github']);
  });

  it('全部未命中时 matches 为空', () => {
    const r = searchTabs(tabs, { query: 'zzzz' });
    expect(r.matches).toEqual([]);
    expect(r.total).toBe(0);
  });

  it('空 query 返回全部（等价 userList）', () => {
    const r = searchTabs(tabs, {});
    expect(r.total).toBe(4);
  });

  it('activeOnly 忽略 query', () => {
    const withActive = [...tabs.slice(0, 1), tab({ tabId: 9, title: 'x', active: true })];
    const r = searchTabs(withActive, { query: 'github', activeOnly: true });
    expect(r.matches.map(m => m.tab.tabId)).toEqual([9]);
  });

  it('latest: active 的同分 tab 靠前', () => {
    const same = [
      tab({ tabId: 1, title: 'abc', active: false }),
      tab({ tabId: 2, title: 'abc', active: true }),
    ];
    const r = searchTabs(same, { query: 'abc' });
    expect(r.matches[0]!.tab.tabId).toBe(2);
  });

  it('按 windowId 过滤', () => {
    const twoWindows = [
      tab({ tabId: 1, windowId: 1, title: 'abc' }),
      tab({ tabId: 2, windowId: 2, title: 'abc' }),
    ];
    const r = searchTabs(twoWindows, { query: 'abc', windowId: 2 });
    expect(r.matches.map(m => m.tab.tabId)).toEqual([2]);
    expect(r.scanned).toBe(1);
  });

  it('按 groupId 过滤', () => {
    const grouped = [
      tab({ tabId: 1, groupId: 5, title: 'abc' }),
      tab({ tabId: 2, groupId: 6, title: 'abc' }),
      tab({ tabId: 3, title: 'abc' }),
    ];
    const r = searchTabs(grouped, { query: 'abc', groupId: 5 });
    expect(r.matches.map(m => m.tab.tabId)).toEqual([1]);
  });

  it('groupId=-1 只取未分组的', () => {
    const grouped = [
      tab({ tabId: 1, groupId: 5, title: 'abc' }),
      tab({ tabId: 3, title: 'abc' }),
    ];
    const r = searchTabs(grouped, { query: 'abc', groupId: -1 });
    expect(r.matches.map(m => m.tab.tabId)).toEqual([3]);
  });

  it('带出所属分组的标题和颜色', () => {
    const grouped = [tab({ tabId: 1, groupId: 5, title: 'abc' })];
    const groups = new Map([[5, { title: '工作', color: 'blue' }]]);
    const r = searchTabs(grouped, { query: 'abc' }, groups);
    expect(r.matches[0]!.groupTitle).toBe('工作');
    expect(r.matches[0]!.groupColor).toBe('blue');
  });

  it('取不到分组信息时不报错', () => {
    const grouped = [tab({ tabId: 1, groupId: 5, title: 'abc' })];
    const r = searchTabs(grouped, { query: 'abc' }, new Map());
    expect(r.matches[0]!.groupTitle).toBeUndefined();
  });

  it('limit 截断并置 truncated', () => {
    const many = Array.from({ length: 5 }, (_, i) => tab({ tabId: i + 1, title: 'abc' }));
    const r = searchTabs(many, { query: 'abc', limit: 2 });
    expect(r.matches.length).toBe(2);
    expect(r.total).toBe(5);
    expect(r.truncated).toBe(true);
  });

  it('未截断时 truncated=false', () => {
    const r = searchTabs(tabs, { query: 'github' });
    expect(r.truncated).toBe(false);
  });
});

describe('clampLimit', () => {
  it('默认 10', () => {
    expect(clampLimit(undefined)).toBe(10);
  });

  it('上限 50', () => {
    expect(clampLimit(9999)).toBe(50);
  });

  it('非法值回落默认', () => {
    expect(clampLimit(0)).toBe(10);
    expect(clampLimit(-5)).toBe(10);
  });
});
