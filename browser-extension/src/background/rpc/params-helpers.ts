import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserExtensionRpcError } from '../session-store';

export function createInvalidParamsError(message: string): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.invalidParams,
    message,
  );
}

export function ensureObjectParams(
  params: unknown,
  message: string,
): Record<string, unknown> {
  if (!params || typeof params !== 'object') {
    throw createInvalidParamsError(message);
  }

  return params as Record<string, unknown>;
}

export function normalizeHttpUrl(value: unknown, context: string): string {
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

export function normalizeSessionId(value: unknown): string {
  const sessionId = typeof value === 'string' ? value.trim() : '';
  if (!sessionId) {
    throw new BrowserExtensionRpcError(
      BROWSER_RPC_ERROR_CODE.browserSessionRequired,
      'Missing browser session id',
    );
  }

  return sessionId;
}

export function normalizeOptionalTitle(value: unknown): string | undefined {
  const title = typeof value === 'string' ? value.trim() : '';
  return title || undefined;
}

export function normalizeRequiredTitle(value: unknown): string {
  const title = normalizeOptionalTitle(value);
  if (!title) {
    throw createInvalidParamsError('Invalid sessions.rename title');
  }

  return title;
}

export function normalizeTabId(value: unknown, context: string): number {
  const tabId =
    typeof value === 'string' && value.trim() ? Number(value) : value;
  if (!Number.isInteger(tabId) || Number(tabId) <= 0) {
    throw createInvalidParamsError(`Invalid ${context} tabId`);
  }

  return Number(tabId);
}

export function normalizeRequiredString(
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

export function normalizeNumber(
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

export function normalizePositiveNumber(
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
