import type {
  BrowserTabActivateParams,
  BrowserTabAttachBatchParams,
  BrowserTabAttachParams,
  BrowserTabCloseParams,
  BrowserTabDetachParams,
  BrowserTabMoveParams,
  BrowserTabOpenParams,
  BrowserTabOrganizeParams,
  BrowserTabOrganizeOp,
  BrowserTabGroupColor,
} from '../../shared';
import {
  createInvalidParamsError,
  ensureObjectParams,
  normalizeHttpUrl,
  normalizeNumber,
  normalizeSessionId,
  normalizeTabGroupColor,
  normalizeTabId,
} from './params-helpers';

export function normalizeTabOpenParams(params: unknown): BrowserTabOpenParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.open params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    url: normalizeHttpUrl(nextParams.url, 'tabs.open'),
    active: typeof nextParams.active === 'boolean' ? nextParams.active : false,
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

export function normalizeTabOrganizeParams(params: unknown): BrowserTabOrganizeParams {
  const p = ensureObjectParams(params, 'Invalid tabs.organize params');
  const ops = p.ops;
  if (!Array.isArray(ops) || ops.length === 0) {
    throw createInvalidParamsError('tabs.organize requires a non-empty ops array');
  }
  return {
    ops: ops.map((raw, i) => normalizeOrganizeOp(raw, i)),
  };
}

function normalizeOrganizeOp(raw: unknown, idx: number): BrowserTabOrganizeOp {
  const p = ensureObjectParams(raw, `Invalid tabs.organize ops[${idx}]`);
  const op = p.op;
  if (op === 'close') {
    const tabs = p.tabs;
    if (!Array.isArray(tabs) || tabs.length === 0) {
      throw createInvalidParamsError(`tabs.organize ops[${idx}].close requires non-empty tabs`);
    }
    return { op: 'close', tabs: tabs.map((id, j) => normalizeTabId(id, `ops[${idx}].tabs[${j}]`)) };
  }
  if (op === 'group') {
    const title = typeof p.title === 'string' ? p.title.trim() : '';
    if (!title) throw createInvalidParamsError(`tabs.organize ops[${idx}].group requires title`);
    const tabs = p.tabs;
    if (!Array.isArray(tabs) || tabs.length === 0) {
      throw createInvalidParamsError(`tabs.organize ops[${idx}].group requires non-empty tabs`);
    }
    return {
      op: 'group',
      title,
      tabs: tabs.map((id, j) => normalizeTabId(id, `ops[${idx}].tabs[${j}]`)),
      ...(p.color != null ? { color: normalizeTabGroupColor(p.color) as BrowserTabGroupColor } : {}),
      ...(p.groupId != null ? { groupId: normalizeNumber(p.groupId, 'groupId', `ops[${idx}]`) } : {}),
    };
  }
  if (op === 'ungroup') {
    const tabs = p.tabs;
    if (!Array.isArray(tabs) || tabs.length === 0) {
      throw createInvalidParamsError(`tabs.organize ops[${idx}].ungroup requires non-empty tabs`);
    }
    return { op: 'ungroup', tabs: tabs.map((id, j) => normalizeTabId(id, `ops[${idx}].tabs[${j}]`)) };
  }
  if (op === 'ungroup_all') {
    if (p.groupId == null && !p.title) {
      throw createInvalidParamsError(`tabs.organize ops[${idx}].ungroup_all requires groupId or title`);
    }
    return {
      op: 'ungroup_all',
      ...(p.groupId != null ? { groupId: normalizeNumber(p.groupId, 'groupId', `ops[${idx}]`) } : {}),
      ...(typeof p.title === 'string' && p.title.trim() ? { title: p.title.trim() } : {}),
    };
  }
  throw createInvalidParamsError(`tabs.organize ops[${idx}]: unknown op "${String(op)}"`);
}
