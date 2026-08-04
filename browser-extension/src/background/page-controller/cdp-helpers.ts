import type { BrowserPageMouseButton, BrowserPagePoint } from '../../shared';
import { createReadyStateExpression } from '../page-runtime';
import type { CdpClient } from '../cdp-client';
import type {
  RuntimeCallFunctionResponse,
  RuntimeEvaluateResponse,
  RuntimeStatus,
} from './types';
import { createPageOperationError, ensureRuntimeOk } from './errors';
import { getMouseButton } from './key-mapping';
import {
  NETWORK_IDLE_EXTRA_WAIT_MS,
  READY_POLL_INTERVAL_MS,
  READY_TIMEOUT_MS,
} from './constants';

export async function evaluate<TResult>(
  client: CdpClient,
  expression: string,
): Promise<TResult> {
  const response = await client.send<RuntimeEvaluateResponse<TResult>>(
    'Runtime.evaluate',
    {
      expression,
      returnByValue: true,
      awaitPromise: false,
    },
  );
  if (response.exceptionDetails) {
    throw createPageOperationError(
      response.exceptionDetails.exception?.description ||
        response.exceptionDetails.text ||
        'Runtime evaluation failed',
    );
  }

  return response.result?.value as TResult;
}

export async function callFunctionOn<TResult>(
  client: CdpClient,
  objectId: string,
  functionDeclaration: string,
  args: unknown[] = [],
): Promise<TResult> {
  const response = await client.send<RuntimeCallFunctionResponse<TResult>>(
    'Runtime.callFunctionOn',
    {
      objectId,
      functionDeclaration,
      arguments: args.map(value => ({ value })),
      returnByValue: true,
      awaitPromise: true,
    },
  );
  if (response.exceptionDetails) {
    throw createPageOperationError(
      response.exceptionDetails.exception?.description ||
        response.exceptionDetails.text ||
        'Runtime call failed',
    );
  }
  return response.result?.value as TResult;
}

export function dispatchMouseMove(
  client: CdpClient,
  x: number,
  y: number,
): Promise<void> {
  return client.send('Input.dispatchMouseEvent', {
    type: 'mouseMoved',
    x,
    y,
    button: 'none',
  });
}

export function dispatchMouseButton(
  client: CdpClient,
  type: 'mousePressed' | 'mouseReleased',
  point: BrowserPagePoint,
  button: BrowserPageMouseButton | undefined,
): Promise<void> {
  return client.send('Input.dispatchMouseEvent', {
    type,
    x: point.x,
    y: point.y,
    button: getMouseButton(button),
    clickCount: 1,
  });
}

export async function assertClickPointNotCovered(
  client: CdpClient,
  objectId: string,
  point: BrowserPagePoint,
): Promise<void> {
  const result = await callFunctionOn<RuntimeStatus>(
    client,
    objectId,
    `function(x, y) {
      const hit = document.elementFromPoint(x, y);
      if (!hit || hit === this || this.contains(hit) || hit.contains(this)) {
        return { ok: true };
      }
      const id = hit.id ? '#' + hit.id : '';
      const classes = typeof hit.className === 'string' && hit.className
        ? '.' + hit.className.trim().split(/\\s+/).slice(0, 3).join('.')
        : '';
      return {
        ok: false,
        error: 'covered by <' + hit.tagName.toLowerCase() + id + classes + '>'
      };
    }`,
    [point.x, point.y],
  );
  ensureRuntimeOk(result);
}

export async function waitForLoadState(
  client: CdpClient,
  load: string,
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < READY_TIMEOUT_MS) {
    const ready = await evaluate<boolean>(
      client,
      createReadyStateExpression(load),
    );
    if (ready) {
      if (load === 'networkidle') {
        await new Promise(resolve =>
          setTimeout(resolve, NETWORK_IDLE_EXTRA_WAIT_MS),
        );
      }
      return;
    }
    await new Promise(resolve => setTimeout(resolve, READY_POLL_INTERVAL_MS));
  }

  throw createPageOperationError(`Timed out waiting for load state: ${load}`);
}
