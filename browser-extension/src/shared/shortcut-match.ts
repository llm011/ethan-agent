/**
 * 页面内快捷键的组合串解析与匹配——纯函数，可单测。
 *
 * 为什么要把这段从 `content/tab-palette.ts` 里抽出来单独测：快捷键「在很多页面上
 * 没反应」这件事**无法只靠读代码判断**，它的失效点是「某个按键恰好落进了某条 early
 * return」。把判据写成纯函数后，输入框/可编辑区/iframe/裸键 这些场景都能钉成用例，
 * 不用每次开浏览器手按。
 *
 * 组合串格式（与 popup 的录入器一致）：
 *   - `mod`  = 平台命令键：mac 上是 Cmd，其它平台是 Ctrl
 *   - `ctrl` / `meta` / `alt` / `shift` = 字面修饰键
 *   - 最后一段是主键（小写），如 `mod+shift+k`
 *   - 空串 = 停用
 */

export interface ParsedCombo {
  key: string;
  mod: boolean;
  ctrl: boolean;
  meta: boolean;
  alt: boolean;
  shift: boolean;
}

/** 平台判定：mac 上 mod 归 Cmd，其它平台归 Ctrl。 */
export function isMacPlatform(platform: string, userAgent = ''): boolean {
  return /mac|iphone|ipad/i.test(platform || userAgent || '');
}

/**
 * 解析组合串。返回 null 表示「这个串不构成一个可用的快捷键」——
 * 空串、只有修饰键、解析不出主键，都归到 null（= 停用）。
 */
export function parseCombo(combo?: string | null): ParsedCombo | null {
  if (!combo || typeof combo !== 'string') return null;
  const parts = combo
    .split('+')
    .map(p => p.trim().toLowerCase())
    .filter(Boolean);
  if (!parts.length) return null;

  const out: ParsedCombo = { key: '', mod: false, ctrl: false, meta: false, alt: false, shift: false };
  for (const p of parts) {
    if (p === 'mod') out.mod = true;
    else if (p === 'cmd' || p === 'meta' || p === 'command') out.meta = true;
    else if (p === 'ctrl' || p === 'control') out.ctrl = true;
    else if (p === 'shift') out.shift = true;
    else if (p === 'alt' || p === 'option') out.alt = true;
    else out.key = p;
  }
  if (!out.key) return null;
  // 只有修饰键的组合不算快捷键（否则会和「按住 Shift」冲突）
  if (!out.mod && !out.ctrl && !out.meta && !out.alt) return null;
  return out;
}

/** 事件里主键的规范化写法（空格写成 space，便于在组合串里表达）。 */
export function normalizeEventKey(key: string): string {
  const k = (key || '').toLowerCase();
  return k === ' ' ? 'space' : k;
}

/** 该组合里是否含「真修饰键」（mod/ctrl/meta/alt）——只有 shift 不算。 */
export function hasRealModifier(parsed: ParsedCombo | null): boolean {
  if (!parsed) return false;
  return parsed.mod || parsed.ctrl || parsed.meta || parsed.alt;
}

export interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

/** 某个真实按键事件是否命中这个组合。 */
export function comboMatches(parsed: ParsedCombo | null, e: KeyLike, isMac: boolean): boolean {
  if (!parsed) return false;
  if (normalizeEventKey(e.key) !== parsed.key) return false;
  if (!!e.shiftKey !== parsed.shift) return false;
  if (!!e.altKey !== parsed.alt) return false;
  const wantMeta = parsed.meta || (parsed.mod && isMac);
  const wantCtrl = parsed.ctrl || (parsed.mod && !isMac);
  if (!!e.metaKey !== wantMeta) return false;
  if (!!e.ctrlKey !== wantCtrl) return false;
  return true;
}

/**
 * 焦点在「会吞掉普通按键」的元素里时，是否应该放弃这次快捷键。
 *
 * 这是「快捷键在很多页面上没反应」的主因，判据要精细：
 *
 *   - **带真修饰键的组合（mod/ctrl/meta/alt + 主键）一律放行**。理由：按住
 *     Cmd/Ctrl/Alt 再按一个字母**不会往输入框里插入文字**，所以它既不会破坏用户
 *     正在打的字，也正是浏览器/编辑器里 Cmd+K、Ctrl+K 这类「命令」的通用形态。
 *     早期版本在这里无条件 return，等于「只要焦点在任意搜索框/评论框/聊天框里，
 *     快捷键就失效」——而现实里用户多数时候焦点就在某个输入框里。
 *   - **只有 Shift、或裸键的组合仍然放弃**。这些是真会和输入冲突的（Shift+字母
 *     会打出大写、裸键会直接输入字符），不能抢。
 *
 * `isEditable` 由调用方判定（含 contenteditable 与 shadow DOM 内的输入框）。
 */
export function shouldYieldToEditable(
  parsed: ParsedCombo | null,
  isEditable: boolean,
): boolean {
  if (!isEditable) return false;
  return !hasRealModifier(parsed);
}

/**
 * 事件目标是否落在「可编辑」区域。
 *
 * 注意 shadow DOM：`e.target` 会是**宿主元素**（比如 `<my-widget>`），它本身不是
 * input，但它内部可能有聚焦的输入框。`shadowRoot.activeElement` 能穿透一层，
 * 所以要沿这条链往下找，否则「组件库里的搜索框」会被误判成普通元素。
 *
 * 前两个参数之外的那条链（宿主自己的 shadowRoot → activeElement → shadowRoot …）
 * 由本函数自己走完，调用方只要把 `e.target` 和 `document.activeElement` 传进来即可。
 */
export function isEditableTarget(target: unknown, deepActiveElement?: unknown): boolean {
  if (isEditableElement(target)) return true;
  if (shadowChainHasEditable(target)) return true;
  if (isEditableElement(deepActiveElement)) return true;
  if (shadowChainHasEditable(deepActiveElement)) return true;
  return false;
}

/**
 * 沿 shadow DOM 的 `activeElement` 链往下找可编辑元素。
 *
 * 组件库常见的形态是 `<my-widget>` 宿主里套 `<my-input>` 再套真正的 `<input>`，
 * `shadowRoot.activeElement` 每次只穿透一层，所以要循环。
 *
 * **带步数上限**：这条链跟着页面里任意深度的 shadow 树走，而 `activeElement`
 * 是可以被页面脚本设成任意元素的。不设上限的话，一段构造出来的深层嵌套（甚至环）
 * 就能让 keydown 处理器转不完——每次按键都卡住页面。真实组件嵌套远少于 10 层。
 */
const MAX_SHADOW_DEPTH = 10;

function shadowChainHasEditable(start: unknown): boolean {
  let node: unknown = start;
  for (let i = 0; i < MAX_SHADOW_DEPTH; i++) {
    if (!node || typeof node !== 'object') return false;
    const shadow = (node as { shadowRoot?: { activeElement?: unknown } | null }).shadowRoot;
    const active = shadow ? shadow.activeElement : null;
    if (!active) return false;
    if (isEditableElement(active)) return true;
    node = active;
  }
  return false;
}

/** 单个节点是不是「会吞掉普通按键」的可编辑元素。 */
function isEditableElement(node: unknown): boolean {
  if (!node || typeof node !== 'object') return false;
  const el = node as {
    tagName?: string;
    isContentEditable?: boolean;
    getAttribute?: (n: string) => string | null;
  };
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  if (el.isContentEditable) return true;
  // 有些站点把输入伪装成 div；`role=textbox` 是可靠信号
  const role = el.getAttribute ? el.getAttribute('role') : null;
  if (role === 'textbox' || role === 'combobox' || role === 'searchbox') return true;
  return false;
}

/**
 * 供「经典脚本内联」场景使用的别名。
 *
 * content script 编译后与这些函数**同处一个 IIFE 作用域**，它自己又要保留同名包装
 * （`parseCombo` / `isEditableTarget`），直接内联会重名冲突。所以这里再导出带后缀的
 * 别名，让页面侧调别名、单测调原名，两边指向同一实现。
 */
export const parseComboSpec = parseCombo;
export const isEditableTargetIn = isEditableTarget;
