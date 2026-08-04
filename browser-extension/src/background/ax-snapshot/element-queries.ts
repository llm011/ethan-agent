import type { CdpClient } from '../cdp-client';
import type {
  CursorElementInfo,
  DomDescribeNodeResult,
  DomGetDocumentResult,
  DomQuerySelectorResult,
  RuntimeEvaluateResponse,
} from './types';
import { literal } from './utils';

export async function getCursorElements(
  client: CdpClient,
): Promise<Map<number, CursorElementInfo>> {
  const token = `ethan-browser-ci-${Date.now()}-${Math.random()
    .toString(16)
    .slice(2)}`;
  const expression = `(() => {
    const token = ${literal(token)};
    const interactiveTags = new Set(['a', 'button', 'input', 'select', 'textarea', 'details', 'summary']);
    const interactiveRoles = new Set(['button', 'link', 'checkbox', 'radio', 'switch', 'menuitem', 'tab', 'textbox', 'combobox']);
    const trim = value => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, 160);
    const elements = [];
    let index = 0;
    for (const el of Array.from(document.querySelectorAll('*'))) {
      const tag = el.tagName.toLowerCase();
      const role = String(el.getAttribute('role') || '').toLowerCase();
      if (interactiveTags.has(tag) || interactiveRoles.has(role)) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue;
      const style = getComputedStyle(el);
      const hasCursorPointer = style.cursor === 'pointer';
      const hasOnClick = el.hasAttribute('onclick') || el.onclick !== null;
      const hasTabIndex = el.hasAttribute('tabindex');
      const isEditable = el.isContentEditable;
      if (!hasCursorPointer && !hasOnClick && !hasTabIndex && !isEditable) continue;
      if (hasCursorPointer && !hasOnClick && !hasTabIndex && !isEditable) {
        const parent = el.parentElement;
        if (parent && getComputedStyle(parent).cursor === 'pointer') continue;
      }
      const text = trim(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title'));
      if (!text) continue;
      const hiddenInput = el.matches('label') && el.control
        ? el.control
        : el.querySelector('input[type="radio"], input[type="checkbox"]');
      const marker = token + '-' + index;
      el.setAttribute('data-ethan-browser-ci', marker);
      index += 1;
      elements.push({
        marker,
        role: hiddenInput?.type || (isEditable ? 'textbox' : 'clickable'),
        name: text,
        text,
        kind: hasCursorPointer || hasOnClick ? 'clickable' : isEditable ? 'editable' : 'focusable',
        hints: [
          hasCursorPointer ? 'cursor:pointer' : '',
          hasOnClick ? 'onclick' : '',
          hasTabIndex ? 'tabindex' : '',
          isEditable ? 'contenteditable' : ''
        ].filter(Boolean),
        checked: hiddenInput ? String(hiddenInput.checked) : undefined
      });
    }
    return elements;
  })()`;
  const runtime = await client.send<
    RuntimeEvaluateResponse<
      Array<Omit<CursorElementInfo, 'backendNodeId'> & { marker: string }>
    >
  >('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: false,
  });
  const candidates = runtime.result?.value || [];
  const documentResult = await client.send<DomGetDocumentResult>(
    'DOM.getDocument',
    {
      depth: 0,
      pierce: true,
    },
  );
  const output = new Map<number, CursorElementInfo>();
  for (const candidate of candidates) {
    const queryResult = await client.send<DomQuerySelectorResult>(
      'DOM.querySelector',
      {
        nodeId: documentResult.root.nodeId,
        selector: `[data-ethan-browser-ci="${candidate.marker}"]`,
      },
    );
    if (!queryResult.nodeId) {
      continue;
    }
    const described = await client.send<DomDescribeNodeResult>(
      'DOM.describeNode',
      {
        nodeId: queryResult.nodeId,
        depth: 0,
      },
    );
    const backendNodeId = described.node.backendNodeId;
    if (typeof backendNodeId !== 'number') {
      continue;
    }
    output.set(backendNodeId, {
      backendNodeId,
      role: candidate.role,
      name: candidate.name,
      text: candidate.text,
      kind: candidate.kind,
      hints: candidate.hints,
      checked: candidate.checked,
    });
  }
  void client.send('Runtime.evaluate', {
    expression: `document.querySelectorAll('[data-ethan-browser-ci]').forEach(el => el.removeAttribute('data-ethan-browser-ci'))`,
    returnByValue: true,
    awaitPromise: false,
  });
  return output;
}

/**
 * 批量获取元素的可见性、bbox、是否浮层信息。
 * 一次 eval 拿到所有 backendNodeId 对应的元素状态，避免逐个 CDP 调用。
 */
export async function getElementsVisibility(
  client: CdpClient,
  backendNodeIds: number[],
): Promise<
  Map<number, { visible: boolean; bbox?: { x: number; y: number; w: number; h: number }; overlay?: boolean }>
> {
  if (backendNodeIds.length === 0) {
    return new Map();
  }
  // 用 backendNodeId → objectId → evaluate 的方式批量获取
  // 但 CDP 没有批量 resolveNode，所以用 DOM.requestNode + 一次性 eval
  // 这里用标记法：给每个元素打 data 属性，然后一次 eval 读取所有信息
  const token = `ethan-vis-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const markers: string[] = [];
  const idToMarker = new Map<number, string>();
  for (let i = 0; i < backendNodeIds.length; i++) {
    const marker = `${token}-${i}`;
    markers.push(marker);
    idToMarker.set(backendNodeIds[i], marker);
  }

  // 逐个标记元素（用 resolveNode + setAttribute）
  const validIds: number[] = [];
  for (let i = 0; i < backendNodeIds.length; i++) {
    const id = backendNodeIds[i];
    const marker = markers[i];
    try {
      const resolved = await client.send<{ object: { objectId?: string } }>(
        'DOM.resolveNode',
        { backendNodeId: id, objectGroup: 'ethan-browser' },
      );
      const objectId = resolved.object.objectId;
      if (!objectId) continue;
      await client.send('Runtime.callFunctionOn', {
        objectId,
        functionDeclaration: `function(marker) { this.setAttribute('data-ethan-vis', marker); }`,
        arguments: [{ value: marker }],
        returnByValue: true,
        awaitPromise: false,
      });
      validIds.push(id);
    } catch {
      // element may be detached
    }
  }

  // 一次性 eval 读取所有标记元素的信息
  const expr = `(() => {
    const token = ${literal(token)};
    const els = document.querySelectorAll('[data-ethan-vis^="' + token + '"]');
    const result = {};
    for (const el of els) {
      const marker = el.getAttribute('data-ethan-vis');
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      const isFixed = style.position === 'fixed' || style.position === 'sticky';
      // offsetParent === null 表示不可见（display:none / 父级隐藏），但 fixed 元素除外
      const offsetParent = el.offsetParent;
      const visible = (offsetParent !== null || isFixed) && rect.width > 0 && rect.height > 0
        && style.visibility !== 'hidden' && style.display !== 'none';
      result[marker] = {
        visible,
        bbox: visible ? { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) } : null,
        overlay: isFixed && visible,
      };
    }
    // 清理标记
    document.querySelectorAll('[data-ethan-vis]').forEach(el => el.removeAttribute('data-ethan-vis'));
    return result;
  })()`;

  const runtime = await client.send<
    RuntimeEvaluateResponse<Record<string, { visible: boolean; bbox: { x: number; y: number; w: number; h: number } | null; overlay: boolean }>>
  >('Runtime.evaluate', {
    expression: expr,
    returnByValue: true,
    awaitPromise: false,
  });

  const data = runtime.result?.value || {};
  const output = new Map<number, { visible: boolean; bbox?: { x: number; y: number; w: number; h: number }; overlay?: boolean }>();
  for (const id of validIds) {
    const marker = idToMarker.get(id);
    if (!marker) continue;
    const info = data[marker];
    if (!info) continue;
    output.set(id, {
      visible: info.visible,
      ...(info.bbox ? { bbox: info.bbox } : {}),
      ...(info.overlay ? { overlay: true } : {}),
    });
  }
  return output;
}
