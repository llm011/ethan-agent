import type { CdpClient } from '../cdp-client';
import type { RuntimeEvaluateResponse, SnapshotNode } from './types';
import { literal } from './utils';

/**
 * 检查元素是否为密码字段，需要遮蔽 value。
 * 通过 backendNodeId 查询 DOM 节点的 tagName 和 type 属性。
 * 缓存结果避免重复 CDP 调用。
 */
export async function detectPasswordFields(
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
      // 只遮蔽真正的密码类型字段；autocomplete='off' + type='text' 不再误遮（搜索框/用户名框常见此组合）
      const isSensitive = tag === 'input' && ['new-password', 'current-password'].includes(type);
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
