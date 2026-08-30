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
import { BrowserSessionStoreSessions } from './store-sessions';
import { getTabId, toSessionTab } from './utils';
import type { StoredSession } from './types';
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
    // tab 已被别的 session 占用：不再报错让用户/agent 先手动 release，
    // 而是自动把该 tab 从旧 session 释放（保留 tab，只移出旧 group）后挂到本 session。
    let releasedFrom: string | undefined;
    if (existingSession && existingSession.sessionId !== params.sessionId) {
      await this.releaseTabFromOtherSession(params.tabId, existingSession);
      releasedFrom = existingSession.sessionId;
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
      ...(releasedFrom ? { releasedFrom } : {}),
    };
  }

  /**
   * 把某个 tab 从旧 session 的控制中释放出来，但保留 tab 本身（只把它移出旧 group）。
   *
   * 与 `detachTab` 的区别：detach 是从「当前 session」移出，这里是把 tab 从
   * 「另一个 session」夺出。释放后若旧 session 已空则清理其记录（与 close/detach
   * 的空组清理一致），否则刷新其 activeTabId。调用方随后会把该 tab 挂到目标 session。
   */
  private async releaseTabFromOtherSession(
    tabId: number,
    oldSession: StoredSession,
  ): Promise<void> {
    if (!this.sessions.has(oldSession.sessionId)) {
      return; // 已被并发的批量释放清理掉，跳过
    }
    await ungroupTabs([tabId]);

    const remaining = await this.getSessionTabs(oldSession);
    if (!remaining.length) {
      this.sessions.delete(oldSession.sessionId);
    } else {
      oldSession.activeTabId = this.resolveActiveTabId(
        remaining,
        oldSession.activeTabId,
      );
      oldSession.updatedAt = Date.now();
    }
    await this.persist();
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
    const releasedFrom: { tabId: number; sessionId: string }[] = [];
    for (const tabId of params.tabIds) {
      const sourceTab = await getTab(tabId);
      const existingSession = this.findSessionByGroup(
        sourceTab.groupId,
        sourceTab.windowId,
      );
      // tab 被别的 session 占用：自动释放其控制权（保留 tab）后并入本 session，不报错。
      if (existingSession && existingSession.sessionId !== params.sessionId) {
        await this.releaseTabFromOtherSession(tabId, existingSession);
        releasedFrom.push({ tabId, sessionId: existingSession.sessionId });
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
      ...(releasedFrom.length ? { releasedFrom } : {}),
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
