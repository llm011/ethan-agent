/* eslint-disable max-lines, max-lines-per-function, complexity -- AX tree rendering is easier to audit in one module */
import type {
  BrowserPageSnapshotElement,
  BrowserPageSnapshotParams,
  BrowserPageViewport,
} from '../shared';

import type { CdpClient } from './cdp-client';
import type { BrowserPageRefEntry } from './ref-store';

const INTERACTIVE_ROLES = new Set([
  'button',
  'link',
  'textbox',
  'combobox',
  'checkbox',
  'radio',
  'switch',
  'menuitem',
  'option',
  'tab',
  'treeitem',
  'Iframe',
]);
const CONTENT_ROLES = new Set([
  'heading',
  'cell',
  'row',
  'paragraph',
  'text',
  'StaticText',
  'LabelText',
]);
const STRUCTURAL_ROLES = new Set([
  'generic',
  'group',
  'list',
  'listitem',
  'navigation',
  'main',
  'banner',
  'contentinfo',
  'RootWebArea',
  'WebArea',
]);
const MAX_NAME_LENGTH = 100;
const EMPTY_SNAPSHOT = '(empty page)';
const EMPTY_INTERACTIVE_SNAPSHOT = '(no interactive elements)';

interface CdpPropertyValue {
  value?: unknown;
}

interface CdpAxNode {
  nodeId: string;
  ignored?: boolean;
  role?: CdpPropertyValue;
  name?: CdpPropertyValue;
  value?: CdpPropertyValue;
  description?: CdpPropertyValue;
  childIds?: string[];
  backendDOMNodeId?: number;
  frameId?: string;
}

interface CdpAxTreeResult {
  nodes: CdpAxNode[];
}

interface DomDescribeNodeResult {
  node: DomNode;
}

interface DomGetDocumentResult {
  root: {
    nodeId: number;
  };
}

interface DomQuerySelectorResult {
  nodeId: number;
}

interface DomNode {
  backendNodeId?: number;
  children?: DomNode[];
}

interface RuntimeEvaluateResponse<TValue> {
  result?: {
    objectId?: string;
    value?: TValue;
  };
}

interface CursorElementInfo {
  backendNodeId: number;
  role: string;
  name: string;
  text: string;
  kind: string;
  hints: string[];
  checked?: string;
}

interface SnapshotNode {
  ax: CdpAxNode;
  role: string;
  name: string;
  value?: string;
  ignored: boolean;
  parentId?: string;
  children: string[];
  depth: number;
  renderDepth?: number;
  refable?: boolean;
  ref?: string;
  href?: string;
  cursor?: CursorElementInfo;
  bbox?: { x: number; y: number; w: number; h: number };
  overlay?: boolean;
  visible?: boolean;
}

export interface AxSnapshotResult {
  snapshot: string;
  elements: BrowserPageSnapshotElement[];
  refs: BrowserPageRefEntry[];
  viewport: BrowserPageViewport;
}

function stringifyValue(value: unknown): string {
  if (value === null || typeof value === 'undefined') {
    return '';
  }
  return String(value).replace(/\s+/g, ' ').trim().slice(0, MAX_NAME_LENGTH);
}

function literal(value: unknown): string {
  return JSON.stringify(value);
}

function getAxValue(property: CdpPropertyValue | undefined): string {
  return stringifyValue(property?.value);
}

function getNodeRole(node: CdpAxNode): string {
  return getAxValue(node.role) || 'generic';
}

function getNodeName(node: CdpAxNode): string {
  return getAxValue(node.name || node.value || node.description);
}

/**
 * 检查元素是否为密码字段，需要遮蔽 value。
 * 通过 backendNodeId 查询 DOM 节点的 tagName 和 type 属性。
 * 缓存结果避免重复 CDP 调用。
 */
async function detectPasswordFields(
  client: CdpClient,
  nodes: Map<string, SnapshotNode>,
): Promise<Set<string>> {
  const passwordNodeIds = new Set<string>();
  // 收集所有 textbox/combobox 角色的节点
  const candidates: { nodeId: string; backendNodeId: number }[] = [];
  nodes.forEach(node => {
    if (
      (node.role === 'textbox' || node.role === 'combobox') &&
      typeof node.ax.backendDOMNodeId === 'number'
    ) {
      candidates.push({
        nodeId: node.ax.nodeId,
        backendNodeId: node.ax.backendDOMNodeId,
      });
    }
  });
  if (candidates.length === 0) return passwordNodeIds;

  // 批量检测：用标记法一次性查
  const token = `ethan-pw-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  for (let i = 0; i < candidates.length; i++) {
    try {
      const resolved = await client.send<{ object: { objectId?: string } }>(
        'DOM.resolveNode',
        { backendNodeId: candidates[i].backendNodeId, objectGroup: 'ethan-browser' },
      );
      const objectId = resolved.object.objectId;
      if (!objectId) continue;
      await client.send('Runtime.callFunctionOn', {
        objectId,
        functionDeclaration: `function(marker) { this.setAttribute('data-ethan-pw', marker); }`,
        arguments: [{ value: `${token}-${i}` }],
        returnByValue: true,
        awaitPromise: false,
      });
    } catch {
      // detached
    }
  }

  const expr = `(() => {
    const token = ${literal(token)};
    const els = document.querySelectorAll('[data-ethan-pw^="' + token + '"]');
    const result = {};
    for (const el of els) {
      const marker = el.getAttribute('data-ethan-pw');
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute('type') || '').toLowerCase();
      const isPassword = tag === 'input' && type === 'password';
      const isSensitive = el.getAttribute('autocomplete') === 'off' && (type === 'text' || type === '');
      result[marker] = { isPassword, isSensitive };
    }
    document.querySelectorAll('[data-ethan-pw]').forEach(el => el.removeAttribute('data-ethan-pw'));
    return result;
  })()`;

  const runtime = await client.send<
    RuntimeEvaluateResponse<Record<string, { isPassword: boolean; isSensitive: boolean }>>
  >('Runtime.evaluate', {
    expression: expr,
    returnByValue: true,
    awaitPromise: false,
  });

  const data = runtime.result?.value || {};
  for (let i = 0; i < candidates.length; i++) {
    const info = data[`${token}-${i}`];
    if (info && (info.isPassword || info.isSensitive)) {
      passwordNodeIds.add(candidates[i].nodeId);
    }
  }
  return passwordNodeIds;
}

function getActions(role: string): string[] {
  const actions = new Set<string>();
  if (
    [
      'button',
      'link',
      'checkbox',
      'radio',
      'switch',
      'menuitem',
      'tab',
      'clickable',
    ].includes(role)
  ) {
    actions.add('click');
  }
  if (['textbox', 'combobox', 'editable'].includes(role)) {
    actions.add('click');
    actions.add('fill');
    actions.add('type');
  }
  if (role === 'focusable') {
    actions.add('click');
  }
  if (role === 'combobox' || role === 'option') {
    actions.add('select');
  }
  actions.add('focus');
  return Array.from(actions);
}

function collectBackendNodeIds(
  node: DomNode | undefined,
  output: Set<number>,
): void {
  if (!node) {
    return;
  }
  if (typeof node.backendNodeId === 'number') {
    output.add(node.backendNodeId);
  }
  node.children?.forEach(child => collectBackendNodeIds(child, output));
}

function getRoots(nodes: Map<string, SnapshotNode>): SnapshotNode[] {
  return Array.from(nodes.values()).filter(
    node => !node.parentId || !nodes.has(node.parentId),
  );
}

function isStructural(node: SnapshotNode): boolean {
  return STRUCTURAL_ROLES.has(node.role);
}

// 不渲染的 role：InlineTextBox 是 StaticText 的子节点，文本完全重复
const SKIP_ROLES = new Set(['InlineTextBox']);

function shouldRender(
  node: SnapshotNode,
  options: BrowserPageSnapshotParams,
): boolean {
  if (node.ignored) {
    return false;
  }
  // 不可见的节点不渲染（visible=false 已标记）
  if (node.visible === false) {
    return false;
  }
  // 跳过 InlineTextBox 等冗余角色（省 ~27% 体积）
  if (SKIP_ROLES.has(node.role)) {
    return false;
  }
  // 无名称的 image 节点对 AI 无信息价值
  if (node.role === 'image' && !node.name) {
    return false;
  }
  // 空名称的 StaticText 是空白占位符
  if (node.role === 'StaticText' && !node.name.trim()) {
    return false;
  }
  if (options.interactive) {
    return Boolean(node.refable);
  }
  if (!options.compact) {
    return true;
  }
  return Boolean(node.refable || node.name || !isStructural(node));
}

function getDisplayName(node: SnapshotNode): string {
  // clickable 的 name 是子节点文本的聚合，子节点会单独展示，这里不重复
  if (node.role === 'clickable') {
    return '';
  }
  return node.name || node.cursor?.text || '';
}

function renderLine(
  node: SnapshotNode,
  indent: number,
  options: BrowserPageSnapshotParams,
): string {
  const prefix = '  '.repeat(indent);
  const refText = node.ref ? `@${node.ref} ` : '';
  const name = getDisplayName(node);
  // 截断超长文本（placeholder/帮助文本常超过 200 字符）
  const truncatedName = name.length > 80 ? `${name.slice(0, 80)}...` : name;
  const nameText = truncatedName ? ` "${truncatedName}"` : '';
  const hrefText =
    options.urls && node.href ? ` url=${JSON.stringify(node.href)}` : '';
  // 简化 cursor hints：只保留关键信息
  const cursorText = node.cursor
    ? ` ${node.cursor.kind}`
    : '';
  // 补充 bbox（仅对有 ref 的元素，帮助 agent 理解元素位置）
  const bboxText = node.ref && node.bbox
    ? ` bbox=[${node.bbox.x},${node.bbox.y},${node.bbox.w}x${node.bbox.h}]`
    : '';
  const overlayText = node.overlay ? ' overlay' : '';
  return `${prefix}${refText}[${node.role}]${nameText}${hrefText}${bboxText}${overlayText}${cursorText}`;
}

function collectRenderedNodes(
  nodes: Map<string, SnapshotNode>,
  node: SnapshotNode,
  indent: number,
  options: BrowserPageSnapshotParams,
  output: Set<string>,
): void {
  const renderSelf = shouldRender(node, options);
  if (
    renderSelf &&
    typeof options.depth === 'number' &&
    indent > options.depth
  ) {
    return;
  }

  const nextIndent = renderSelf ? indent + 1 : indent;
  if (renderSelf) {
    node.renderDepth = indent;
    output.add(node.ax.nodeId);
  }

  // 导航类容器：只渲染摘要行，不展开子节点（省大量字符）
  // 除非用了 selector 限定范围（此时用户明确要这个区域）
  if (renderSelf && isNavContainer(node) && node.children.length > 0) {
    // 统计子节点数
    const childCount = node.children.length;
    node.name = `[navigation: ${childCount} items]`;
    return; // 不递归子节点
  }

  node.children
    .map(id => nodes.get(id))
    .filter((child): child is SnapshotNode => Boolean(child))
    .forEach(child =>
      collectRenderedNodes(nodes, child, nextIndent, options, output),
    );
}

function renderTree(
  nodes: Map<string, SnapshotNode>,
  node: SnapshotNode,
  renderedNodeIds: Set<string>,
  options: BrowserPageSnapshotParams,
  output: string[],
): void {
  if (renderedNodeIds.has(node.ax.nodeId)) {
    output.push(renderLine(node, node.renderDepth ?? 0, options));
  }
  node.children
    .map(id => nodes.get(id))
    .filter((child): child is SnapshotNode => Boolean(child))
    .forEach(child =>
      renderTree(nodes, child, renderedNodeIds, options, output),
    );
}

function makeEmptySnapshot(options: BrowserPageSnapshotParams): string {
  return options.interactive ? EMPTY_INTERACTIVE_SNAPSHOT : EMPTY_SNAPSHOT;
}

function findAncestorRef(
  nodes: Map<string, SnapshotNode>,
  node: SnapshotNode,
): string | undefined {
  let current = node.parentId ? nodes.get(node.parentId) : undefined;
  while (current) {
    if (current.ref) {
      return current.ref;
    }
    current = current.parentId ? nodes.get(current.parentId) : undefined;
  }
  return undefined;
}

async function getViewport(client: CdpClient): Promise<BrowserPageViewport> {
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

async function getScopedBackendNodeIds(
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

async function getCursorElements(
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

async function getHref(
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

/**
 * 批量获取元素的可见性、bbox、是否浮层信息。
 * 一次 eval 拿到所有 backendNodeId 对应的元素状态，避免逐个 CDP 调用。
 */
async function getElementsVisibility(
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
      const inViewport = visible && rect.bottom > 0 && rect.right > 0
        && rect.top < window.innerHeight && rect.left < window.innerWidth;
      result[marker] = {
        visible,
        inViewport,
        bbox: visible ? { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) } : null,
        overlay: isFixed && visible,
      };
    }
    // 清理标记
    document.querySelectorAll('[data-ethan-vis]').forEach(el => el.removeAttribute('data-ethan-vis'));
    return result;
  })()`;

  const runtime = await client.send<
    RuntimeEvaluateResponse<Record<string, { visible: boolean; inViewport: boolean; bbox: { x: number; y: number; w: number; h: number } | null; overlay: boolean }>>
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

/** 判断节点是否属于导航类容器（需要摘要而不是展开）。 */
function isNavContainer(node: SnapshotNode): boolean {
  return node.role === 'navigation' || node.role === 'banner';
}

export async function takeAxSnapshot(
  client: CdpClient,
  params: BrowserPageSnapshotParams,
): Promise<AxSnapshotResult> {
  await client.send('DOM.enable');
  await client.send('Accessibility.enable');
  const [viewport, scopedBackendIds, cursorElements, tree] = await Promise.all([
    getViewport(client),
    getScopedBackendNodeIds(client, params.selector),
    params.cursor ? getCursorElements(client) : Promise.resolve(new Map()),
    client.send<CdpAxTreeResult>('Accessibility.getFullAXTree'),
  ]);

  const nodes = new Map<string, SnapshotNode>();
  const parentById = new Map<string, string>();
  tree.nodes.forEach(ax => {
    ax.childIds?.forEach(childId => parentById.set(childId, ax.nodeId));
  });

  tree.nodes.forEach(ax => {
    const cursor = ax.backendDOMNodeId
      ? cursorElements.get(ax.backendDOMNodeId)
      : undefined;
    const role = cursor?.role || getNodeRole(ax);
    const name = getNodeName(ax) || cursor?.name || '';
    nodes.set(ax.nodeId, {
      ax,
      role,
      name,
      value: getAxValue(ax.value),
      ignored: Boolean(ax.ignored),
      parentId: parentById.get(ax.nodeId),
      children: ax.childIds || [],
      depth: 0,
      cursor,
    });
  });

  const allowedNodeIds = new Set<string>();
  if (scopedBackendIds) {
    nodes.forEach(node => {
      if (
        typeof node.ax.backendDOMNodeId === 'number' &&
        scopedBackendIds.has(node.ax.backendDOMNodeId)
      ) {
        allowedNodeIds.add(node.ax.nodeId);
      }
    });
    nodes.forEach(node => {
      node.children = node.children.filter(childId =>
        allowedNodeIds.has(childId),
      );
      if (!allowedNodeIds.has(node.ax.nodeId)) {
        nodes.delete(node.ax.nodeId);
      }
    });
  }

  getRoots(nodes).forEach(root => {
    const walk = (node: SnapshotNode, depth: number): void => {
      node.depth = depth;
      node.children
        .map(id => nodes.get(id))
        .filter((child): child is SnapshotNode => Boolean(child))
        .forEach(child => walk(child, depth + 1));
    };
    walk(root, 0);
  });

  for (const node of nodes.values()) {
    const backendNodeId = node.ax.backendDOMNodeId;
    node.refable =
      Boolean(backendNodeId) &&
      (INTERACTIVE_ROLES.has(node.role) ||
        Boolean(node.cursor) ||
        (CONTENT_ROLES.has(node.role) && Boolean(node.name)));
  }

  // ── 可见性检测：批量获取所有有 backendNodeId 的元素的可见性+bbox+浮层状态 ──
  const allBackendNodeIds: number[] = [];
  nodes.forEach(node => {
    if (typeof node.ax.backendDOMNodeId === 'number') {
      allBackendNodeIds.push(node.ax.backendDOMNodeId);
    }
  });
  const visibilityMap = await getElementsVisibility(client, allBackendNodeIds);

  // 过滤不可见节点 + 补充 bbox/overlay 信息
  const invisibleNodeIds = new Set<string>();
  nodes.forEach(node => {
    const backendNodeId = node.ax.backendDOMNodeId;
    if (typeof backendNodeId !== 'number') return;
    const vis = visibilityMap.get(backendNodeId);
    if (!vis) return;
    node.visible = vis.visible;
    if (vis.bbox) node.bbox = vis.bbox;
    if (vis.overlay) node.overlay = true;
    // 不可见的 refable 节点标记为不可渲染（省 10-20% 节点）
    if (!vis.visible && node.refable) {
      invisibleNodeIds.add(node.ax.nodeId);
    }
  });
  // 把不可见节点从渲染集合中剔除（但不删 nodes Map，保持树结构完整）
  nodes.forEach(node => {
    if (invisibleNodeIds.has(node.ax.nodeId)) {
      node.refable = false;
    }
  });

  // ── 密码字段检测：遮蔽敏感输入框的 value，防止泄露给 LLM ──
  const passwordNodeIds = await detectPasswordFields(client, nodes);
  nodes.forEach(node => {
    if (passwordNodeIds.has(node.ax.nodeId)) {
      node.value = '***'; // 遮蔽 value
    }
  });

  // ── iframe 数量限制：只保留主 frame + 前 N 个 iframe，其余跳过 ──
  const MAX_IFRAMES = 3;
  const frameIdCounts = new Map<string, number>();
  nodes.forEach(node => {
    const fid = node.ax.frameId || '';
    frameIdCounts.set(fid, (frameIdCounts.get(fid) || 0) + 1);
  });
  const sortedFrameIds = Array.from(frameIdCounts.keys()).sort((a, b) =>
    (frameIdCounts.get(b) || 0) - (frameIdCounts.get(a) || 0),
  );
  const allowedFrameIds = new Set(sortedFrameIds.slice(0, MAX_IFRAMES));
  const skippedFrameCount = Math.max(0, sortedFrameIds.length - MAX_IFRAMES);
  const skippedIframeNodeIds = new Set<string>();
  if (sortedFrameIds.length > MAX_IFRAMES) {
    nodes.forEach(node => {
      const fid = node.ax.frameId || '';
      if (fid && !allowedFrameIds.has(fid)) {
        skippedIframeNodeIds.add(node.ax.nodeId);
      }
    });
  }

  const renderedNodeIds = new Set<string>();
  getRoots(nodes).forEach(root =>
    collectRenderedNodes(nodes, root, 0, params, renderedNodeIds),
  );

  // 被跳过的 iframe 节点不渲染
  skippedIframeNodeIds.forEach(id => renderedNodeIds.delete(id));

  const refs: BrowserPageRefEntry[] = [];
  const elements: BrowserPageSnapshotElement[] = [];
  const roleNameCounts = new Map<string, number>();
  let nextRef = 1;

  for (const node of nodes.values()) {
    if (!renderedNodeIds.has(node.ax.nodeId) || !node.refable) {
      continue;
    }
    const backendNodeId = node.ax.backendDOMNodeId;
    const key = `${node.role}\u0000${node.name}`;
    const nth = roleNameCounts.get(key) || 0;
    roleNameCounts.set(key, nth + 1);
    const ref = `e${nextRef}`;
    nextRef += 1;
    node.ref = ref;
    if (params.urls && node.role === 'link' && backendNodeId) {
      node.href = await getHref(client, backendNodeId);
    }
    refs.push({
      ref,
      role: node.role,
      ...(node.name ? { name: node.name } : {}),
      nth,
      ...(backendNodeId ? { backendNodeId } : {}),
      ...(node.ax.frameId ? { frameId: node.ax.frameId } : {}),
      ...(node.cursor?.text ? { text: node.cursor.text } : {}),
    });
    elements.push({
      ref,
      role: node.role,
      ...(node.name ? { name: node.name } : {}),
      ...(node.value ? { value: node.value } : {}),
      ...(node.href ? { href: node.href } : {}),
      depth: node.renderDepth ?? 0,
      ...(findAncestorRef(nodes, node)
        ? { parentRef: findAncestorRef(nodes, node) }
        : {}),
      ...(backendNodeId ? { backendNodeId } : {}),
      ...(node.ax.frameId ? { frameId: node.ax.frameId } : {}),
      ...(node.bbox ? { bbox: node.bbox } : {}),
      ...(node.overlay ? { overlay: true } : {}),
      actions: getActions(node.role),
    });
  }

  const output: string[] = [];
  // 浮层优先：先渲染浮层节点（overlay=true），再渲染正常树
  const overlayRoots = getRoots(nodes).filter(r => r.overlay);
  const normalRoots = getRoots(nodes).filter(r => !r.overlay);
  // 收集浮层子树中所有已渲染节点
  const overlayRendered = new Set<string>();
  overlayRoots.forEach(root => {
    collectRenderedNodes(nodes, root, 0, params, overlayRendered);
  });
  overlayRoots.forEach(root =>
    renderTree(nodes, root, overlayRendered, params, output),
  );
  // 渲染剩余正常节点
  const normalRendered = new Set(renderedNodeIds);
  // 从 normalRendered 中移除已在 overlay 中渲染的
  overlayRendered.forEach(id => normalRendered.delete(id));
  normalRoots.forEach(root =>
    renderTree(nodes, root, normalRendered, params, output),
  );

  const snapshotStr = output.join('\n') || makeEmptySnapshot(params);
  const finalSnapshot = skippedFrameCount > 0
    ? `${snapshotStr}\n(已跳过 ${skippedFrameCount} 个 iframe 的内容以控制体积)`
    : snapshotStr;

  return {
    snapshot: finalSnapshot,
    elements,
    refs,
    viewport,
  };
}
