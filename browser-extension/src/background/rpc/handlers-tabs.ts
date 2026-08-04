import type { JsonRpcRequest, JsonRpcResponse } from '../../shared';
import { BROWSER_RPC_METHODS } from '../../shared';
import type { BrowserRequestDependencies } from './types';
import { createSuccessResponse } from './response';
import { normalizeSessionIdParams } from './normalize-session';
import {
  normalizeTabActivateParams,
  normalizeTabAttachBatchParams,
  normalizeTabAttachParams,
  normalizeTabCloseParams,
  normalizeTabDetachParams,
  normalizeTabMoveParams,
  normalizeTabOpenParams,
} from './normalize-tabs';

export async function handleTabMethods(
  message: JsonRpcRequest,
  deps: BrowserRequestDependencies,
): Promise<JsonRpcResponse | null> {
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

  return null;
}
