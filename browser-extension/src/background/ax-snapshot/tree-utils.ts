import type { BrowserPageSnapshotParams } from '../../shared';
import type { DomNode, SnapshotNode } from './types';
import { SKIP_ROLES, STRUCTURAL_ROLES } from './constants';

export function getActions(role: string): string[] {
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

export function collectBackendNodeIds(
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

export function getRoots(nodes: Map<string, SnapshotNode>): SnapshotNode[] {
  return Array.from(nodes.values()).filter(
    node => !node.parentId || !nodes.has(node.parentId),
  );
}

export function isStructural(node: SnapshotNode): boolean {
  return STRUCTURAL_ROLES.has(node.role);
}

export function shouldRender(
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
  if (node.role === 'StaticText' && !node.name?.trim()) {
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

export function getDisplayName(node: SnapshotNode): string {
  // clickable 的 name 是子节点文本的聚合，子节点会单独展示，这里不重复
  if (node.role === 'clickable') {
    return '';
  }
  return node.name || node.cursor?.text || '';
}

/** 判断节点是否属于导航类容器（需要摘要而不是展开）。 */
export function isNavContainer(node: SnapshotNode): boolean {
  return node.role === 'navigation' || node.role === 'banner';
}

export function findAncestorRef(
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
