import type {
  BrowserSessionAttachCurrentParams,
  BrowserSessionAttachCurrentResult,
  BrowserSessionCloseParams,
  BrowserSessionCloseResult,
  BrowserSessionCreateParams,
  BrowserSessionCreateResult,
  BrowserSessionInfo,
  BrowserSessionListResult,
  BrowserSessionReleaseParams,
  BrowserSessionReleaseResult,
  BrowserSessionRenameParams,
  BrowserSessionRenameResult,
  BrowserSessionUpdateParams,
  BrowserSessionUpdateResult,
} from '../../shared';
import { DEFAULT_SESSION_URL } from './constants';
import { BrowserSessionStoreCore } from './store-core';
import type { StoredSession } from './types';
import {
  buildGroupTitle,
  createSessionId,
  getTabId,
} from './utils';
import {
  createTab,
  getCurrentActiveTab,
  groupTabs,
  removeTabs,
  updateGroup,
  updateGroupFull,
} from './chrome-api';

export class BrowserSessionStoreSessions extends BrowserSessionStoreCore {
  private _bgWindowId: number | undefined;

  private async _getBackgroundWindow(): Promise<number | undefined> {
    if (this._bgWindowId == null) return undefined;
    try {
      const win = await new Promise<chrome.windows.Window | undefined>((resolve) => {
        chrome.windows.get(this._bgWindowId!, (w) => {
          if (chrome.runtime.lastError || !w) resolve(undefined);
          else resolve(w);
        });
      });
      if (win && !win.focused) return this._bgWindowId;
      // Window is focused or gone — clear it
      this._bgWindowId = undefined;
      return undefined;
    } catch {
      this._bgWindowId = undefined;
      return undefined;
    }
  }

  async createSession(
    params: BrowserSessionCreateParams,
  ): Promise<BrowserSessionCreateResult> {
    await this.ensureLoaded();

    let windowId: number | undefined;
    if (params.background) {
      windowId = await this._getBackgroundWindow();
      if (windowId == null) {
        const win = await new Promise<chrome.windows.Window>((resolve, reject) => {
          chrome.windows.create({ focused: false, type: 'normal' }, w => {
            if (chrome.runtime.lastError || !w) {
              reject(new Error(chrome.runtime.lastError?.message || 'Failed to create background window'));
            } else {
              resolve(w);
            }
          });
        });
        windowId = win.id;
        this._bgWindowId = windowId;
        if (win.tabs && win.tabs.length > 0 && win.tabs[0].id) {
          await new Promise<void>(resolve => {
            chrome.tabs.remove(win.tabs![0].id!, () => resolve());
          });
        }
      }
    }

    const tab = await createTab({
      url: params.url || DEFAULT_SESSION_URL,
      active: !params.background,
      ...(windowId != null ? { windowId } : {}),
    });
    const tabId = getTabId(tab, 'Cannot create a session without tab id');
    const groupId = await groupTabs([tabId]);
    const now = Date.now();
    const session: StoredSession = {
      sessionId: createSessionId(),
      title: params.title,
      groupId,
      windowId: tab.windowId,
      activeTabId: tabId,
      createdAt: now,
      updatedAt: now,
    };

    await updateGroup(groupId, buildGroupTitle(session));
    if (params.color) {
      await updateGroupFull(groupId, { color: params.color as chrome.tabGroups.ColorEnum });
    }
    this.sessions.set(session.sessionId, session);
    const info = await this.reconcileSessionOrThrow(session);
    await this.persist();

    return {
      created: true,
      session: info,
    };
  }

  async attachCurrentSession(
    params: BrowserSessionAttachCurrentParams,
  ): Promise<BrowserSessionAttachCurrentResult> {
    await this.ensureLoaded();

    const tab = await getCurrentActiveTab();
    const tabId = getTabId(tab, 'Cannot attach current tab without tab id');
    const existingSession = this.findSessionByGroup(tab.groupId, tab.windowId);
    if (existingSession) {
      const info = await this.reconcileSessionOrThrow(existingSession);
      await this.persist();
      return {
        attached: true,
        attachedTabId: tabId,
        session: info,
      };
    }

    const groupId = await groupTabs([tabId]);
    const now = Date.now();
    const session: StoredSession = {
      sessionId: createSessionId(),
      title: params.title,
      groupId,
      windowId: tab.windowId,
      activeTabId: tabId,
      createdAt: now,
      updatedAt: now,
    };

    await updateGroup(groupId, buildGroupTitle(session));
    if (params.color) {
      await updateGroupFull(groupId, { color: params.color as chrome.tabGroups.ColorEnum });
    }
    this.sessions.set(session.sessionId, session);
    const info = await this.reconcileSessionOrThrow(session);
    await this.persist();

    return {
      attached: true,
      attachedTabId: tabId,
      session: info,
    };
  }

  async listSessions(): Promise<BrowserSessionListResult> {
    await this.ensureLoaded();

    const sessions: BrowserSessionInfo[] = [];
    for (const session of Array.from(this.sessions.values())) {
      const info = await this.reconcileSession(session);
      if (info) {
        sessions.push(info);
      }
    }

    await this.persist();
    return { sessions };
  }

  async renameSession(
    params: BrowserSessionRenameParams,
  ): Promise<BrowserSessionRenameResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);

    session.title = params.title;
    session.updatedAt = Date.now();
    await updateGroup(session.groupId, buildGroupTitle(session));
    const info = await this.reconcileSessionOrThrow(session);
    await this.persist();

    return {
      renamed: true,
      session: info,
    };
  }

  async releaseSession(
    params: BrowserSessionReleaseParams,
  ): Promise<BrowserSessionReleaseResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    this.sessions.delete(params.sessionId);
    await this.persist();

    return {
      released: true,
      sessionId: params.sessionId,
    };
  }

  async closeSession(
    params: BrowserSessionCloseParams,
  ): Promise<BrowserSessionCloseResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    const tabs = await this.getSessionTabsOrThrow(session);
    const closedTabIds = tabs.map(tab => tab.tabId);

    if (closedTabIds.length) {
      await removeTabs(closedTabIds);
    }
    this.sessions.delete(params.sessionId);
    await this.persist();

    return {
      closed: true,
      sessionId: params.sessionId,
      closedTabIds,
    };
  }

  async updateSession(
    params: BrowserSessionUpdateParams,
  ): Promise<BrowserSessionUpdateResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);

    if (params.title !== undefined) {
      session.title = params.title;
    }
    session.updatedAt = Date.now();

    const updateProps: { title: string; color?: chrome.tabGroups.ColorEnum } = {
      title: buildGroupTitle(session),
    };
    if (params.color) {
      updateProps.color = params.color as chrome.tabGroups.ColorEnum;
    }
    await updateGroupFull(session.groupId, updateProps);
    const info = await this.reconcileSessionOrThrow(session);
    await this.persist();

    return {
      updated: true,
      session: info,
    };
  }
}
