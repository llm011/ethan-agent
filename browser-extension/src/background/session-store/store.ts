import type {
  BrowserTabActivateParams,
  BrowserTabActivateResult,
  BrowserTabActiveParams,
  BrowserTabActiveResult,
  BrowserTabListParams,
  BrowserTabListResult,
  BrowserTabMoveParams,
  BrowserTabMoveResult,
  BrowserTabOpenParams,
  BrowserTabOpenResult,
  BrowserTabUserListResult,
} from '../../shared';
import { createSessionNotFoundError } from './errors';
import { BrowserSessionStoreTabs } from './store-tabs';
import { getTabId, toSessionTab } from './utils';
import {
  createTab,
  getTab,
  groupTabs,
  moveTabToIndex,
  queryTabs,
  updateTab,
} from './chrome-api';

export class BrowserSessionStore extends BrowserSessionStoreTabs {
  async openTab(params: BrowserTabOpenParams): Promise<BrowserTabOpenResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);

    const tab = await createTab({
      url: params.url,
      active: params.active ?? true,
      windowId: session.windowId,
    });
    const tabId = getTabId(tab, 'Cannot open a tab without tab id');
    await groupTabs([tabId], session.groupId);

    if (params.active ?? true) {
      session.activeTabId = tabId;
      session.updatedAt = Date.now();
    }

    const normalizedTab = await getTab(tabId);
    await this.persist();
    return {
      opened: true,
      sessionId: params.sessionId,
      tab: toSessionTab(normalizedTab),
    };
  }

  async listTabs(params: BrowserTabListParams): Promise<BrowserTabListResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    const info = await this.reconcileSessionOrThrow(session);
    await this.persist();

    return {
      sessionId: params.sessionId,
      tabs: info.tabs,
    };
  }

  async listUserTabs(): Promise<BrowserTabUserListResult> {
    const tabs = await queryTabs({});
    return {
      tabs: tabs.map(toSessionTab),
    };
  }

  async getActiveTab(
    params: BrowserTabActiveParams,
  ): Promise<BrowserTabActiveResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    const info = await this.reconcileSessionOrThrow(session);
    const tab =
      info.tabs.find(item => item.tabId === info.activeTabId) ?? info.tabs[0];
    if (!tab) {
      throw createSessionNotFoundError(params.sessionId);
    }

    await this.persist();
    return {
      sessionId: params.sessionId,
      tab,
    };
  }

  async activateTab(
    params: BrowserTabActivateParams,
  ): Promise<BrowserTabActivateResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);
    const tab = await updateTab(params.tabId, { active: true });

    session.activeTabId = params.tabId;
    session.updatedAt = Date.now();
    await this.persist();

    return {
      activated: true,
      sessionId: params.sessionId,
      tab: toSessionTab(tab),
    };
  }

  async moveTab(
    params: BrowserTabMoveParams,
  ): Promise<BrowserTabMoveResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);

    // params.index 是组内相对索引，需转为 window 下的绝对索引
    const tabsInGroup = await queryTabs({
      groupId: session.groupId,
      windowId: session.windowId,
    });
    tabsInGroup.sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
    const groupStartIndex = tabsInGroup.length > 0 ? (tabsInGroup[0].index ?? 0) : 0;
    const absoluteIndex = groupStartIndex + Math.max(0, Math.min(params.index, tabsInGroup.length - 1));
    const movedTab = await moveTabToIndex(params.tabId, absoluteIndex);
    session.updatedAt = Date.now();
    await this.persist();

    return {
      moved: true,
      sessionId: params.sessionId,
      tab: toSessionTab(movedTab),
    };
  }

  async handleTabRemoved(_tabId: number): Promise<void> {
    await this.ensureLoaded();
    for (const session of Array.from(this.sessions.values())) {
      await this.reconcileSession(session);
    }
    await this.persist();
  }
}
