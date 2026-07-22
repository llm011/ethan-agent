/* eslint-disable -- request router keeps all protocol methods in one place. */
import type {
  BrowserPageActionResult,
  BrowserPageClickParams,
  BrowserPageEvalParams,
  BrowserPageEvalResult,
  BrowserPageFillParams,
  BrowserPageGetParams,
  BrowserPageGetResult,
  BrowserPageHoverParams,
  BrowserPageMouseButton,
  BrowserPageMouseParams,
  BrowserPagePressParams,
  BrowserPageScreenshotFormat,
  BrowserPageScreenshotParams,
  BrowserPageScreenshotResult,
  BrowserPageScrollDirection,
  BrowserPageScrollIntoViewParams,
  BrowserPageScrollParams,
  BrowserPageSelectParams,
  BrowserPageSnapshotParams,
  BrowserPageSnapshotResult,
  BrowserPageTypeParams,
  BrowserPageUploadParams,
  BrowserPageSavePdfParams,
  BrowserPageSavePdfResult,
  BrowserPageWaitParams,
  BrowserPageWaitResult,
  BrowserNetworkStartResult,
  BrowserNetworkStopResult,
  BrowserNetworkListResult,
  BrowserNetworkDetailResult,
  BrowserSessionAttachCurrentParams,
  BrowserSessionAttachCurrentResult,
  BrowserSessionCloseParams,
  BrowserSessionCloseResult,
  BrowserSessionCreateParams,
  BrowserSessionCreateResult,
  BrowserSessionListResult,
  BrowserSessionRenameParams,
  BrowserSessionRenameResult,
  BrowserSessionReleaseParams,
  BrowserSessionReleaseResult,
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
  BrowserTabAttachBatchParams,
  BrowserTabAttachBatchResult,
  BrowserTabDetachParams,
  BrowserTabDetachResult,
  BrowserTabMoveParams,
  BrowserTabMoveResult,
  BrowserSessionUpdateParams,
  BrowserSessionUpdateResult,
  JsonRpcRequest,
  JsonRpcResponse,
} from '../shared';
import {
  BROWSER_RPC_ERROR_CODE,
  BROWSER_RPC_METHODS,
} from '../shared';

import { BrowserExtensionRpcError } from './session-store';

export interface BrowserRequestDependencies {
  createSession: (
    params: BrowserSessionCreateParams,
  ) => Promise<BrowserSessionCreateResult>;
  attachCurrentSession: (
    params: BrowserSessionAttachCurrentParams,
  ) => Promise<BrowserSessionAttachCurrentResult>;
  listSessions: () => Promise<BrowserSessionListResult>;
  renameSession: (
    params: BrowserSessionRenameParams,
  ) => Promise<BrowserSessionRenameResult>;
  releaseSession: (
    params: BrowserSessionReleaseParams,
  ) => Promise<BrowserSessionReleaseResult>;
  closeSession: (
    params: BrowserSessionCloseParams,
  ) => Promise<BrowserSessionCloseResult>;
  openTab: (params: BrowserTabOpenParams) => Promise<BrowserTabOpenResult>;
  listTabs: (params: BrowserTabListParams) => Promise<BrowserTabListResult>;
  listUserTabs: () => Promise<BrowserTabUserListResult>;
  attachTab: (
    params: BrowserTabAttachParams,
  ) => Promise<BrowserTabAttachResult>;
  getActiveTab: (
    params: BrowserTabActiveParams,
  ) => Promise<BrowserTabActiveResult>;
  activateTab: (
    params: BrowserTabActivateParams,
  ) => Promise<BrowserTabActivateResult>;
  closeTab: (params: BrowserTabCloseParams) => Promise<BrowserTabCloseResult>;
  attachBatchTabs: (
    params: BrowserTabAttachBatchParams,
  ) => Promise<BrowserTabAttachBatchResult>;
  detachTab: (
    params: BrowserTabDetachParams,
  ) => Promise<BrowserTabDetachResult>;
  moveTab: (
    params: BrowserTabMoveParams,
  ) => Promise<BrowserTabMoveResult>;
  updateSession: (
    params: BrowserSessionUpdateParams,
  ) => Promise<BrowserSessionUpdateResult>;
  pageSnapshot: (
    params: BrowserPageSnapshotParams,
  ) => Promise<BrowserPageSnapshotResult>;
  pageClick: (
    params: BrowserPageClickParams,
  ) => Promise<BrowserPageActionResult>;
  pageFill: (params: BrowserPageFillParams) => Promise<BrowserPageActionResult>;
  pageType: (params: BrowserPageTypeParams) => Promise<BrowserPageActionResult>;
  pagePress: (
    params: BrowserPagePressParams,
  ) => Promise<BrowserPageActionResult>;
  pageHover: (
    params: BrowserPageHoverParams,
  ) => Promise<BrowserPageActionResult>;
  pageSelect: (
    params: BrowserPageSelectParams,
  ) => Promise<BrowserPageActionResult>;
  pageScroll: (
    params: BrowserPageScrollParams,
  ) => Promise<BrowserPageActionResult>;
  pageScrollIntoView: (
    params: BrowserPageScrollIntoViewParams,
  ) => Promise<BrowserPageActionResult>;
  pageScreenshot: (
    params: BrowserPageScreenshotParams,
  ) => Promise<BrowserPageScreenshotResult>;
  pageGet: (params: BrowserPageGetParams) => Promise<BrowserPageGetResult>;
  pageMouse: (
    params: BrowserPageMouseParams,
  ) => Promise<BrowserPageActionResult>;
  pageWait: (params: BrowserPageWaitParams) => Promise<BrowserPageWaitResult>;
  pageEval: (params: BrowserPageEvalParams) => Promise<BrowserPageEvalResult>;
  pageUpload: (params: BrowserPageUploadParams) => Promise<BrowserPageActionResult>;
  pageSavePdf: (params: BrowserPageSavePdfParams) => Promise<BrowserPageSavePdfResult>;
  networkStart: (params: { sessionId: string }) => Promise<BrowserNetworkStartResult>;
  networkStop: (params: { sessionId: string }) => Promise<BrowserNetworkStopResult>;
  networkList: (params: { sessionId: string; filter?: string }) => Promise<BrowserNetworkListResult>;
  networkDetail: (params: { sessionId: string; requestId: string }) => Promise<BrowserNetworkDetailResult>;
}

const ALLOWED_METHODS = new Set<string>([
  BROWSER_RPC_METHODS.sessionsCreate,
  BROWSER_RPC_METHODS.sessionsAttachCurrent,
  BROWSER_RPC_METHODS.sessionsList,
  BROWSER_RPC_METHODS.sessionsRename,
  BROWSER_RPC_METHODS.sessionsRelease,
  BROWSER_RPC_METHODS.sessionsClose,
  BROWSER_RPC_METHODS.tabsOpen,
  BROWSER_RPC_METHODS.tabsList,
  BROWSER_RPC_METHODS.tabsUserList,
  BROWSER_RPC_METHODS.tabsAttach,
  BROWSER_RPC_METHODS.tabsActive,
  BROWSER_RPC_METHODS.tabsActivate,
  BROWSER_RPC_METHODS.tabsClose,
  BROWSER_RPC_METHODS.tabsAttachBatch,
  BROWSER_RPC_METHODS.tabsDetach,
  BROWSER_RPC_METHODS.tabsMove,
  BROWSER_RPC_METHODS.sessionsUpdate,
  BROWSER_RPC_METHODS.pagesSnapshot,
  BROWSER_RPC_METHODS.pagesClick,
  BROWSER_RPC_METHODS.pagesFill,
  BROWSER_RPC_METHODS.pagesType,
  BROWSER_RPC_METHODS.pagesPress,
  BROWSER_RPC_METHODS.pagesHover,
  BROWSER_RPC_METHODS.pagesSelect,
  BROWSER_RPC_METHODS.pagesScroll,
  BROWSER_RPC_METHODS.pagesScrollIntoView,
  BROWSER_RPC_METHODS.pagesScreenshot,
  BROWSER_RPC_METHODS.pagesGet,
  BROWSER_RPC_METHODS.pagesMouse,
  BROWSER_RPC_METHODS.pagesWait,
  BROWSER_RPC_METHODS.pagesEval,
  BROWSER_RPC_METHODS.pagesUpload,
  BROWSER_RPC_METHODS.pagesSavePdf,
  BROWSER_RPC_METHODS.networkStart,
  BROWSER_RPC_METHODS.networkStop,
  BROWSER_RPC_METHODS.networkList,
  BROWSER_RPC_METHODS.networkDetail,
]);

function createSuccessResponse<T>(
  request: JsonRpcRequest,
  result: T,
): JsonRpcResponse<T> {
  return {
    jsonrpc: '2.0',
    id: request.id ?? null,
    result,
  };
}

function createErrorResponse(
  request: Partial<JsonRpcRequest>,
  code: number,
  message: string,
): JsonRpcResponse {
  return {
    jsonrpc: '2.0',
    id: request.id ?? null,
    error: {
      code,
      message,
    },
  };
}

function isJsonRpcRequest(value: unknown): value is JsonRpcRequest {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const candidate = value as Partial<JsonRpcRequest>;
  return candidate.jsonrpc === '2.0' && typeof candidate.method === 'string';
}

function createInvalidParamsError(message: string): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.invalidParams,
    message,
  );
}

function ensureObjectParams(
  params: unknown,
  message: string,
): Record<string, unknown> {
  if (!params || typeof params !== 'object') {
    throw createInvalidParamsError(message);
  }

  return params as Record<string, unknown>;
}

function normalizeHttpUrl(value: unknown, context: string): string {
  if (typeof value !== 'string') {
    throw createInvalidParamsError(`Invalid ${context} url`);
  }

  let parsedUrl: URL;
  try {
    parsedUrl = new URL(value);
  } catch {
    throw createInvalidParamsError(`Invalid URL: ${value}`);
  }

  if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
    throw createInvalidParamsError(
      `Unsupported URL protocol: ${parsedUrl.protocol}`,
    );
  }

  return parsedUrl.toString();
}

function normalizeSessionId(value: unknown): string {
  const sessionId = typeof value === 'string' ? value.trim() : '';
  if (!sessionId) {
    throw new BrowserExtensionRpcError(
      BROWSER_RPC_ERROR_CODE.browserSessionRequired,
      'Missing browser session id',
    );
  }

  return sessionId;
}

function normalizeOptionalTitle(value: unknown): string | undefined {
  const title = typeof value === 'string' ? value.trim() : '';
  return title || undefined;
}

function normalizeRequiredTitle(value: unknown): string {
  const title = normalizeOptionalTitle(value);
  if (!title) {
    throw createInvalidParamsError('Invalid sessions.rename title');
  }

  return title;
}

function normalizeTabId(value: unknown, context: string): number {
  const tabId =
    typeof value === 'string' && value.trim() ? Number(value) : value;
  if (!Number.isInteger(tabId) || Number(tabId) <= 0) {
    throw createInvalidParamsError(`Invalid ${context} tabId`);
  }

  return Number(tabId);
}

function normalizeSessionCreateParams(
  params: unknown,
): BrowserSessionCreateParams {
  const nextParams =
    params && typeof params === 'object'
      ? (params as Record<string, unknown>)
      : {};
  const title = normalizeOptionalTitle(nextParams.title);

  return {
    ...(typeof nextParams.url === 'string'
      ? { url: normalizeHttpUrl(nextParams.url, 'sessions.create') }
      : {}),
    ...(title ? { title } : {}),
  };
}

function normalizeSessionAttachCurrentParams(
  params: unknown,
): BrowserSessionAttachCurrentParams {
  const nextParams =
    params && typeof params === 'object'
      ? (params as Record<string, unknown>)
      : {};
  const title = normalizeOptionalTitle(nextParams.title);

  return {
    ...(title ? { title } : {}),
  };
}

function normalizeSessionRenameParams(
  params: unknown,
): BrowserSessionRenameParams {
  const nextParams = ensureObjectParams(
    params,
    'Invalid sessions.rename params',
  );

  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    title: normalizeRequiredTitle(nextParams.title),
  };
}

function normalizeSessionIdParams(
  params: unknown,
  context: string,
): { sessionId: string } {
  const nextParams = ensureObjectParams(params, `Invalid ${context} params`);
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
  };
}

function normalizeTabOpenParams(params: unknown): BrowserTabOpenParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.open params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    url: normalizeHttpUrl(nextParams.url, 'tabs.open'),
    active: typeof nextParams.active === 'boolean' ? nextParams.active : true,
  };
}

function normalizeTabActivateParams(params: unknown): BrowserTabActivateParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.activate params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.activate'),
  };
}

function normalizeTabAttachParams(params: unknown): BrowserTabAttachParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.attach params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.attach'),
  };
}

function normalizeTabCloseParams(params: unknown): BrowserTabCloseParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.close params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.close'),
  };
}

function normalizeRequiredString(
  value: unknown,
  fieldName: string,
  context: string,
): string {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) {
    throw createInvalidParamsError(`Invalid ${context} ${fieldName}`);
  }

  return text;
}

function normalizeNumber(
  value: unknown,
  fieldName: string,
  context: string,
): number {
  const numberValue =
    typeof value === 'string' && value.trim() ? Number(value) : value;
  if (!Number.isFinite(numberValue)) {
    throw createInvalidParamsError(`Invalid ${context} ${fieldName}`);
  }

  return Number(numberValue);
}

function normalizePositiveNumber(
  value: unknown,
  fieldName: string,
  context: string,
): number {
  const numberValue = normalizeNumber(value, fieldName, context);
  if (numberValue <= 0) {
    throw createInvalidParamsError(`Invalid ${context} ${fieldName}`);
  }
  return numberValue;
}

function normalizePageBaseParams(
  params: unknown,
  context: string,
): { sessionId: string } {
  const nextParams = ensureObjectParams(params, `Invalid ${context} params`);
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
  };
}

function normalizePageRefParams(
  params: unknown,
  context: string,
): { sessionId: string; ref: string } {
  const nextParams = ensureObjectParams(params, `Invalid ${context} params`);
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    ref: normalizeRequiredString(nextParams.ref, 'ref', context),
  };
}

function normalizePageSnapshotParams(
  params: unknown,
): BrowserPageSnapshotParams {
  const nextParams = ensureObjectParams(
    params,
    'Invalid pages.snapshot params',
  );
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    interactive:
      typeof nextParams.interactive === 'boolean'
        ? nextParams.interactive
        : false,
    compact:
      typeof nextParams.compact === 'boolean' ? nextParams.compact : false,
    cursor: typeof nextParams.cursor === 'boolean' ? nextParams.cursor : false,
    urls: typeof nextParams.urls === 'boolean' ? nextParams.urls : false,
    ...(typeof nextParams.depth !== 'undefined'
      ? {
          depth: normalizePositiveNumber(
            nextParams.depth,
            'depth',
            'pages.snapshot',
          ),
        }
      : {}),
    ...(typeof nextParams.selector === 'string' && nextParams.selector.trim()
      ? { selector: nextParams.selector.trim() }
      : {}),
  };
}

function normalizePageFillParams(params: unknown): BrowserPageFillParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.fill params');
  return {
    ...normalizePageRefParams(params, 'pages.fill'),
    text:
      typeof nextParams.text === 'string'
        ? nextParams.text
        : normalizeRequiredString(nextParams.text, 'text', 'pages.fill'),
  };
}

function normalizePageTypeParams(params: unknown): BrowserPageTypeParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.type params');
  return {
    ...normalizePageRefParams(params, 'pages.type'),
    text:
      typeof nextParams.text === 'string'
        ? nextParams.text
        : normalizeRequiredString(nextParams.text, 'text', 'pages.type'),
  };
}

function normalizePageSelectParams(params: unknown): BrowserPageSelectParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.select params');
  return {
    ...normalizePageRefParams(params, 'pages.select'),
    value: normalizeRequiredString(nextParams.value, 'value', 'pages.select'),
  };
}

function normalizePagePressParams(params: unknown): BrowserPagePressParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.press params');
  return {
    ...normalizePageBaseParams(params, 'pages.press'),
    key: normalizeRequiredString(nextParams.key, 'key', 'pages.press'),
  };
}

function normalizeScrollDirection(value: unknown): BrowserPageScrollDirection {
  if (value !== 'up' && value !== 'down') {
    throw createInvalidParamsError('Invalid pages.scroll direction');
  }
  return value;
}

function normalizePageScrollParams(params: unknown): BrowserPageScrollParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.scroll params');
  return {
    ...normalizePageBaseParams(params, 'pages.scroll'),
    direction: normalizeScrollDirection(nextParams.direction),
    pixels: normalizePositiveNumber(
      nextParams.pixels,
      'pixels',
      'pages.scroll',
    ),
  };
}

function normalizeScreenshotFormat(
  value: unknown,
): BrowserPageScreenshotFormat | undefined {
  if (typeof value === 'undefined') {
    return undefined;
  }
  if (value !== 'png' && value !== 'jpeg') {
    throw createInvalidParamsError('Invalid pages.screenshot format');
  }
  return value;
}

function normalizePageScreenshotParams(
  params: unknown,
): BrowserPageScreenshotParams {
  const nextParams = ensureObjectParams(
    params,
    'Invalid pages.screenshot params',
  );
  const quality =
    typeof nextParams.quality === 'undefined'
      ? undefined
      : normalizePositiveNumber(
          nextParams.quality,
          'quality',
          'pages.screenshot',
        );
  const format = normalizeScreenshotFormat(nextParams.format);
  return {
    ...normalizePageBaseParams(params, 'pages.screenshot'),
    fullPage:
      typeof nextParams.fullPage === 'boolean' ? nextParams.fullPage : false,
    ...(format ? { format } : {}),
    ...(typeof quality === 'number' ? { quality } : {}),
  };
}

function normalizePageGetParams(params: unknown): BrowserPageGetParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.get params');
  const what = nextParams.what;
  if (
    what !== 'text' &&
    what !== 'value' &&
    what !== 'html' &&
    what !== 'title' &&
    what !== 'url' &&
    what !== 'box'
  ) {
    throw createInvalidParamsError('Invalid pages.get what');
  }
  const needsRef = what !== 'title' && what !== 'url';
  return {
    ...normalizePageBaseParams(params, 'pages.get'),
    what,
    ...(needsRef
      ? { ref: normalizeRequiredString(nextParams.ref, 'ref', 'pages.get') }
      : {}),
  };
}

function normalizeMouseButton(value: unknown): BrowserPageMouseButton {
  if (typeof value === 'undefined') {
    return 'left';
  }
  if (value !== 'left' && value !== 'middle' && value !== 'right') {
    throw createInvalidParamsError('Invalid pages.mouse button');
  }
  return value;
}

function normalizePageMouseParams(params: unknown): BrowserPageMouseParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.mouse params');
  if (
    nextParams.action !== 'move' &&
    nextParams.action !== 'down' &&
    nextParams.action !== 'up' &&
    nextParams.action !== 'wheel'
  ) {
    throw createInvalidParamsError('Invalid pages.mouse action');
  }
  return {
    ...normalizePageBaseParams(params, 'pages.mouse'),
    action: nextParams.action,
    ...(typeof nextParams.x !== 'undefined'
      ? { x: normalizeNumber(nextParams.x, 'x', 'pages.mouse') }
      : {}),
    ...(typeof nextParams.y !== 'undefined'
      ? { y: normalizeNumber(nextParams.y, 'y', 'pages.mouse') }
      : {}),
    ...(nextParams.action === 'down' || nextParams.action === 'up'
      ? { button: normalizeMouseButton(nextParams.button) }
      : {}),
    ...(typeof nextParams.deltaX !== 'undefined'
      ? { deltaX: normalizeNumber(nextParams.deltaX, 'deltaX', 'pages.mouse') }
      : {}),
    ...(typeof nextParams.deltaY !== 'undefined'
      ? { deltaY: normalizeNumber(nextParams.deltaY, 'deltaY', 'pages.mouse') }
      : {}),
  };
}

function normalizePageWaitParams(params: unknown): BrowserPageWaitParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.wait params');
  if (
    typeof nextParams.load !== 'undefined' &&
    nextParams.load !== 'load' &&
    nextParams.load !== 'domcontentloaded' &&
    nextParams.load !== 'networkidle'
  ) {
    throw createInvalidParamsError('Invalid pages.wait load');
  }
  return {
    ...normalizePageBaseParams(params, 'pages.wait'),
    ...(typeof nextParams.ms !== 'undefined'
      ? { ms: normalizePositiveNumber(nextParams.ms, 'ms', 'pages.wait') }
      : {}),
    ...(typeof nextParams.load === 'string' ? { load: nextParams.load } : {}),
  };
}

function normalizePageEvalParams(params: unknown): BrowserPageEvalParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.eval params');
  return {
    ...normalizePageBaseParams(params, 'pages.eval'),
    script: normalizeRequiredString(nextParams.script, 'script', 'pages.eval'),
    awaitPromise:
      typeof nextParams.awaitPromise === 'boolean'
        ? nextParams.awaitPromise
        : true,
  };
}

function normalizeTabAttachBatchParams(params: unknown): BrowserTabAttachBatchParams {
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

function normalizeTabDetachParams(params: unknown): BrowserTabDetachParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.detach params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.detach'),
  };
}

function normalizeTabMoveParams(params: unknown): BrowserTabMoveParams {
  const nextParams = ensureObjectParams(params, 'Invalid tabs.move params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    tabId: normalizeTabId(nextParams.tabId, 'tabs.move'),
    index: normalizeNumber(nextParams.index, 'index', 'tabs.move'),
  };
}

function normalizeSessionUpdateParams(params: unknown): BrowserSessionUpdateParams {
  const nextParams = ensureObjectParams(params, 'Invalid sessions.update params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    ...(typeof nextParams.title === 'string' ? { title: nextParams.title.trim() } : {}),
    ...(typeof nextParams.color === 'string' ? { color: nextParams.color.trim() } : {}),
  };
}

export async function handleNativeRequest(
  message: unknown,
  deps: BrowserRequestDependencies,
): Promise<JsonRpcResponse | null> {
  if (!isJsonRpcRequest(message)) {
    return null;
  }

  if (!ALLOWED_METHODS.has(message.method)) {
    return createErrorResponse(
      message,
      BROWSER_RPC_ERROR_CODE.methodNotFound,
      `Unknown method: ${message.method}`,
    );
  }

  try {
    if (message.method === BROWSER_RPC_METHODS.sessionsCreate) {
      return createSuccessResponse(
        message,
        await deps.createSession(normalizeSessionCreateParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.sessionsAttachCurrent) {
      return createSuccessResponse(
        message,
        await deps.attachCurrentSession(
          normalizeSessionAttachCurrentParams(message.params),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.sessionsList) {
      return createSuccessResponse(message, await deps.listSessions());
    }

    if (message.method === BROWSER_RPC_METHODS.sessionsRename) {
      return createSuccessResponse(
        message,
        await deps.renameSession(normalizeSessionRenameParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.sessionsRelease) {
      return createSuccessResponse(
        message,
        await deps.releaseSession(
          normalizeSessionIdParams(message.params, 'sessions.release'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.sessionsClose) {
      return createSuccessResponse(
        message,
        await deps.closeSession(
          normalizeSessionIdParams(message.params, 'sessions.close'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsOpen) {
      return createSuccessResponse(
        message,
        await deps.openTab(normalizeTabOpenParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsList) {
      return createSuccessResponse(
        message,
        await deps.listTabs(
          normalizeSessionIdParams(message.params, 'tabs.list'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsUserList) {
      return createSuccessResponse(message, await deps.listUserTabs());
    }

    if (message.method === BROWSER_RPC_METHODS.tabsAttach) {
      return createSuccessResponse(
        message,
        await deps.attachTab(normalizeTabAttachParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsActive) {
      return createSuccessResponse(
        message,
        await deps.getActiveTab(
          normalizeSessionIdParams(message.params, 'tabs.active'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsActivate) {
      return createSuccessResponse(
        message,
        await deps.activateTab(normalizeTabActivateParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsClose) {
      return createSuccessResponse(
        message,
        await deps.closeTab(normalizeTabCloseParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsAttachBatch) {
      return createSuccessResponse(
        message,
        await deps.attachBatchTabs(normalizeTabAttachBatchParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsDetach) {
      return createSuccessResponse(
        message,
        await deps.detachTab(normalizeTabDetachParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.tabsMove) {
      return createSuccessResponse(
        message,
        await deps.moveTab(normalizeTabMoveParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.sessionsUpdate) {
      return createSuccessResponse(
        message,
        await deps.updateSession(normalizeSessionUpdateParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesSnapshot) {
      return createSuccessResponse(
        message,
        await deps.pageSnapshot(normalizePageSnapshotParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesClick) {
      return createSuccessResponse(
        message,
        await deps.pageClick(
          normalizePageRefParams(message.params, 'pages.click'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesFill) {
      return createSuccessResponse(
        message,
        await deps.pageFill(normalizePageFillParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesType) {
      return createSuccessResponse(
        message,
        await deps.pageType(normalizePageTypeParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesPress) {
      return createSuccessResponse(
        message,
        await deps.pagePress(normalizePagePressParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesHover) {
      return createSuccessResponse(
        message,
        await deps.pageHover(
          normalizePageRefParams(message.params, 'pages.hover'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesSelect) {
      return createSuccessResponse(
        message,
        await deps.pageSelect(normalizePageSelectParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesScroll) {
      return createSuccessResponse(
        message,
        await deps.pageScroll(normalizePageScrollParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesScrollIntoView) {
      return createSuccessResponse(
        message,
        await deps.pageScrollIntoView(
          normalizePageRefParams(message.params, 'pages.scrollIntoView'),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesScreenshot) {
      return createSuccessResponse(
        message,
        await deps.pageScreenshot(
          normalizePageScreenshotParams(message.params),
        ),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesGet) {
      return createSuccessResponse(
        message,
        await deps.pageGet(normalizePageGetParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesMouse) {
      return createSuccessResponse(
        message,
        await deps.pageMouse(normalizePageMouseParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesWait) {
      return createSuccessResponse(
        message,
        await deps.pageWait(normalizePageWaitParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesEval) {
      return createSuccessResponse(
        message,
        await deps.pageEval(normalizePageEvalParams(message.params)),
      );
    }

    if (message.method === BROWSER_RPC_METHODS.pagesUpload) {
      const p = ensureObjectParams(message.params, 'Invalid pages.upload params');
      return createSuccessResponse(message, await deps.pageUpload({
        sessionId: normalizeSessionId(p.sessionId),
        ref: normalizeRequiredString(p.ref, 'ref', 'pages.upload'),
        files: Array.isArray(p.files) ? p.files.map(f => String(f)) : [],
      }));
    }

    if (message.method === BROWSER_RPC_METHODS.pagesSavePdf) {
      const p = ensureObjectParams(message.params, 'Invalid pages.savePdf params');
      return createSuccessResponse(message, await deps.pageSavePdf({
        sessionId: normalizeSessionId(p.sessionId),
        ...(typeof p.paperFormat === 'string' ? { paperFormat: p.paperFormat as 'a4' } : {}),
        ...(typeof p.landscape === 'boolean' ? { landscape: p.landscape } : {}),
        ...(typeof p.path === 'string' ? { path: p.path } : {}),
      }));
    }

    if (message.method === BROWSER_RPC_METHODS.networkStart) {
      const p = ensureObjectParams(message.params, 'Invalid network.start params');
      return createSuccessResponse(message, await deps.networkStart({ sessionId: normalizeSessionId(p.sessionId) }));
    }

    if (message.method === BROWSER_RPC_METHODS.networkStop) {
      const p = ensureObjectParams(message.params, 'Invalid network.stop params');
      return createSuccessResponse(message, await deps.networkStop({ sessionId: normalizeSessionId(p.sessionId) }));
    }

    if (message.method === BROWSER_RPC_METHODS.networkList) {
      const p = ensureObjectParams(message.params, 'Invalid network.list params');
      return createSuccessResponse(message, await deps.networkList({
        sessionId: normalizeSessionId(p.sessionId),
        ...(typeof p.filter === 'string' ? { filter: p.filter } : {}),
      }));
    }

    if (message.method === BROWSER_RPC_METHODS.networkDetail) {
      const p = ensureObjectParams(message.params, 'Invalid network.detail params');
      return createSuccessResponse(message, await deps.networkDetail({
        sessionId: normalizeSessionId(p.sessionId),
        requestId: normalizeRequiredString(p.requestId, 'requestId', 'network.detail'),
      }));
    }

    return createErrorResponse(
      message,
      BROWSER_RPC_ERROR_CODE.methodNotFound,
      `Unhandled method: ${message.method}`,
    );
  } catch (error) {
    const messageText = error instanceof Error ? error.message : String(error);
    const code =
      error instanceof BrowserExtensionRpcError
        ? error.code
        : BROWSER_RPC_ERROR_CODE.browserOperationFailed;
    return createErrorResponse(message, code, messageText);
  }
}
