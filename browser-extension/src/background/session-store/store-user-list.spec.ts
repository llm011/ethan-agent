import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BrowserSessionStore } from './store';
import { BrowserSessionStoreCore } from './store-core';
import { BrowserExtensionRpcError } from './errors';
import { toSessionTab } from './utils';
import type { StoredSession } from './types';

vi.mock('./chrome-api', () => ({
  queryTabs: vi.fn(),
  queryGroups: vi.fn(),
}));
import { queryGroups, queryTabs } from './chrome-api';

const icon = `data:image/png;base64,${'A'.repeat(100_000)}`;
function makeTab(id: number): chrome.tabs.Tab {
  return {
    id, windowId: id % 2 + 1, groupId: id % 2 ? 5 : -1,
    index: id, active: id === 0, highlighted: false, pinned: false,
    incognito: false, selected: false, discarded: false, autoDiscardable: true,
    url: `https://example.com/${id}`, title: `标签 ${id}`, favIconUrl: icon,
  };
}

class TestStoreCore extends BrowserSessionStoreCore {
  getTabs(session: StoredSession) { return this.getSessionTabs(session); }
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(queryGroups).mockResolvedValue([]);
});

describe('user_list favicon 体积保护', () => {
  it('保留跨窗口全部标签及操作元数据，但不包含 favicon', async () => {
    const tabs = Array.from({ length: 80 }, (_, i) => makeTab(i));
    vi.mocked(queryTabs).mockResolvedValue(tabs);
    const result = await new BrowserSessionStore().listUserTabs();
    expect(queryTabs).toHaveBeenCalledWith({});
    expect(result.tabs).toHaveLength(80);
    expect(result.tabs).toEqual(tabs.map(tab => ({
      tabId: tab.id, windowId: tab.windowId,
      groupId: tab.groupId === -1 ? undefined : tab.groupId,
      url: tab.url, title: tab.title, active: tab.active,
    })));
    expect(result.tabs.every(tab => !('favIconUrl' in tab))).toBe(true);
    expect(JSON.stringify(result).length).toBeLessThan(18_000);
    expect(tabs[0].favIconUrl).toBe(icon); // 不修改 Chrome 返回值
  });

  it('空清单保持原有响应结构', async () => {
    vi.mocked(queryTabs).mockResolvedValue([]);
    expect(await new BrowserSessionStore().listUserTabs()).toEqual({ tabs: [] });
  });

  it('默认转换保留图标，显式禁用才移除', () => {
    expect(toSessionTab(makeTab(0)).favIconUrl).toBe(icon);
    expect(toSessionTab(makeTab(0), {}).favIconUrl).toBe(icon);
    expect(toSessionTab(makeTab(0), { includeFavIcon: false })).not.toHaveProperty('favIconUrl');
    const tab = makeTab(1);
    delete tab.favIconUrl;
    expect(toSessionTab(tab)).not.toHaveProperty('favIconUrl');
    delete tab.id;
    expect(() => toSessionTab(tab)).toThrow(BrowserExtensionRpcError);
  });

  it('会话列表包装 map 回调，多个标签的图标不受索引参数影响', async () => {
    vi.mocked(queryTabs).mockResolvedValue([makeTab(0), makeTab(1)]);
    const result = await new TestStoreCore().getTabs({
      sessionId: 's_test', groupId: 5, windowId: 1, createdAt: 0, updatedAt: 0,
    });
    expect(queryTabs).toHaveBeenCalledWith({ groupId: 5, windowId: 1 });
    expect(result.map(tab => tab.favIconUrl)).toEqual([icon, icon]);
  });

  it('关键词搜索继续返回图标，供 UI 显示', async () => {
    vi.mocked(queryTabs).mockResolvedValue([makeTab(0), makeTab(1)]);
    const result = await new BrowserSessionStore().searchTabs({ query: 'example' });
    expect(result.matches).toHaveLength(2);
    expect(result.matches.map(match => match.tab.favIconUrl)).toEqual([icon, icon]);
  });

  it('查询失败向上传递，而不是伪装空列表', async () => {
    vi.mocked(queryTabs).mockRejectedValue(new Error('query failed'));
    await expect(new BrowserSessionStore().listUserTabs()).rejects.toThrow('query failed');
  });
});
