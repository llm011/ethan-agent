import type {
  BrowserSessionInfo,
  BrowserSessionTab,
} from '../../shared';
import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import {
  GROUP_TITLE_PREFIX,
  SESSION_ID_FALLBACK_RADIX,
  SESSION_ID_RANDOM_LENGTH,
  TAB_GROUP_ID_NONE,
} from './constants';
import { BrowserExtensionRpcError } from './errors';
import type { StoredSession } from './types';

export function createSessionId(): string {
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

export function isStoredSession(value: unknown): value is StoredSession {
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

export function buildGroupTitle(
  session: Pick<StoredSession, 'sessionId' | 'title'>,
) {
  return `${GROUP_TITLE_PREFIX}${
    session.title || session.sessionId.slice(0, SESSION_ID_RANDOM_LENGTH)
  }`;
}

export function getRuntimeErrorMessage(): string | undefined {
  return chrome.runtime.lastError?.message;
}

export function rejectWithRuntimeError(
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

export function getTabId(tab: chrome.tabs.Tab, fallback: string): number {
  if (typeof tab.id !== 'number') {
    throw new BrowserExtensionRpcError(
      BROWSER_RPC_ERROR_CODE.browserTabNotFound,
      fallback,
    );
  }

  return tab.id;
}

export function toSessionTab(tab: chrome.tabs.Tab): BrowserSessionTab {
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

export function toSessionInfo(
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
