/**
 * Tab 搜索命令面板的快捷键常量 —— 三处共用（popup / background / content script）。
 *
 * 单独放一个小文件而不是塞进 shared/index.ts：content script 编译成**经典脚本**
 * （vite.config.ts 里用 ts.transpileModule，module=None），不能 import；
 * 它靠构建时内联这个字面量。放这里至少让「谁在用同一个默认值」一眼可见，
 * 避免 popup 有兜底、content script 没有而导致两边不一致
 * （表现是 popup 显示 ⌘⇧K 但快捷键不生效）。
 */
export const TAB_PALETTE_SHORTCUT_KEY = 'tabPaletteShortcut';

/** 平台无关写法：mod = mac 的 Cmd / 其它平台的 Ctrl。 */
export const DEFAULT_TAB_PALETTE_SHORTCUT = 'mod+shift+k';

/**
 * 从 storage 读到的对象里解析出最终生效的组合串。
 *
 * 语义边界（三处必须一致）：
 *   - **没存过 / 脏数据** → 默认值（否则快捷键静默失效）
 *   - **显式空串** → 空串，代表用户主动停用页面内那一层，**不回落到默认**
 *     （否则用户没法关掉它）
 */
export function resolveShortcut(stored: unknown): string {
  if (!stored || typeof stored !== 'object') return DEFAULT_TAB_PALETTE_SHORTCUT;
  const value = (stored as Record<string, unknown>)[TAB_PALETTE_SHORTCUT_KEY];
  if (typeof value === 'string') return value;
  return DEFAULT_TAB_PALETTE_SHORTCUT;
}
