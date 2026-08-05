import type { JsonRpcRequest, JsonRpcResponse } from '../../shared';
import { BROWSER_RPC_METHODS } from '../../shared';
import type { BrowserRequestDependencies } from './types';
import { createSuccessResponse } from './response';
import {
  ensureObjectParams,
  normalizeRequiredString,
  normalizeSessionId,
} from './params-helpers';

export async function handleNetworkMethods(
  message: JsonRpcRequest,
  deps: BrowserRequestDependencies,
): Promise<JsonRpcResponse | null> {
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

  return null;
}
