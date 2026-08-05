import type { BrowserPageViewport } from '../../shared';
import type { CdpClient } from '../cdp-client';
import type {
  DomDescribeNodeResult,
  DomGetDocumentResult,
  DomQuerySelectorResult,
  RuntimeEvaluateResponse,
} from './types';
import { collectBackendNodeIds } from './tree-utils';
import { stringifyValue } from './utils';

export async function getViewport(client: CdpClient): Promise<BrowserPageViewport> {
  const result = await client.send<
    RuntimeEvaluateResponse<BrowserPageViewport>
  >('Runtime.evaluate', {
    expression: `(() => ({
        width: Math.round(window.innerWidth || document.documentElement.clientWidth || 0),
        height: Math.round(window.innerHeight || document.documentElement.clientHeight || 0),
        deviceScaleFactor: window.devicePixelRatio || 1
      }))()`,
    returnByValue: true,
    awaitPromise: false,
  });
  return (
    result.result?.value || {
      width: 0,
      height: 0,
      deviceScaleFactor: 1,
    }
  );
}

export async function getScopedBackendNodeIds(
  client: CdpClient,
  selector: string | undefined,
): Promise<Set<number> | undefined> {
  if (!selector) {
    return undefined;
  }

  const documentResult = await client.send<DomGetDocumentResult>(
    'DOM.getDocument',
    {
      depth: 0,
      pierce: true,
    },
  );
  const queryResult = await client.send<DomQuerySelectorResult>(
    'DOM.querySelector',
    {
      nodeId: documentResult.root.nodeId,
      selector,
    },
  );
  if (!queryResult.nodeId) {
    throw new Error(`Snapshot selector not found: ${selector}`);
  }

  const described = await client.send<DomDescribeNodeResult>(
    'DOM.describeNode',
    {
      nodeId: queryResult.nodeId,
      depth: -1,
      pierce: true,
    },
  );
  const output = new Set<number>();
  collectBackendNodeIds(described.node, output);
  return output;
}

export async function getHref(
  client: CdpClient,
  backendNodeId: number,
): Promise<string | undefined> {
  const resolved = await client.send<{ object: { objectId?: string } }>(
    'DOM.resolveNode',
    {
      backendNodeId,
      objectGroup: 'ethan-browser',
    },
  );
  const objectId = resolved.object.objectId;
  if (!objectId) {
    return undefined;
  }
  const href = await client.send<RuntimeEvaluateResponse<string>>(
    'Runtime.callFunctionOn',
    {
      objectId,
      functionDeclaration: `function() {
      return this.href || this.getAttribute?.('href') || '';
    }`,
      returnByValue: true,
      awaitPromise: false,
    },
  );
  return stringifyValue(href.result?.value) || undefined;
}
