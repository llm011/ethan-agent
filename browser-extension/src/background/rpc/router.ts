/* eslint-disable -- request router keeps all protocol methods in one place. */
import type { JsonRpcRequest, JsonRpcResponse } from '../../shared';
import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserExtensionRpcError } from '../session-store';
import type { BrowserRequestDependencies } from './types';
import { ALLOWED_METHODS } from './types';
import { createErrorResponse, isJsonRpcRequest } from './response';
import { handleNetworkMethods } from './handlers-network';
import { handlePageMethods } from './handlers-pages';
import { handleSessionMethods } from './handlers-session';
import { handleTabMethods } from './handlers-tabs';

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
    const sessionResult = await handleSessionMethods(message, deps);
    if (sessionResult) {
      return sessionResult;
    }

    const tabResult = await handleTabMethods(message, deps);
    if (tabResult) {
      return tabResult;
    }

    const pageResult = await handlePageMethods(message, deps);
    if (pageResult) {
      return pageResult;
    }

    const networkResult = await handleNetworkMethods(message, deps);
    if (networkResult) {
      return networkResult;
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
