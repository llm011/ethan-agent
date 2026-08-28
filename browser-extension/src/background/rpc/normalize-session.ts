import type {
  BrowserSessionAttachCurrentParams,
  BrowserSessionCreateParams,
  BrowserSessionRenameParams,
  BrowserSessionUpdateParams,
} from '../../shared';
import {
  ensureObjectParams,
  normalizeHttpUrl,
  normalizeOptionalTitle,
  normalizeRequiredTitle,
  normalizeSessionId,
} from './params-helpers';

export function normalizeSessionCreateParams(
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
    ...(typeof nextParams.background === 'boolean'
      ? { background: nextParams.background }
      : {}),
    ...(typeof nextParams.color === 'string'
      ? { color: nextParams.color.trim() }
      : {}),
  };
}

export function normalizeSessionAttachCurrentParams(
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

export function normalizeSessionRenameParams(
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

export function normalizeSessionIdParams(
  params: unknown,
  context: string,
): { sessionId: string } {
  const nextParams = ensureObjectParams(params, `Invalid ${context} params`);
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
  };
}

export function normalizeSessionUpdateParams(params: unknown): BrowserSessionUpdateParams {
  const nextParams = ensureObjectParams(params, 'Invalid sessions.update params');
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    ...(typeof nextParams.title === 'string' ? { title: nextParams.title.trim() } : {}),
    ...(typeof nextParams.color === 'string' ? { color: nextParams.color.trim() } : {}),
  };
}
