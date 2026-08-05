import type {
  BrowserPageActionResult,
  BrowserPageEvalParams,
  BrowserPageEvalResult,
  BrowserPageGetParams,
  BrowserPageGetResult,
  BrowserPageSnapshotParams,
  BrowserPageSnapshotResult,
  BrowserPageWaitParams,
  BrowserPageWaitResult,
} from '../../shared';
import { takeAxSnapshot } from '../ax-snapshot';
import { createScrollExpression } from '../page-runtime';
import type {
  GetRuntimeResult,
  PageControllerContext,
  RuntimeEvaluateResponse,
  RuntimeStatus,
} from './types';
import {
  callFunctionOn,
  evaluate,
  waitForLoadState,
} from './cdp-helpers';
import { resolveRef } from './ref-resolver';
import { createPageOperationError, ensureRuntimeOk } from './errors';

export async function snapshotAction(
  ctx: PageControllerContext,
  params: BrowserPageSnapshotParams,
): Promise<BrowserPageSnapshotResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const snapshot = await takeAxSnapshot(client, params);
    ctx.refStore.reset(tab.tabId, snapshot.refs);
    return {
      ...ctx.createBaseResult(params.sessionId, tab),
      origin: tab.url || '',
      snapshot: snapshot.snapshot,
      refs: ctx.refStore.toRecord(tab.tabId),
      viewport: snapshot.viewport,
      elements: snapshot.elements,
    };
  });
}

export async function getAction(
  ctx: PageControllerContext,
  params: BrowserPageGetParams,
): Promise<BrowserPageGetResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    if (params.what === 'title' || params.what === 'url') {
      const value = await evaluate<string>(
        client,
        params.what === 'title' ? 'document.title' : 'location.href',
      );
      return {
        ...ctx.createBaseResult(params.sessionId, tab),
        what: params.what,
        value,
      };
    }

    const resolved = await resolveRef(
      ctx.refStore,
      client,
      tab,
      params.ref || '',
      false,
    );
    const result = await callFunctionOn<GetRuntimeResult>(
      client,
      resolved.objectId,
      `function(what) {
        if (what === 'box') {
          const rect = this.getBoundingClientRect();
          return {
            ok: true,
            box: {
              x: Math.round(rect.x),
              y: Math.round(rect.y),
              width: Math.round(rect.width),
              height: Math.round(rect.height)
            }
          };
        }
        if (what === 'html') return { ok: true, value: this.outerHTML };
        if (what === 'value') return { ok: true, value: 'value' in this ? this.value : null };
        return { ok: true, value: this.innerText || this.textContent || '' };
      }`,
      [params.what],
    );
    ensureRuntimeOk(result, params.ref);
    return {
      ...ctx.createBaseResult(params.sessionId, tab),
      what: params.what,
      ...(result.box ? { box: result.box } : { value: result.value }),
    };
  });
}

export async function evalAction(
  ctx: PageControllerContext,
  params: BrowserPageEvalParams,
): Promise<BrowserPageEvalResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const response = await client.send<RuntimeEvaluateResponse<unknown>>(
      'Runtime.evaluate',
      {
        expression: params.script,
        returnByValue: true,
        awaitPromise: params.awaitPromise !== false,
      },
    );
    if (response.exceptionDetails) {
      throw createPageOperationError(
        response.exceptionDetails.exception?.description ||
          response.exceptionDetails.text ||
          'Runtime evaluation failed',
      );
    }
    return {
      ...ctx.createBaseResult(params.sessionId, tab),
      origin: tab.url || '',
      result:
        typeof response.result?.value !== 'undefined'
          ? response.result.value
          : (response.result?.description ?? null),
    };
  });
}

export async function scrollAction(
  ctx: PageControllerContext,
  params: {
    sessionId: string;
    direction: 'up' | 'down';
    pixels: number;
  },
): Promise<BrowserPageActionResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    ensureRuntimeOk(
      await evaluate<RuntimeStatus>(
        client,
        createScrollExpression(params.direction, params.pixels),
      ),
    );
    return ctx.createActionResult(params.sessionId, tab);
  });
}

export async function waitAction(
  ctx: PageControllerContext,
  params: BrowserPageWaitParams,
): Promise<BrowserPageWaitResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    if (typeof params.ms === 'number') {
      await new Promise(resolve => setTimeout(resolve, params.ms));
    }
    if (params.load) {
      await waitForLoadState(client, params.load);
    }
    return {
      ...ctx.createBaseResult(params.sessionId, tab),
      ...(typeof params.ms === 'number' ? { waitedMs: params.ms } : {}),
      ...(params.load ? { load: params.load } : {}),
    };
  });
}
