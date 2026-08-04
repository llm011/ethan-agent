import { BROWSER_RPC_ERROR_CODE } from '../../shared';

export class BrowserExtensionRpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
  }
}

export function createSessionNotFoundError(
  sessionId: string,
): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserSessionNotFound,
    `Session ${sessionId} not found`,
  );
}
