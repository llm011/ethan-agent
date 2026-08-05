import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserExtensionRpcError } from '../session-store';
import type { RuntimeStatus } from './types';

export function createRefNotFoundError(ref: string): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserPageRefNotFound,
    `Snapshot ref ${ref} not found. Run page snapshot again.`,
  );
}

export function createPageOperationError(
  message: string,
): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserPageOperationFailed,
    message,
  );
}

export function ensureRuntimeOk(result: RuntimeStatus, ref?: string): void {
  if (result.ok) {
    return;
  }

  if (result.error === 'REF_NOT_FOUND' && ref) {
    throw createRefNotFoundError(ref);
  }

  throw createPageOperationError(result.error || 'Page operation failed');
}
