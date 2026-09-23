/**
 * 快捷键默认值。
 *
 * 曾经真实出过的坑：content script 编译成经典脚本、不能 import 常量，靠构建时
 * 内联默认值；它读 storage 时漏了兜底 → 全新安装（storage 无此 key）时
 * `applyShortcut(undefined)` → 匹配器为 null → 页面内快捷键**静默失效**，
 * 而 popup 那边有兜底、显示的是 ⌘⇧K。用户表现是「设置里明明写着，按了没反应」。
 *
 * 这里钉住「默认值本身」以及「兜底逻辑」的形状；三处（popup / background /
 * content script）共用同一个值是靠 `tab-palette-config.ts` 收敛的。
 * content script 因经典脚本限制无法被 import，那条路径由
 * `content/tab-palette.ts` 里的内联默认值保证，改动时需人工对齐本文件。
 */
import { describe, it, expect } from 'vitest';
import {
  TAB_PALETTE_SHORTCUT_KEY,
  DEFAULT_TAB_PALETTE_SHORTCUT,
  resolveShortcut,
} from './tab-palette-config';

describe('tab-palette 快捷键常量', () => {
  it('默认值是 mod+shift+k（平台无关写法：mac=⌘ / 其它=Ctrl）', () => {
    expect(DEFAULT_TAB_PALETTE_SHORTCUT).toBe('mod+shift+k');
  });

  it('storage key 与 popup/background/content 三处一致', () => {
    expect(TAB_PALETTE_SHORTCUT_KEY).toBe('tabPaletteShortcut');
  });
});

describe('resolveShortcut（storage 读取的兜底）', () => {
  it('storage 为空（全新安装）→ 用默认值，而不是 undefined', () => {
    expect(resolveShortcut(undefined)).toBe(DEFAULT_TAB_PALETTE_SHORTCUT);
  });

  it('storage 里是空对象 → 用默认值', () => {
    expect(resolveShortcut({})).toBe(DEFAULT_TAB_PALETTE_SHORTCUT);
  });

  it('非字符串值 → 用默认值（脏数据不该让快捷键失效）', () => {
    expect(resolveShortcut({ tabPaletteShortcut: 123 })).toBe(DEFAULT_TAB_PALETTE_SHORTCUT);
  });

  it('用户显式存的组合 → 原样返回', () => {
    expect(resolveShortcut({ tabPaletteShortcut: 'mod+shift+j' })).toBe('mod+shift+j');
  });

  it('用户显式存空串 → 返回空串（= 停用页面内快捷键，不是回落默认）', () => {
    // 空串是用户「清空」的语义，必须与「没存过」区分开：
    // 若这里也回落到默认，用户将无法停用这一层。
    expect(resolveShortcut({ tabPaletteShortcut: '' })).toBe('');
  });
});
