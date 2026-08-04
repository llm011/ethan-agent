import type { BrowserPageMouseButton, BrowserSessionTab } from '../../shared';
import {
  KEY_MODIFIER_ALT,
  KEY_MODIFIER_CTRL,
  KEY_MODIFIER_META,
  KEY_MODIFIER_SHIFT,
} from './constants';

export function getPageInfo(
  tab: BrowserSessionTab,
): { url?: string; title?: string } {
  return {
    url: tab.url,
    title: tab.title,
  };
}

export function getMouseButton(
  button: BrowserPageMouseButton | undefined,
): 'left' | 'middle' | 'right' {
  return button || 'left';
}

export function getKeyDefinition(key: string): {
  key: string;
  code: string;
  windowsVirtualKeyCode: number;
  text?: string;
  modifiers: number;
} {
  const parts = key
    .split('+')
    .map(part => part.trim())
    .filter(Boolean);
  const baseKey = parts.pop() || key;
  let modifiers = 0;
  parts.forEach(part => {
    const normalized = part.toLowerCase();
    if (normalized === 'alt' || normalized === 'option') {
      modifiers |= KEY_MODIFIER_ALT;
    } else if (normalized === 'control' || normalized === 'ctrl') {
      modifiers |= KEY_MODIFIER_CTRL;
    } else if (
      normalized === 'meta' ||
      normalized === 'command' ||
      normalized === 'cmd'
    ) {
      modifiers |= KEY_MODIFIER_META;
    } else if (normalized === 'shift') {
      modifiers |= KEY_MODIFIER_SHIFT;
    }
  });

  const specialKeys: Record<string, { code: string; keyCode: number }> = {
    Enter: { code: 'Enter', keyCode: 13 },
    Tab: { code: 'Tab', keyCode: 9 },
    Escape: { code: 'Escape', keyCode: 27 },
    Backspace: { code: 'Backspace', keyCode: 8 },
    Delete: { code: 'Delete', keyCode: 46 },
    ArrowUp: { code: 'ArrowUp', keyCode: 38 },
    ArrowDown: { code: 'ArrowDown', keyCode: 40 },
    ArrowLeft: { code: 'ArrowLeft', keyCode: 37 },
    ArrowRight: { code: 'ArrowRight', keyCode: 39 },
  };
  const special = specialKeys[baseKey];
  if (special) {
    return {
      key: baseKey,
      code: special.code,
      windowsVirtualKeyCode: special.keyCode,
      modifiers,
    };
  }

  const text = baseKey.length === 1 && modifiers === 0 ? baseKey : undefined;
  return {
    key: baseKey,
    code: baseKey.length === 1 ? `Key${baseKey.toUpperCase()}` : baseKey,
    windowsVirtualKeyCode:
      baseKey.length === 1 ? baseKey.toUpperCase().charCodeAt(0) : 0,
    text,
    modifiers,
  };
}
