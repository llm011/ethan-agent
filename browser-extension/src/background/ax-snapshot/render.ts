import type { BrowserPageSnapshotParams } from '../../shared';
import type { SnapshotNode } from './types';
import { EMPTY_INTERACTIVE_SNAPSHOT, EMPTY_SNAPSHOT } from './constants';
import { getDisplayName, isNavContainer, shouldRender } from './tree-utils';

export function renderLine(
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

export function collectRenderedNodes(
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
    // 统计子节点数，覆写 name 为摘要（nav 容器子节点对 AI 无逐个阅读价值）
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

export function renderTree(
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

export function makeEmptySnapshot(options: BrowserPageSnapshotParams): string {
  return options.interactive ? EMPTY_INTERACTIVE_SNAPSHOT : EMPTY_SNAPSHOT;
}
