import type { BrowserPagePoint, BrowserSessionTab } from '../../shared';
import type { CdpClient } from '../cdp-client';
import type { BrowserPageRefStore } from '../ref-store';
import type { DomGetBoxModelResult, DomResolveNodeResult, ResolvedRef } from './types';
import { createRefNotFoundError } from './errors';
import { assertClickPointNotCovered } from './cdp-helpers';
import { DEFAULT_MOUSE_X, DEFAULT_MOUSE_Y } from './constants';

export async function resolveRef(
  refStore: BrowserPageRefStore,
  client: CdpClient,
  tab: BrowserSessionTab,
  ref: string,
  checkCovered: boolean,
): Promise<ResolvedRef> {
  const entry = refStore.get(tab.tabId, ref);
  if (!entry || typeof entry.backendNodeId !== 'number') {
    throw createRefNotFoundError(ref);
  }

  await client.send('DOM.scrollIntoViewIfNeeded', {
    backendNodeId: entry.backendNodeId,
  });
  const [boxModel, resolvedNode] = await Promise.all([
    client.send<DomGetBoxModelResult>('DOM.getBoxModel', {
      backendNodeId: entry.backendNodeId,
    }),
    client.send<DomResolveNodeResult>('DOM.resolveNode', {
      backendNodeId: entry.backendNodeId,
      objectGroup: 'ethan-browser',
    }),
  ]);
  const objectId = resolvedNode.object.objectId;
  if (!objectId) {
    throw createRefNotFoundError(ref);
  }
  const quad = boxModel.model.content || boxModel.model.border || [];
  const xs = [quad[0], quad[2], quad[4], quad[6]].filter(
    (value): value is number => typeof value === 'number',
  );
  const ys = [quad[1], quad[3], quad[5], quad[7]].filter(
    (value): value is number => typeof value === 'number',
  );
  const x = xs.length
    ? xs.reduce((sum, value) => sum + value, 0) / xs.length
    : DEFAULT_MOUSE_X;
  const y = ys.length
    ? ys.reduce((sum, value) => sum + value, 0) / ys.length
    : DEFAULT_MOUSE_Y;
  const box = {
    x: Math.round(Math.min(...xs, x)),
    y: Math.round(Math.min(...ys, y)),
    width: Math.round(boxModel.model.width),
    height: Math.round(boxModel.model.height),
  };
  const center: BrowserPagePoint = {
    x: Math.round(x),
    y: Math.round(y),
  };

  if (checkCovered) {
    await assertClickPointNotCovered(client, objectId, center);
  }

  return {
    entry,
    objectId,
    box,
    center,
  };
}
