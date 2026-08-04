import type {
  BrowserSessionTab,
  BrowserTabAttachBatchParams,
  BrowserTabAttachBatchResult,
  BrowserTabAttachParams,
  BrowserTabAttachResult,
  BrowserTabCloseParams,
  BrowserTabCloseResult,
  BrowserTabDetachParams,
  BrowserTabDetachResult,
} from '../../shared';
import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserExtensionRpcError } from './errors';
import { BrowserSessionStoreSessions } from './store-sessions';
import { getTabId, toSessionTab } from './utils';
import {
  getTab,
  groupTabs,
  moveTabToWindow,
  removeTabs,
  ungroupTabs,
} from './chrome-api';

export class BrowserSessionStoreTabs extends BrowserSessionStoreSessions {
  async attachTab(
    params: BrowserTabAttachParams,
  ): Promise<BrowserTabAttachResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);

    const sourceTab = await getTab(params.tabId);
    const existingSession = this.findSessionByGroup(
      sourceTab.groupId,
      sourceTab.windowId,
    );
    if (existingSession && existingSession.sessionId !== params.sessionId) {
      throw new BrowserExtensionRpcError(
        BROWSER_RPC_ERROR_CODE.browserTabClaimedByAnotherSession,
        `Tab ${params.tabId} is already managed by session ${existingSession.sessionId}`,
      );
    }

    const targetTab =
      sourceTab.windowId === session.windowId
        ? sourceTab
        : await moveTabToWindow(params.tabId, session.windowId);
    const tabId = getTabId(targetTab, 'Cannot attach a tab without id');
    await groupTabs([tabId], session.groupId);

    session.activeTabId = tabId;
    session.updatedAt = Date.now();
    const normalizedTab = await getTab(tabId);
    await this.persist();

    return {
      attached: true,
      sessionId: params.sessionId,
      tab: toSessionTab(normalizedTab),
    };
  }

  async closeTab(
    params: BrowserTabCloseParams,
  ): Promise<BrowserTabCloseResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);
    await removeTabs([params.tabId]);

    const remainingTabs = await this.getSessionTabs(session);
    if (!remainingTabs.length) {
      this.sessions.delete(params.sessionId);
      await this.persist();
      return {
        closed: true,
        sessionId: params.sessionId,
        closedTabId: params.tabId,
        sessionClosed: true,
      };
    }

    if (session.activeTabId === params.tabId) {
      session.activeTabId = this.resolveActiveTabId(remainingTabs);
    }
    session.updatedAt = Date.now();
    await this.persist();

    return {
      closed: true,
      sessionId: params.sessionId,
      closedTabId: params.tabId,
    };
  }

  async attachBatchTabs(
    params: BrowserTabAttachBatchParams,
  ): Promise<BrowserTabAttachBatchResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);

    const validTabIds: number[] = [];
    for (const tabId of params.tabIds) {
      const sourceTab = await getTab(tabId);
      const existingSession = this.findSessionByGroup(
        sourceTab.groupId,
        sourceTab.windowId,
      );
      if (existingSession && existingSession.sessionId !== params.sessionId) {
        throw new BrowserExtensionRpcError(
          BROWSER_RPC_ERROR_CODE.browserTabClaimedByAnotherSession,
          `Tab ${tabId} is already managed by session ${existingSession.sessionId}`,
        );
      }
      // Move to target window if needed
      if (sourceTab.windowId !== session.windowId) {
        await moveTabToWindow(tabId, session.windowId);
      }
      validTabIds.push(tabId);
    }

    if (validTabIds.length) {
      await groupTabs(validTabIds, session.groupId);
    }

    session.activeTabId = validTabIds[validTabIds.length - 1] ?? session.activeTabId;
    session.updatedAt = Date.now();

    const attachedTabs: BrowserSessionTab[] = [];
    for (const tabId of validTabIds) {
      const normalizedTab = await getTab(tabId);
      attachedTabs.push(toSessionTab(normalizedTab));
    }
    await this.persist();

    return {
      attached: true,
      sessionId: params.sessionId,
      tabs: attachedTabs,
    };
  }

  async detachTab(
    params: BrowserTabDetachParams,
  ): Promise<BrowserTabDetachResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);

    await ungroupTabs([params.tabId]);

    const remainingTabs = await this.getSessionTabs(session);
    if (!remainingTabs.length) {
      // Group 已空，Chrome 会自动销毁 Group，清理 session
      this.sessions.delete(params.sessionId);
      await this.persist();
      return {
        detached: true,
        sessionId: params.sessionId,
        detachedTabId: params.tabId,
      };
    }

    // If the detached tab was the active one, pick another
    if (session.activeTabId === params.tabId) {
      session.activeTabId = this.resolveActiveTabId(remainingTabs);
    }
    session.updatedAt = Date.now();
    await this.persist();

    return {
      detached: true,
      sessionId: params.sessionId,
      detachedTabId: params.tabId,
    };
  }
}
