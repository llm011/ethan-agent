import type { JsonRpcRequest, JsonRpcResponse } from '../../shared';
import { BROWSER_RPC_METHODS } from '../../shared';
import type { BrowserRequestDependencies } from './types';
import { createSuccessResponse } from './response';
import {
  normalizeSessionAttachCurrentParams,
  normalizeSessionCreateParams,
  normalizeSessionIdParams,
  normalizeSessionRenameParams,
  normalizeSessionUpdateParams,
} from './normalize-session';

export async function handleSessionMethods(
  message: JsonRpcRequest,
  deps: BrowserRequestDependencies,
): Promise<JsonRpcResponse | null> {
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

  if (message.method === BROWSER_RPC_METHODS.sessionsUpdate) {
    return createSuccessResponse(
      message,
      await deps.updateSession(normalizeSessionUpdateParams(message.params)),
    );
  }

  return null;
}
