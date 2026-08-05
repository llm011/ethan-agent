/* eslint-disable max-lines-per-function, complexity -- AX tree snapshot orchestration is easier to audit in one function */
import type {
  BrowserPageSnapshotElement,
  BrowserPageSnapshotParams,
} from '../../shared';
import type { CdpClient } from '../cdp-client';
import type { BrowserPageRefEntry } from '../ref-store';
import type {
  AxSnapshotResult,
  CdpAxTreeResult,
  SnapshotNode,
} from './types';
import { CONTENT_ROLES, INTERACTIVE_ROLES } from './constants';
import {
  getHref,
  getScopedBackendNodeIds,
  getViewport,
} from './cdp-queries';
import {
  getCursorElements,
  getElementsVisibility,
} from './element-queries';
import { detectPasswordFields } from './password-detect';
import {
  collectRenderedNodes,
  makeEmptySnapshot,
  renderTree,
} from './render';
import { findAncestorRef, getActions, getRoots } from './tree-utils';
import { getAxValue, getNodeName, getNodeRole } from './utils';

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
