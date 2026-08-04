import type { JsonRpcRequest, JsonRpcResponse } from '../../shared';
import { BROWSER_RPC_METHODS } from '../../shared';
import type { BrowserRequestDependencies } from './types';
import { createSuccessResponse } from './response';
import {
  ensureObjectParams,
  normalizeRequiredString,
  normalizeSessionId,
} from './params-helpers';
import {
  normalizePageEvalParams,
  normalizePageFillParams,
  normalizePageGetParams,
  normalizePageMouseParams,
  normalizePagePressParams,
  normalizePageRefParams,
  normalizePageScreenshotParams,
  normalizePageScrollParams,
  normalizePageSelectParams,
  normalizePageSnapshotParams,
  normalizePageTypeParams,
  normalizePageWaitParams,
} from './normalize-pages';

export async function handlePageMethods(
  message: JsonRpcRequest,
  deps: BrowserRequestDependencies,
): Promise<JsonRpcResponse | null> {
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

  return null;
}
