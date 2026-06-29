/* eslint-disable max-lines -- session store keeps Chrome group lifecycle in one module for V1 */
import type {
  BrowserSessionAttachCurrentParams,
  BrowserSessionAttachCurrentResult,
  BrowserSessionCloseParams,
  BrowserSessionCloseResult,
  BrowserSessionCreateParams,
  BrowserSessionCreateResult,
  BrowserSessionInfo,
  BrowserSessionListResult,
  BrowserSessionRenameParams,
  BrowserSessionRenameResult,
  BrowserSessionReleaseParams,
  BrowserSessionReleaseResult,
  BrowserSessionTab,
  BrowserTabActivateParams,
  BrowserTabActivateResult,
  BrowserTabActiveParams,
  BrowserTabActiveResult,
  BrowserTabAttachParams,
  BrowserTabAttachResult,
  BrowserTabCloseParams,
  BrowserTabCloseResult,
  BrowserTabListParams,
  BrowserTabListResult,
  BrowserTabOpenParams,
  BrowserTabOpenResult,
  BrowserTabUserListResult,
} from '../shared';
import { COZE_BROWSER_RPC_ERROR_CODE } from '../shared';

const STORAGE_KEY = 'coze_browser_sessions_v2';
const TAB_GROUP_ID_NONE = -1;
const DEFAULT_SESSION_URL = 'about:blank';
const GROUP_TITLE_PREFIX = 'Coze · ';
const SESSION_ID_RANDOM_LENGTH = 12;
const SESSION_ID_FALLBACK_RADIX = 36;

interface StoredSession {
  sessionId: string;
  title?: string;
  groupId: number;
  windowId: number;
  activeTabId?: number;
  createdAt: number;
  updatedAt: number;
}

export class BrowserExtensionRpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
  }
}

function createSessionId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return `s_${globalThis.crypto
      .randomUUID()
      .replaceAll('-', '')
      .slice(0, SESSION_ID_RANDOM_LENGTH)}`;
  }

  return `s_${Date.now().toString(SESSION_ID_FALLBACK_RADIX)}_${Math.random()
    .toString(SESSION_ID_FALLBACK_RADIX)
    .slice(2, 2 + SESSION_ID_RANDOM_LENGTH)}`;
}

function isStoredSession(value: unknown): value is StoredSession {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const session = value as Partial<StoredSession>;
  return (
    typeof session.sessionId === 'string' &&
    typeof session.groupId === 'number' &&
    typeof session.windowId === 'number' &&
    typeof session.createdAt === 'number' &&
    typeof session.updatedAt === 'number'
  );
}

function buildGroupTitle(session: Pick<StoredSession, 'sessionId' | 'title'>) {
  return `${GROUP_TITLE_PREFIX}${
    session.title || session.sessionId.slice(0, SESSION_ID_RANDOM_LENGTH)
  }`;
}

function createSessionNotFoundError(
  sessionId: string,
): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    COZE_BROWSER_RPC_ERROR_CODE.browserSessionNotFound,
    `Session ${sessionId} not found`,
  );
}

function getRuntimeErrorMessage(): string | undefined {
  return chrome.runtime.lastError?.message;
}

function rejectWithRuntimeError(
  reject: (error: Error) => void,
  fallback: string,
): boolean {
  const message = getRuntimeErrorMessage();
  if (!message) {
    return false;
  }
  reject(new Error(message || fallback));
  return true;
}

function getTabId(tab: chrome.tabs.Tab, fallback: string): number {
  if (typeof tab.id !== 'number') {
    throw new BrowserExtensionRpcError(
      COZE_BROWSER_RPC_ERROR_CODE.browserTabNotFound,
      fallback,
    );
  }

  return tab.id;
}

function toSessionTab(tab: chrome.tabs.Tab): BrowserSessionTab {
  const tabId = getTabId(tab, 'Missing Chrome tab id');
  return {
    tabId,
    windowId: tab.windowId,
    groupId:
      typeof tab.groupId === 'number' && tab.groupId !== TAB_GROUP_ID_NONE
        ? tab.groupId
        : undefined,
    url: tab.url,
    title: tab.title,
    active: tab.active,
  };
}

function toSessionInfo(
  session: StoredSession,
  tabs: BrowserSessionTab[],
): BrowserSessionInfo {
  const activeTabId = tabs.some(tab => tab.tabId === session.activeTabId)
    ? session.activeTabId
    : undefined;

  return {
    sessionId: session.sessionId,
    title: session.title,
    windowId: session.windowId,
    groupId: session.groupId,
    groupTitle: buildGroupTitle(session),
    activeTabId,
    tabs,
  };
}

export class BrowserSessionStore {
  private loaded = false;

  private readonly sessions = new Map<string, StoredSession>();

  async createSession(
    params: BrowserSessionCreateParams,
  ): Promise<BrowserSessionCreateResult> {
    await this.ensureLoaded();

    const tab = await this.createTab({
      url: params.url || DEFAULT_SESSION_URL,
      active: true,
    });
    const tabId = getTabId(tab, 'Cannot create a session without tab id');
    const groupId = await this.groupTabs([tabId]);
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

    await this.updateGroup(groupId, buildGroupTitle(session));
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

    const tab = await this.getCurrentActiveTab();
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

    const groupId = await this.groupTabs([tabId]);
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

    await this.updateGroup(groupId, buildGroupTitle(session));
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
    await this.updateGroup(session.groupId, buildGroupTitle(session));
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
      await this.removeTabs(closedTabIds);
    }
    this.sessions.delete(params.sessionId);
    await this.persist();

    return {
      closed: true,
      sessionId: params.sessionId,
      closedTabIds,
    };
  }

  async openTab(params: BrowserTabOpenParams): Promise<BrowserTabOpenResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);

    const tab = await this.createTab({
      url: params.url,
      active: params.active ?? true,
      windowId: session.windowId,
    });
    const tabId = getTabId(tab, 'Cannot open a tab without tab id');
    await this.groupTabs([tabId], session.groupId);

    if (params.active ?? true) {
      session.activeTabId = tabId;
      session.updatedAt = Date.now();
    }

    const normalizedTab = await this.getTab(tabId);
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
    const tabs = await this.queryTabs({});
    return {
      tabs: tabs.map(toSessionTab),
    };
  }

  async attachTab(
    params: BrowserTabAttachParams,
  ): Promise<BrowserTabAttachResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);

    const sourceTab = await this.getTab(params.tabId);
    const existingSession = this.findSessionByGroup(
      sourceTab.groupId,
      sourceTab.windowId,
    );
    if (existingSession && existingSession.sessionId !== params.sessionId) {
      throw new BrowserExtensionRpcError(
        COZE_BROWSER_RPC_ERROR_CODE.browserTabClaimedByAnotherSession,
        `Tab ${params.tabId} is already managed by session ${existingSession.sessionId}`,
      );
    }

    const targetTab =
      sourceTab.windowId === session.windowId
        ? sourceTab
        : await this.moveTabToWindow(params.tabId, session.windowId);
    const tabId = getTabId(targetTab, 'Cannot attach a tab without id');
    await this.groupTabs([tabId], session.groupId);

    session.activeTabId = tabId;
    session.updatedAt = Date.now();
    const normalizedTab = await this.getTab(tabId);
    await this.persist();

    return {
      attached: true,
      sessionId: params.sessionId,
      tab: toSessionTab(normalizedTab),
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
    const tab = await this.updateTab(params.tabId, { active: true });

    session.activeTabId = params.tabId;
    session.updatedAt = Date.now();
    await this.persist();

    return {
      activated: true,
      sessionId: params.sessionId,
      tab: toSessionTab(tab),
    };
  }

  async closeTab(
    params: BrowserTabCloseParams,
  ): Promise<BrowserTabCloseResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);
    await this.removeTabs([params.tabId]);

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

  async handleTabRemoved(_tabId: number): Promise<void> {
    await this.ensureLoaded();
    for (const session of Array.from(this.sessions.values())) {
      await this.reconcileSession(session);
    }
    await this.persist();
  }

  private async ensureLoaded(): Promise<void> {
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
  }

  private getSessionOrThrow(sessionId: string): StoredSession {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw createSessionNotFoundError(sessionId);
    }

    return session;
  }

  private findSessionByGroup(
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

  private async reconcileSessionOrThrow(
    session: StoredSession,
  ): Promise<BrowserSessionInfo> {
    const info = await this.reconcileSession(session);
    if (!info) {
      throw createSessionNotFoundError(session.sessionId);
    }

    return info;
  }

  private async reconcileSession(
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

    await this.updateGroup(session.groupId, buildGroupTitle(session));
    return toSessionInfo(session, tabs);
  }

  private async getSessionTabsOrThrow(
    session: StoredSession,
  ): Promise<BrowserSessionTab[]> {
    const info = await this.reconcileSessionOrThrow(session);
    return info.tabs;
  }

  private async getSessionTabs(
    session: StoredSession,
  ): Promise<BrowserSessionTab[]> {
    try {
      const tabs = await this.queryTabs({
        groupId: session.groupId,
        windowId: session.windowId,
      });
      return tabs.map(toSessionTab);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new BrowserExtensionRpcError(
        COZE_BROWSER_RPC_ERROR_CODE.browserOperationFailed,
        message,
      );
    }
  }

  private resolveActiveTabId(
    tabs: BrowserSessionTab[],
    preferredTabId?: number,
  ): number | undefined {
    if (tabs.some(tab => tab.tabId === preferredTabId)) {
      return preferredTabId;
    }

    return tabs.find(tab => tab.active)?.tabId ?? tabs[0]?.tabId;
  }

  private async assertTabInSessionGroup(
    session: StoredSession,
    tabId: number,
  ): Promise<BrowserSessionTab> {
    const tab = toSessionTab(await this.getTab(tabId));
    if (tab.windowId !== session.windowId || tab.groupId !== session.groupId) {
      throw new BrowserExtensionRpcError(
        COZE_BROWSER_RPC_ERROR_CODE.browserTabNotInSession,
        `Tab ${tabId} is not in session ${session.sessionId}`,
      );
    }

    return tab;
  }

  private readStoredSessions(): Promise<Record<string, StoredSession>> {
    return new Promise(resolve => {
      chrome.storage.local.get(STORAGE_KEY, result => {
        resolve((result[STORAGE_KEY] as Record<string, StoredSession>) || {});
      });
    });
  }

  private persist(): Promise<void> {
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

  private createTab(
    params: chrome.tabs.CreateProperties,
  ): Promise<chrome.tabs.Tab> {
    return new Promise((resolve, reject) => {
      chrome.tabs.create(params, tab => {
        if (rejectWithRuntimeError(reject, 'Failed to create tab')) {
          return;
        }
        resolve(tab);
      });
    });
  }

  private getTab(tabId: number): Promise<chrome.tabs.Tab> {
    return new Promise<chrome.tabs.Tab>((resolve, reject) => {
      chrome.tabs.get(tabId, tab => {
        if (rejectWithRuntimeError(reject, `Tab ${tabId} not found`)) {
          return;
        }
        resolve(tab);
      });
    }).catch(error => {
      const message = error instanceof Error ? error.message : String(error);
      throw new BrowserExtensionRpcError(
        COZE_BROWSER_RPC_ERROR_CODE.browserTabNotFound,
        message,
      );
    });
  }

  private getCurrentActiveTab(): Promise<chrome.tabs.Tab> {
    return new Promise((resolve, reject) => {
      chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
        if (rejectWithRuntimeError(reject, 'Failed to query active tab')) {
          return;
        }

        const tab = tabs[0];
        if (!tab) {
          reject(
            new BrowserExtensionRpcError(
              COZE_BROWSER_RPC_ERROR_CODE.browserTabNotFound,
              'Current active tab not found',
            ),
          );
          return;
        }

        resolve(tab);
      });
    });
  }

  private moveTabToWindow(
    tabId: number,
    windowId: number,
  ): Promise<chrome.tabs.Tab> {
    return new Promise((resolve, reject) => {
      chrome.tabs.move(tabId, { windowId, index: -1 }, tab => {
        if (rejectWithRuntimeError(reject, 'Failed to move tab')) {
          return;
        }

        resolve(Array.isArray(tab) ? tab[0] : tab);
      });
    });
  }

  private queryTabs(
    queryInfo: chrome.tabs.QueryInfo,
  ): Promise<chrome.tabs.Tab[]> {
    return new Promise((resolve, reject) => {
      chrome.tabs.query(queryInfo, tabs => {
        if (rejectWithRuntimeError(reject, 'Failed to query tabs')) {
          return;
        }
        resolve(tabs);
      });
    });
  }

  private groupTabs(tabIds: number[], groupId?: number): Promise<number> {
    const groupTabIds = tabIds as [number, ...number[]];
    return new Promise<number>((resolve, reject) => {
      chrome.tabs.group(
        {
          tabIds: groupTabIds,
          ...(typeof groupId === 'number' ? { groupId } : {}),
        },
        nextGroupId => {
          if (rejectWithRuntimeError(reject, 'Failed to group tabs')) {
            return;
          }
          resolve(nextGroupId);
        },
      );
    }).catch(error => {
      const message = error instanceof Error ? error.message : String(error);
      throw new BrowserExtensionRpcError(
        COZE_BROWSER_RPC_ERROR_CODE.browserTabGroupFailed,
        message,
      );
    });
  }

  private updateGroup(groupId: number, title: string): Promise<void> {
    return new Promise((resolve, reject) => {
      chrome.tabGroups.update(groupId, { title }, () => {
        if (rejectWithRuntimeError(reject, 'Failed to update tab group')) {
          return;
        }
        resolve();
      });
    });
  }

  private updateTab(
    tabId: number,
    updateProperties: chrome.tabs.UpdateProperties,
  ): Promise<chrome.tabs.Tab> {
    return new Promise((resolve, reject) => {
      chrome.tabs.update(tabId, updateProperties, tab => {
        if (rejectWithRuntimeError(reject, 'Failed to update tab')) {
          return;
        }
        if (!tab) {
          reject(
            new BrowserExtensionRpcError(
              COZE_BROWSER_RPC_ERROR_CODE.browserTabNotFound,
              `Tab ${tabId} not found`,
            ),
          );
          return;
        }
        resolve(tab);
      });
    });
  }

  private removeTabs(tabIds: number[]): Promise<void> {
    return new Promise((resolve, reject) => {
      chrome.tabs.remove(tabIds, () => {
        if (rejectWithRuntimeError(reject, 'Failed to remove tabs')) {
          return;
        }
        resolve();
      });
    });
  }
}
