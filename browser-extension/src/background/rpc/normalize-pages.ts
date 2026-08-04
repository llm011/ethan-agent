import type {
  BrowserPageEvalParams,
  BrowserPageFillParams,
  BrowserPageGetParams,
  BrowserPageMouseButton,
  BrowserPageMouseParams,
  BrowserPagePressParams,
  BrowserPageScreenshotFormat,
  BrowserPageScreenshotParams,
  BrowserPageScrollDirection,
  BrowserPageScrollParams,
  BrowserPageSelectParams,
  BrowserPageSnapshotParams,
  BrowserPageTypeParams,
  BrowserPageWaitParams,
} from '../../shared';
import {
  createInvalidParamsError,
  ensureObjectParams,
  normalizeNumber,
  normalizePositiveNumber,
  normalizeRequiredString,
  normalizeSessionId,
} from './params-helpers';

export function normalizePageBaseParams(
  params: unknown,
  context: string,
): { sessionId: string } {
  const nextParams = ensureObjectParams(params, `Invalid ${context} params`);
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
  };
}

export function normalizePageRefParams(
  params: unknown,
  context: string,
): { sessionId: string; ref: string } {
  const nextParams = ensureObjectParams(params, `Invalid ${context} params`);
  return {
    sessionId: normalizeSessionId(nextParams.sessionId),
    ref: normalizeRequiredString(nextParams.ref, 'ref', context),
  };
}

export function normalizePageSnapshotParams(
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

export function normalizePageFillParams(params: unknown): BrowserPageFillParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.fill params');
  return {
    ...normalizePageRefParams(params, 'pages.fill'),
    text:
      typeof nextParams.text === 'string'
        ? nextParams.text
        : normalizeRequiredString(nextParams.text, 'text', 'pages.fill'),
  };
}

export function normalizePageTypeParams(params: unknown): BrowserPageTypeParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.type params');
  return {
    ...normalizePageRefParams(params, 'pages.type'),
    text:
      typeof nextParams.text === 'string'
        ? nextParams.text
        : normalizeRequiredString(nextParams.text, 'text', 'pages.type'),
  };
}

export function normalizePageSelectParams(params: unknown): BrowserPageSelectParams {
  const nextParams = ensureObjectParams(params, 'Invalid pages.select params');
  return {
    ...normalizePageRefParams(params, 'pages.select'),
    value: normalizeRequiredString(nextParams.value, 'value', 'pages.select'),
  };
}

export function normalizePagePressParams(params: unknown): BrowserPagePressParams {
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

export function normalizePageScrollParams(params: unknown): BrowserPageScrollParams {
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

export function normalizePageScreenshotParams(
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

export function normalizePageGetParams(params: unknown): BrowserPageGetParams {
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

export function normalizePageMouseParams(params: unknown): BrowserPageMouseParams {
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

export function normalizePageWaitParams(params: unknown): BrowserPageWaitParams {
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

export function normalizePageEvalParams(params: unknown): BrowserPageEvalParams {
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
