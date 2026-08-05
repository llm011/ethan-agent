import type {
  BrowserSessionInfo,
  BrowserSessionTab,
} from '../../shared';
import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { GROUP_TITLE_PREFIX, STORAGE_KEY, TAB_GROUP_ID_NONE } from './constants';
import { BrowserExtensionRpcError, createSessionNotFoundError } from './errors';
import type { StoredSession } from './types';
import {
  buildGroupTitle,
  isStoredSession,
  rejectWithRuntimeError,
  toSessionInfo,
  toSessionTab,
} from './utils';
import { getTab, queryTabs, updateGroup } from './chrome-api';

export class BrowserSessionStoreCore {
  protected loaded = false;

  protected readonly sessions = new Map<string, StoredSession>();

  protected async ensureLoaded(): Promise<void> {
    if (this.loaded) {
      return;
    }

    const stored = await this.readStoredSessions();
    Object.values(stored).forEach(value => {
      if (isStoredSession(value)) {
        this.sessions.set(value.sessionId, { ...value });
      }
    });
    this.loaded = true;

    // 浏览器重启后 groupId/tabId 会变，按 TabGroup 标题重新匹配
    await this.reconcileAfterRestart();
  }

  /** 浏览器重启后 TabGroup ID 会变，按标题（Ethan · xxx）重新关联 session。 */
  private async reconcileAfterRestart(): Promise<void> {
    if (this.sessions.size === 0) return;

    let groups: chrome.tabGroups.TabGroup[];
    try {
      groups = await chrome.tabGroups.query({});
    } catch {
      return;  // tabGroups API 不可用，静默跳过
    }

    // 按 title 建立 "title → group" 映射，只看 Ethan 开头的
    const groupByTitle = new Map<string, chrome.tabGroups.TabGroup>();
    for (const g of groups) {
      if (g.title && g.title.startsWith(GROUP_TITLE_PREFIX)) {
        groupByTitle.set(g.title, g);
      }
    }

    if (groupByTitle.size === 0) return;

    let changed = false;
    for (const session of this.sessions.values()) {
      const expectedTitle = buildGroupTitle(session);
      const matched = groupByTitle.get(expectedTitle);
      if (!matched) continue;
      // groupId 或 windowId 变了 → 更新
      if (session.groupId !== matched.id || session.windowId !== matched.windowId) {
        session.groupId = matched.id;
        session.windowId = matched.windowId;
        session.updatedAt = Date.now();
        changed = true;
      }
    }

    if (changed) {
      await this.persist();
    }
  }

  protected getSessionOrThrow(sessionId: string): StoredSession {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw createSessionNotFoundError(sessionId);
    }

    return session;
  }

  protected findSessionByGroup(
    groupId: number | undefined,
    windowId: number,
  ): StoredSession | undefined {
    if (typeof groupId !== 'number' || groupId === TAB_GROUP_ID_NONE) {
      return undefined;
    }

    return Array.from(this.sessions.values()).find(
      session => session.groupId === groupId && session.windowId === windowId,
    );
  }

  protected async reconcileSessionOrThrow(
    session: StoredSession,
  ): Promise<BrowserSessionInfo> {
    const info = await this.reconcileSession(session);
    if (!info) {
      throw createSessionNotFoundError(session.sessionId);
    }

    return info;
  }

  protected async reconcileSession(
    session: StoredSession,
  ): Promise<BrowserSessionInfo | null> {
    const tabs = await this.getSessionTabs(session);
    if (!tabs.length) {
      this.sessions.delete(session.sessionId);
      return null;
    }

    const activeTabId = this.resolveActiveTabId(tabs, session.activeTabId);
    const nextWindowId = tabs[0]?.windowId ?? session.windowId;
    const changed =
      session.activeTabId !== activeTabId || session.windowId !== nextWindowId;

    session.activeTabId = activeTabId;
    session.windowId = nextWindowId;
    if (changed) {
      session.updatedAt = Date.now();
    }

    await updateGroup(session.groupId, buildGroupTitle(session));
    return toSessionInfo(session, tabs);
  }

  protected async getSessionTabsOrThrow(
    session: StoredSession,
  ): Promise<BrowserSessionTab[]> {
    const info = await this.reconcileSessionOrThrow(session);
    return info.tabs;
  }

  protected async getSessionTabs(
    session: StoredSession,
  ): Promise<BrowserSessionTab[]> {
    try {
      const tabs = await queryTabs({
        groupId: session.groupId,
        windowId: session.windowId,
      });
      return tabs.map(toSessionTab);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new BrowserExtensionRpcError(
        BROWSER_RPC_ERROR_CODE.browserOperationFailed,
        message,
      );
    }
  }

  protected resolveActiveTabId(
    tabs: BrowserSessionTab[],
    preferredTabId?: number,
  ): number | undefined {
    if (tabs.some(tab => tab.tabId === preferredTabId)) {
      return preferredTabId;
    }

    return tabs.find(tab => tab.active)?.tabId ?? tabs[0]?.tabId;
  }

  protected async assertTabInSessionGroup(
    session: StoredSession,
    tabId: number,
  ): Promise<BrowserSessionTab> {
    const tab = toSessionTab(await getTab(tabId));
    if (tab.windowId !== session.windowId || tab.groupId !== session.groupId) {
      throw new BrowserExtensionRpcError(
        BROWSER_RPC_ERROR_CODE.browserTabNotInSession,
        `Tab ${tabId} is not in session ${session.sessionId}`,
      );
    }

    return tab;
  }

  protected readStoredSessions(): Promise<Record<string, StoredSession>> {
    return new Promise(resolve => {
      chrome.storage.local.get(STORAGE_KEY, result => {
        resolve((result[STORAGE_KEY] as Record<string, StoredSession>) || {});
      });
    });
  }

  protected persist(): Promise<void> {
    const stored: Record<string, StoredSession> = {};
    this.sessions.forEach(session => {
      stored[session.sessionId] = { ...session };
    });

    return new Promise((resolve, reject) => {
      chrome.storage.local.set({ [STORAGE_KEY]: stored }, () => {
        if (rejectWithRuntimeError(reject, 'Failed to persist sessions')) {
          return;
        }
        resolve();
      });
    });
  }
}
