/**
 * 页面内快捷键的判据。
 *
 * 这些用例直接对应「快捷键在很多页面上没反应」的实测现象——真实 Chromium 里跑
 * 出来的失效集合就是「焦点在 input/textarea/select/contenteditable 里」。
 * 所以 `shouldYieldToEditable` 是这套断言的核心：只有 shift/裸键才该让路。
 */
import { describe, it, expect } from 'vitest';
import {
  parseCombo,
  comboMatches,
  hasRealModifier,
  isMacPlatform,
  normalizeEventKey,
  shouldYieldToEditable,
  isEditableTarget,
} from './shortcut-match';

const ev = (o: Partial<{ key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }>) => ({
  key: 'k', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...o,
});

describe('isMacPlatform', () => {
  it('mac 判为真', () => {
    expect(isMacPlatform('MacIntel')).toBe(true);
  });

  it('windows/linux 判为假', () => {
    expect(isMacPlatform('Win32')).toBe(false);
    expect(isMacPlatform('Linux x86_64')).toBe(false);
  });

  it('platform 为空时退回 userAgent', () => {
    expect(isMacPlatform('', 'Mozilla/5.0 (Macintosh)')).toBe(true);
  });
});

describe('parseCombo', () => {
  it('默认值解析出 mod+shift+k', () => {
    expect(parseCombo('mod+shift+k')).toEqual({
      key: 'k', mod: true, ctrl: false, meta: false, alt: false, shift: true,
    });
  });

  it('空串/空值 → null（停用语义）', () => {
    expect(parseCombo('')).toBeNull();
    expect(parseCombo(undefined)).toBeNull();
    expect(parseCombo(null)).toBeNull();
  });

  it('只有修饰键 → null（不算完整快捷键）', () => {
    expect(parseCombo('mod+shift')).toBeNull();
    expect(parseCombo('ctrl')).toBeNull();
  });

  it('裸键 → null（不能抢普通按键）', () => {
    expect(parseCombo('k')).toBeNull();
  });

  it('cmd/meta/command 都归到 meta', () => {
    expect(parseCombo('cmd+k')?.meta).toBe(true);
    expect(parseCombo('meta+k')?.meta).toBe(true);
    expect(parseCombo('command+k')?.meta).toBe(true);
  });

  it('option 归到 alt', () => {
    expect(parseCombo('option+k')?.alt).toBe(true);
  });

  it('大小写不敏感', () => {
    expect(parseCombo('MOD+SHIFT+K')).toEqual(parseCombo('mod+shift+k'));
  });

  it('空格写成 space', () => {
    expect(parseCombo('mod+space')?.key).toBe('space');
  });
});

describe('hasRealModifier', () => {
  it('mod/shift 组合算有真修饰键', () => {
    expect(hasRealModifier(parseCombo('mod+shift+k'))).toBe(true);
  });

  it('只有 shift 不算', () => {
    expect(hasRealModifier(parseCombo('shift+k'))).toBe(false);
  });

  it('null → false', () => {
    expect(hasRealModifier(null)).toBe(false);
  });
});

describe('comboMatches —— mac 上 mod 归 Cmd', () => {
  const p = parseCombo('mod+shift+k');

  it('mac 上 Cmd+Shift+K 命中', () => {
    expect(comboMatches(p, ev({ key: 'K', metaKey: true, shiftKey: true }), true)).toBe(true);
  });

  it('mac 上 Ctrl+Shift+K 不命中（Ctrl 不是 mod）', () => {
    expect(comboMatches(p, ev({ key: 'K', ctrlKey: true, shiftKey: true }), true)).toBe(false);
  });

  it('mac 上同时按 Cmd+Ctrl 不命中（多了个键）', () => {
    expect(comboMatches(p, ev({ key: 'K', metaKey: true, ctrlKey: true, shiftKey: true }), true)).toBe(false);
  });

  it('少了 Shift 不命中', () => {
    expect(comboMatches(p, ev({ key: 'K', metaKey: true }), true)).toBe(false);
  });

  it('主键不对不命中', () => {
    expect(comboMatches(p, ev({ key: 'J', metaKey: true, shiftKey: true }), true)).toBe(false);
  });
});

describe('comboMatches —— 非 mac 上 mod 归 Ctrl', () => {
  const p = parseCombo('mod+shift+k');

  it('Ctrl+Shift+K 命中', () => {
    expect(comboMatches(p, ev({ key: 'K', ctrlKey: true, shiftKey: true }), false)).toBe(true);
  });

  it('Cmd+Shift+K 不命中', () => {
    expect(comboMatches(p, ev({ key: 'K', metaKey: true, shiftKey: true }), false)).toBe(false);
  });
});

describe('comboMatches —— 显式 ctrl/meta 与平台无关', () => {
  it('显式 ctrl+k 在 mac 上也要 Ctrl', () => {
    const p = parseCombo('ctrl+k');
    expect(comboMatches(p, ev({ key: 'k', ctrlKey: true }), true)).toBe(true);
    expect(comboMatches(p, ev({ key: 'k', metaKey: true }), true)).toBe(false);
  });

  it('显式 alt 组合', () => {
    const p = parseCombo('alt+k');
    expect(comboMatches(p, ev({ key: 'k', altKey: true }), true)).toBe(true);
  });

  it('null 组合永不命中', () => {
    expect(comboMatches(null, ev({ key: 'k', metaKey: true }), true)).toBe(false);
  });
});

describe('normalizeEventKey', () => {
  it('空格归一为 space', () => {
    expect(normalizeEventKey(' ')).toBe('space');
  });

  it('大写转小写', () => {
    expect(normalizeEventKey('K')).toBe('k');
  });
});

describe('shouldYieldToEditable —— 「输入框里快捷键失效」的修复点', () => {
  it('焦点在输入框 + 带真修饰键 → 不让路（这是修复的核心）', () => {
    expect(shouldYieldToEditable(parseCombo('mod+shift+k'), true)).toBe(false);
    expect(shouldYieldToEditable(parseCombo('ctrl+k'), true)).toBe(false);
    expect(shouldYieldToEditable(parseCombo('alt+k'), true)).toBe(false);
  });

  it('焦点不在可编辑区 → 一律不让路', () => {
    expect(shouldYieldToEditable(parseCombo('mod+shift+k'), false)).toBe(false);
  });

  it('只有 shift 的组合在输入框里让路（Shift+字母会打大写）', () => {
    expect(shouldYieldToEditable(parseCombo('shift+k'), true)).toBe(true);
  });

  it('停用的快捷键让路', () => {
    expect(shouldYieldToEditable(null, true)).toBe(true);
  });
});

describe('isEditableTarget', () => {
  it('input/textarea/select 判为可编辑', () => {
    expect(isEditableTarget({ tagName: 'INPUT' })).toBe(true);
    expect(isEditableTarget({ tagName: 'TEXTAREA' })).toBe(true);
    expect(isEditableTarget({ tagName: 'SELECT' })).toBe(true);
  });

  it('大小写不影响', () => {
    expect(isEditableTarget({ tagName: 'input' })).toBe(true);
  });

  it('contenteditable 判为可编辑', () => {
    expect(isEditableTarget({ tagName: 'DIV', isContentEditable: true })).toBe(true);
  });

  it('role=textbox 的伪装输入判为可编辑', () => {
    expect(isEditableTarget({ tagName: 'DIV', getAttribute: (n: string) => (n === 'role' ? 'textbox' : null) })).toBe(true);
  });

  it('普通 div/p/body 判为不可编辑', () => {
    expect(isEditableTarget({ tagName: 'DIV', isContentEditable: false, getAttribute: () => null })).toBe(false);
    expect(isEditableTarget({ tagName: 'BODY' })).toBe(false);
  });

  it('shadow DOM 宿主元素自身不是输入框，但内部聚焦的元素是 → 判为可编辑', () => {
    expect(isEditableTarget({ tagName: 'MY-WIDGET' }, { tagName: 'INPUT' })).toBe(true);
  });

  it('null/非对象安全', () => {
    expect(isEditableTarget(null)).toBe(false);
    expect(isEditableTarget(undefined)).toBe(false);
    expect(isEditableTarget('str')).toBe(false);
  });
});
