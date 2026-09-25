/**
 * 指令展示偏好的语义边界。
 *
 * 这里钉住的是三件容易走样的事：
 *   1. 脏数据不能让「展示数量」静默失效（回落到「不限」，而不是 0 条/NaN 条）；
 *   2. 「移出弹窗」不是删除——指令对象仍在 `all` 里，右键菜单/选中工具条照常能用；
 *   3. 先剔除移出的、再按 limit 截断（顺序反了会让用户觉得列表里凭空冒出指令）。
 */
import { describe, it, expect } from 'vitest';
import {
  DEFAULT_POPUP_COMMAND_LIMIT,
  POPUP_COMMAND_LIMIT_KEY,
  HIDDEN_COMMAND_IDS_KEY,
  resolveCommandPrefs,
  normalizeLimit,
  normalizeHiddenIds,
  selectPopupCommands,
  togglePopupVisibility,
  hideFromPopup,
  showInPopup,
  isHiddenFromPopup,
  pruneHiddenIds,
  moveItem,
  type CommandPrefs,
} from './command-prefs';

const cmd = (id: string) => ({ id });

describe('常量', () => {
  it('默认不限量（0）', () => {
    expect(DEFAULT_POPUP_COMMAND_LIMIT).toBe(0);
  });

  it('storage key 固定，改动需同步 popup/options', () => {
    expect(POPUP_COMMAND_LIMIT_KEY).toBe('popupCommandLimit');
    expect(HIDDEN_COMMAND_IDS_KEY).toBe('hiddenCommandIds');
  });
});

describe('normalizeLimit', () => {
  it('未存过 → 不限', () => {
    expect(normalizeLimit(undefined)).toBe(0);
  });

  it('非数字 → 不限（脏数据不该让列表变成空）', () => {
    expect(normalizeLimit('abc')).toBe(0);
    expect(normalizeLimit({})).toBe(0);
    expect(normalizeLimit(NaN)).toBe(0);
  });

  it('负数 → 不限', () => {
    expect(normalizeLimit(-3)).toBe(0);
  });

  it('数字字符串 → 解析成数字', () => {
    expect(normalizeLimit('5')).toBe(5);
  });

  it('小数 → 向下取整', () => {
    expect(normalizeLimit(3.9)).toBe(3);
  });

  it('正数原样保留', () => {
    expect(normalizeLimit(7)).toBe(7);
  });
});

describe('normalizeHiddenIds', () => {
  it('非数组 → 空', () => {
    expect(normalizeHiddenIds(undefined)).toEqual([]);
    expect(normalizeHiddenIds('summary')).toEqual([]);
    expect(normalizeHiddenIds(null)).toEqual([]);
  });

  it('过滤掉非字符串与空串项', () => {
    expect(normalizeHiddenIds(['a', 1, '', null, 'b', {}])).toEqual(['a', 'b']);
  });
});

describe('resolveCommandPrefs', () => {
  it('storage 为空 → 默认偏好', () => {
    expect(resolveCommandPrefs(undefined)).toEqual({ hiddenIds: [], limit: 0 });
  });

  it('读出真实存的值', () => {
    expect(
      resolveCommandPrefs({ [HIDDEN_COMMAND_IDS_KEY]: ['polish'], [POPUP_COMMAND_LIMIT_KEY]: 3 }),
    ).toEqual({ hiddenIds: ['polish'], limit: 3 });
  });

  it('脏值各自独立回落到默认', () => {
    expect(
      resolveCommandPrefs({ [HIDDEN_COMMAND_IDS_KEY]: 'nope', [POPUP_COMMAND_LIMIT_KEY]: -1 }),
    ).toEqual({ hiddenIds: [], limit: 0 });
  });
});

describe('selectPopupCommands', () => {
  const all = [cmd('summary'), cmd('translate'), cmd('polish'), cmd('vocab')];

  it('没移出、不限量 → 原样返回全部（且保持顺序）', () => {
    expect(selectPopupCommands(all, { hiddenIds: [], limit: 0 }).map(c => c.id))
      .toEqual(['summary', 'translate', 'polish', 'vocab']);
  });

  it('移出的指令不出现在结果里', () => {
    const r = selectPopupCommands(all, { hiddenIds: ['translate'], limit: 0 });
    expect(r.map(c => c.id)).toEqual(['summary', 'polish', 'vocab']);
  });

  it('移出不是删除：原数组仍有该指令（右键菜单/选中工具条还能用）', () => {
    selectPopupCommands(all, { hiddenIds: ['translate'], limit: 0 });
    expect(all.map(c => c.id)).toContain('translate');
  });

  it('先剔除移出的、再截断', () => {
    // 若顺序反了（先截断 2 条 = summary,translate，再剔除 translate）会只剩 summary
    const r = selectPopupCommands(all, { hiddenIds: ['summary'], limit: 2 });
    expect(r.map(c => c.id)).toEqual(['translate', 'polish']);
  });

  it('limit 大于总数 → 全部可见项', () => {
    expect(selectPopupCommands(all, { hiddenIds: [], limit: 99 })).toHaveLength(4);
  });

  it('limit 为 0 → 不限（不是「一条都不显示」）', () => {
    expect(selectPopupCommands(all, { hiddenIds: [], limit: 0 })).toHaveLength(4);
  });

  it('全部移出 → 空列表', () => {
    const r = selectPopupCommands(all, { hiddenIds: all.map(c => c.id), limit: 0 });
    expect(r).toEqual([]);
  });

  it('隐藏标记指向不存在的 id 时不影响结果', () => {
    const r = selectPopupCommands(all, { hiddenIds: ['ghost'], limit: 0 });
    expect(r).toHaveLength(4);
  });
});

describe('移出 / 加回', () => {
  const base: CommandPrefs = { hiddenIds: [], limit: 0 };

  it('移出后 isHidden 为真', () => {
    expect(isHiddenFromPopup('polish', hideFromPopup('polish', base))).toBe(true);
  });

  it('移出是幂等的', () => {
    const once = hideFromPopup('polish', base);
    const twice = hideFromPopup('polish', once);
    expect(twice.hiddenIds).toEqual(['polish']);
  });

  it('加回后 isHidden 为假', () => {
    expect(isHiddenFromPopup('polish', showInPopup('polish', hideFromPopup('polish', base)))).toBe(false);
  });

  it('加回不存在的 id 不报错', () => {
    expect(showInPopup('ghost', base).hiddenIds).toEqual([]);
  });

  it('toggle 一次移出、再 toggle 加回', () => {
    const hidden = togglePopupVisibility('vocab', base);
    expect(isHiddenFromPopup('vocab', hidden)).toBe(true);
    expect(isHiddenFromPopup('vocab', togglePopupVisibility('vocab', hidden))).toBe(false);
  });

  it('不改原对象（纯函数）', () => {
    const p = { hiddenIds: [], limit: 2 };
    hideFromPopup('polish', p);
    expect(p.hiddenIds).toEqual([]);
  });

  it('保留 limit 不被覆盖', () => {
    const p = { hiddenIds: [], limit: 5 };
    expect(hideFromPopup('polish', p).limit).toBe(5);
    expect(showInPopup('polish', p).limit).toBe(5);
  });
});

describe('pruneHiddenIds', () => {
  it('清掉已不存在的 id', () => {
    expect(pruneHiddenIds({ hiddenIds: ['a', 'gone', 'b'], limit: 0 }, ['a', 'b']).hiddenIds)
      .toEqual(['a', 'b']);
  });

  it('没有可清理项时原样返回同一个对象（避免无谓写 storage）', () => {
    const p = { hiddenIds: ['a'], limit: 0 };
    expect(pruneHiddenIds(p, ['a', 'b'])).toBe(p);
  });
});

describe('moveItem', () => {
  const list = ['a', 'b', 'c', 'd'];

  it('下移一位', () => {
    expect(moveItem(list, 1, 2)).toEqual(['a', 'c', 'b', 'd']);
  });

  it('上移一位', () => {
    expect(moveItem(list, 2, 1)).toEqual(['a', 'c', 'b', 'd']);
  });

  it('移到队首', () => {
    expect(moveItem(list, 3, 0)).toEqual(['d', 'a', 'b', 'c']);
  });

  it('移到队尾', () => {
    expect(moveItem(list, 0, 3)).toEqual(['b', 'c', 'd', 'a']);
  });

  it('原地不动 → 内容不变', () => {
    expect(moveItem(list, 2, 2)).toEqual(list);
  });

  it('越界 → 内容不变（调用方不必先判边界）', () => {
    expect(moveItem(list, -1, 2)).toEqual(list);
    expect(moveItem(list, 9, 2)).toEqual(list);
    expect(moveItem(list, 1, 9)).toEqual(list);
    expect(moveItem(list, 1, -1)).toEqual(list);
  });

  it('空数组不炸', () => {
    expect(moveItem([], 0, 1)).toEqual([]);
  });

  it('不改原数组（纯函数）', () => {
    moveItem(list, 0, 3);
    expect(list).toEqual(['a', 'b', 'c', 'd']);
  });
});

describe('normalizeHiddenIds 去重', () => {
  it('重复 id 只留一份', () => {
    // 管理界面的「已移出」区按这个数组逐行渲染：重复项会让同一条指令显示两行，
    // 点一次「加回」只消失一行，用户看着像没生效。
    expect(normalizeHiddenIds(['a', 'b', 'a'])).toEqual(['a', 'b']);
  });

  it('空串/非字符串被丢掉', () => {
    expect(normalizeHiddenIds(['a', '', 3, null, 'b'])).toEqual(['a', 'b']);
  });

  it('保持首次出现的次序', () => {
    expect(normalizeHiddenIds(['z', 'a', 'z'])).toEqual(['z', 'a']);
  });

  it('不是数组时返回空', () => {
    expect(normalizeHiddenIds('a')).toEqual([]);
    expect(normalizeHiddenIds(undefined)).toEqual([]);
  });
});
