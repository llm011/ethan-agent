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
const MAX_NAME_LENGTH = 160;
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

function shouldRender(
  node: SnapshotNode,
  options: BrowserPageSnapshotParams,
): boolean {
  if (node.ignored) {
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
  const nameText = name ? ` "${name}"` : '';
  const hrefText =
    options.urls && node.href ? ` url=${JSON.stringify(node.href)}` : '';
  const cursorText = node.cursor
    ? ` ${node.cursor.kind} [${node.cursor.hints.join(', ')}]`
    : '';
  return `${prefix}${refText}[${node.role}]${nameText}${hrefText}${cursorText}`;
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

  const renderedNodeIds = new Set<string>();
  getRoots(nodes).forEach(root =>
    collectRenderedNodes(nodes, root, 0, params, renderedNodeIds),
  );

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
      actions: getActions(node.role),
    });
  }

  const output: string[] = [];
  getRoots(nodes).forEach(root =>
    renderTree(nodes, root, renderedNodeIds, params, output),
  );

  return {
    snapshot: output.join('\n') || makeEmptySnapshot(params),
    elements,
    refs,
    viewport,
  };
}
