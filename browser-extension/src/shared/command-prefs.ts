/**
 * 页面指令在 popup 里的「展示偏好」——顺序、展示数量、以及被移出弹窗的指令。
 *
 * 单独成模块（并保持纯函数）的原因：这套语义要被 popup（渲染）、options（管理）
 * 和 background（右键菜单）三处共用，且必须能单测。谁是纯函数、谁碰 storage，
 * 分界线清楚才不会三处各写一份而渐渐走样。
 *
 * 三个概念分得很开，别混：
 *   - **顺序**：直接就是 `commands` 数组本身的次序，不额外存一份。少一份状态就
 *     少一处能不一致的地方（否则「顺序表」和「指令表」会各自漂移）。
 *   - **移出弹窗**（`hiddenCommandIds`）：指令还在 `commands` 里、还在右键菜单/
 *     选中工具条里能用，只是**不在 popup 列表里出现**。这不是删除——用户能在管理
 *     界面把它加回来。所以它存的是 id 集合，不是「换个地方放」。
 *   - **展示数量**（`popupCommandLimit`）：0 表示不限。被移出的指令先剔除，再截断，
 *     顺序是「先移除、后限量」——反过来的话用户会觉得「我把某个移走了，结果列表里
 *     又冒出来一个新指令」。
 */

export const POPUP_COMMAND_LIMIT_KEY = 'popupCommandLimit';
export const HIDDEN_COMMAND_IDS_KEY = 'hiddenCommandIds';

/** 默认不限量：与其猜一个数字，不如默认把用户排好的都显示出来。 */
export const DEFAULT_POPUP_COMMAND_LIMIT = 0;

export interface CommandPrefs {
  /** 移出 popup 的指令 id（指令本身仍存在，只是不在弹窗里展示）。 */
  hiddenIds: string[];
  /** popup 里最多展示几条；0 = 不限。 */
  limit: number;
}

export const DEFAULT_COMMAND_PREFS: CommandPrefs = {
  hiddenIds: [],
  limit: DEFAULT_POPUP_COMMAND_LIMIT,
};

/** 把 storage 里的原始值解析成合法的展示数量（脏数据一律回落到「不限」）。 */
export function normalizeLimit(raw: unknown): number {
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n) || n < 0) return DEFAULT_POPUP_COMMAND_LIMIT;
  return Math.floor(n);
}

/** 把 storage 里的原始值解析成 id 列表（过滤掉非字符串项）。 */
export function normalizeHiddenIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((id): id is string => typeof id === 'string' && id.length > 0);
}

/** 从 storage 读到的对象里解析出完整偏好。 */
export function resolveCommandPrefs(stored: unknown): CommandPrefs {
  if (!stored || typeof stored !== 'object') return { ...DEFAULT_COMMAND_PREFS };
  const obj = stored as Record<string, unknown>;
  return {
    hiddenIds: normalizeHiddenIds(obj[HIDDEN_COMMAND_IDS_KEY]),
    limit: normalizeLimit(obj[POPUP_COMMAND_LIMIT_KEY]),
  };
}

/**
 * 按偏好算出 popup 该展示哪些指令。
 *
 * `all` 的次序就是用户排好的次序——这里只做「剔除移出的」+「按 limit 截断」，
 * 不重排，排序的职责在管理界面。
 */
export function selectPopupCommands<T extends { id: string }>(
  all: T[],
  prefs: CommandPrefs,
): T[] {
  const hidden = new Set(prefs.hiddenIds);
  const visible = all.filter(c => !hidden.has(c.id));
  const limit = normalizeLimit(prefs.limit);
  return limit > 0 ? visible.slice(0, limit) : visible;
}

/** 某条指令是否被移出了弹窗。 */
export function isHiddenFromPopup(id: string, prefs: CommandPrefs): boolean {
  return prefs.hiddenIds.includes(id);
}

/** 把一条指令移出弹窗（幂等）。 */
export function hideFromPopup(id: string, prefs: CommandPrefs): CommandPrefs {
  if (prefs.hiddenIds.includes(id)) return { ...prefs, hiddenIds: [...prefs.hiddenIds] };
  return { ...prefs, hiddenIds: [...prefs.hiddenIds, id] };
}

/** 把一条指令重新加回弹窗（幂等）。 */
export function showInPopup(id: string, prefs: CommandPrefs): CommandPrefs {
  return { ...prefs, hiddenIds: prefs.hiddenIds.filter(x => x !== id) };
}

/**
 * 反转隐藏状态（管理界面里的「移出/加回」同一个按钮）。
 * 注意：`hiddenIds` 是有序数组，但语义是集合——加回时顺序无所谓，因为真正的
 * 展示顺序由 `commands` 决定。
 */
export function togglePopupVisibility(id: string, prefs: CommandPrefs): CommandPrefs {
  return isHiddenFromPopup(id, prefs) ? showInPopup(id, prefs) : hideFromPopup(id, prefs);
}

/**
 * 指令被删除时同步清掉它的隐藏标记（避免 id 集合无限残留）。
 * 内置指令永远不该被删，但用户自定义的会被删——这个函数就是给那条路径用的。
 */
export function pruneHiddenIds(prefs: CommandPrefs, existingIds: string[]): CommandPrefs {
  const alive = new Set(existingIds);
  const kept = prefs.hiddenIds.filter(id => alive.has(id));
  return kept.length === prefs.hiddenIds.length ? prefs : { ...prefs, hiddenIds: kept };
}

/**
 * 把一个元素从 `from` 位置移动到 `to` 位置，返回新数组（不改原数组）。
 *
 * 越界或原地不动时返回原数组的浅拷贝，调用方不必先做边界判断。
 * 之所以放在这里而不是各 UI 里自己 splice：上移/下移/拖拽三种交互最后都要落到
 * 同一次「搬动」上，写三遍容易在边界（第一位上移、最后一位下移）上出现分歧。
 */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
  const next = [...items];
  if (from === to) return next;
  if (from < 0 || from >= next.length) return next;
  if (to < 0 || to >= next.length) return next;
  const [moved] = next.splice(from, 1);
  if (moved === undefined) return next;
  next.splice(to, 0, moved);
  return next;
}
