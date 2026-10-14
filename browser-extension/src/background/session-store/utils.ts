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

/**
 * 把 Chrome tab 归一化成会话 tab 结构。
 *
 * user_list 传 includeFavIcon=false：内嵌 base64 favicon 会放大全量 RPC 响应，
 * 且整理只需要标签元数据。默认保留 favicon，兼容会话操作及搜索面板图标。
 * 带 options 参数后，Array.map 必须用包装函数，避免把索引当成 options 传入。
 */
export function toSessionTab(
  tab: chrome.tabs.Tab,
  options: { includeFavIcon?: boolean } = {},
): BrowserSessionTab {
  const { includeFavIcon = true } = options;
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
    ...(includeFavIcon && tab.favIconUrl ? { favIconUrl: tab.favIconUrl } : {}),
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

/**
 * 规范化 URL 用于「同一会话里是否已打开该页」的去重比较。
 *
 * 为什么需要：tabs.open 本身不幂等，而上游（agent / MCP）在超时/断连等「假失败」后
 * 会重试同一个 open——此时第一个 tab 往往已经建好，重试就多开一个。按规范化 URL 去重，
 * 让重试命中已存在的 tab 而不是再建一个（见 openTab）。
 *
 * 规范化：去掉末尾斜杠、小写化 scheme+host、丢弃 hash（#fragment 不算不同页面）。
 * 解析失败（相对路径等）就退回去掉首尾空白的原串，宁可不去重也不误判。
 */
export function normalizeUrlForDedup(raw: string | undefined): string {
  const value = (raw ?? '').trim();
  if (!value) {
    return '';
  }
  try {
    const u = new URL(value);
    u.hash = '';
    const normalized = u.toString();
    return normalized.endsWith('/') ? normalized.slice(0, -1) : normalized;
  } catch {
    return value;
  }
}
