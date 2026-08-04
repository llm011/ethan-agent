import type {
  BrowserTabActivateParams,
  BrowserTabAttachBatchParams,
  BrowserTabAttachParams,
  BrowserTabCloseParams,
  BrowserTabDetachParams,
  BrowserTabMoveParams,
  BrowserTabOpenParams,
} from '../../shared';
import {
  createInvalidParamsError,
  ensureObjectParams,
  normalizeHttpUrl,
  normalizeNumber,
  normalizeSessionId,
  normalizeTabId,
} from './params-helpers';

export function normalizeTabOpenParams(params: unknown): BrowserTabOpenParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.open params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    url: normalizeHttpUrl(nextParams.url, 'tabs.open'),
    active: typeof nextParams.active === 'boolean' ? nextParams.active : true,
  };
}

export function normalizeTabActivateParams(params: unknown): BrowserTabActivateParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.activate params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.activate'),
  };
}

export function normalizeTabAttachParams(params: unknown): BrowserTabAttachParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.attach params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.attach'),
  };
}

export function normalizeTabCloseParams(params: unknown): BrowserTabCloseParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.close params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.close'),
  };
}

export function normalizeTabAttachBatchParams(params: unknown): BrowserTabAttachBatchParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.attachBatch params');
  const tabIds = nextParams.tabIds;
  if (!Array.isArray(tabIds) || tabIds.length === 0) {
    throw createInvalidParamsError('Invalid tabs.attachBatch tabIds: must be a non-empty array');
  }
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabIds: tabIds.map((id, i) => normalizeTabId(id, `tabs.attachBatch[${i}]`)),
  };
}

export function normalizeTabDetachParams(params: unknown): BrowserTabDetachParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.detach params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.detach'),
  };
}

export function normalizeTabMoveParams(params: unknown): BrowserTabMoveParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.move params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.move'),
    index: normalizeNumber(nextParams.index, 'index', 'tabs.move'),
  };
}
