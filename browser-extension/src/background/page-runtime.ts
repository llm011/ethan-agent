import type {
  BrowserPageGetWhat,
  BrowserPageScrollDirection,
} from '../shared';

const REF_MAP_KEY = '__COZE_BROWSER_REF_MAP__';

function literal(value: unknown): string {
  return JSON.stringify(value);
}

export function createViewportExpression(): string {
  return `(() => ({
    width: Math.round(window.innerWidth || document.documentElement.clientWidth || 0),
    height: Math.round(window.innerHeight || document.documentElement.clientHeight || 0),
    deviceScaleFactor: window.devicePixelRatio || 1
  }))()`;
}

export function createSnapshotExpression(interactive = false): string {
  return `(() => {
    const REF_MAP_KEY = ${literal(REF_MAP_KEY)};
    const interactiveOnly = ${literal(interactive)};
    const maxElements = 200;
    const maxTextLength = 160;
    const interactiveSelector = [
      'a',
      'button',
      'input',
      'textarea',
      'select',
      'summary',
      'label',
      '[role]',
      '[onclick]',
      '[tabindex]',
      '[contenteditable="true"]'
    ].join(',');
    const structuralSelector = [
      interactiveSelector,
      'h1',
      'h2',
      'h3',
      'p',
      'span'
    ].join(',');
    const elements = Array.from(document.querySelectorAll(
      interactiveOnly ? interactiveSelector : structuralSelector
    ));
    const refMap = {};
    const trim = value => String(value || '').replace(/\\s+/g, ' ').trim().slice(0, maxTextLength);
    const isVisible = element => {
      const style = window.getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) {
        return false;
      }
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.bottom >= 0 && rect.right >= 0 &&
        rect.top <= window.innerHeight && rect.left <= window.innerWidth;
    };
    const getRole = element => {
      const explicitRole = element.getAttribute('role');
      if (explicitRole) {
        return explicitRole;
      }
      const tagName = element.tagName.toLowerCase();
      if (tagName === 'a') return 'link';
      if (tagName === 'button') return 'button';
      if (tagName === 'select') return 'combobox';
      if (tagName === 'textarea') return 'textbox';
      if (tagName === 'input') {
        const type = String(element.getAttribute('type') || 'text').toLowerCase();
        if (type === 'checkbox') return 'checkbox';
        if (type === 'radio') return 'radio';
        if (type === 'submit' || type === 'button') return 'button';
        return 'textbox';
      }
      return tagName;
    };
    const getActions = element => {
      const tagName = element.tagName.toLowerCase();
      const role = getRole(element);
      const actions = new Set();
      if (
        tagName === 'a' ||
        tagName === 'button' ||
        tagName === 'label' ||
        tagName === 'summary' ||
        element.hasAttribute('onclick') ||
        ['button', 'link', 'checkbox', 'radio', 'menuitem', 'tab'].includes(role)
      ) {
        actions.add('click');
      }
      if (
        tagName === 'input' ||
        tagName === 'textarea' ||
        element.isContentEditable
      ) {
        actions.add('click');
        actions.add('fill');
        actions.add('type');
      }
      if (tagName === 'select') {
        actions.add('select');
      }
      if (typeof element.focus === 'function') {
        actions.add('focus');
      }
      return Array.from(actions);
    };
    const getName = element => trim(
      element.getAttribute('aria-label') ||
      element.getAttribute('alt') ||
      element.getAttribute('title') ||
      element.getAttribute('placeholder') ||
      element.innerText ||
      element.textContent ||
      element.value
    );
    const output = [];
    for (const element of elements) {
      if (output.length >= maxElements || !isVisible(element)) {
        continue;
      }
      const actions = getActions(element);
      if (interactiveOnly && actions.length === 0) {
        continue;
      }
      const rect = element.getBoundingClientRect();
      const ref = 'e' + (output.length + 1);
      refMap[ref] = element;
      output.push({
        ref,
        role: getRole(element),
        name: getName(element),
        text: trim(element.innerText || element.textContent),
        value: typeof element.value === 'string' ? trim(element.value) : undefined,
        tagName: element.tagName.toLowerCase(),
        box: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height)
        },
        center: {
          x: Math.round(rect.x + rect.width / 2),
          y: Math.round(rect.y + rect.height / 2)
        },
        actions
      });
    }
    window[REF_MAP_KEY] = refMap;
    return {
      elements: output,
      viewport: {
        width: Math.round(window.innerWidth || document.documentElement.clientWidth || 0),
        height: Math.round(window.innerHeight || document.documentElement.clientHeight || 0),
        deviceScaleFactor: window.devicePixelRatio || 1
      }
    };
  })()`;
}

export function createRefInfoExpression(ref: string): string {
  return `(() => {
    const element = window[${literal(REF_MAP_KEY)}]?.[${literal(ref)}];
    if (!element) {
      return { ok: false, error: 'REF_NOT_FOUND' };
    }
    const rect = element.getBoundingClientRect();
    return {
      ok: true,
      box: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height)
      },
      center: {
        x: Math.round(rect.x + rect.width / 2),
        y: Math.round(rect.y + rect.height / 2)
      }
    };
  })()`;
}

export function createDomActionExpression(
  action: 'fill' | 'type' | 'select' | 'scrollIntoView',
  ref: string,
  value?: string,
): string {
  return `(() => {
    const element = window[${literal(REF_MAP_KEY)}]?.[${literal(ref)}];
    if (!element) {
      return { ok: false, error: 'REF_NOT_FOUND' };
    }
    const dispatch = type => element.dispatchEvent(new Event(type, { bubbles: true }));
    if (${literal(action)} === 'scrollIntoView') {
      element.scrollIntoView({ block: 'center', inline: 'center', behavior: 'auto' });
      return { ok: true };
    }
    if (${literal(action)} === 'select') {
      element.value = ${literal(value || '')};
      dispatch('input');
      dispatch('change');
      return { ok: true };
    }
    if (typeof element.focus === 'function') {
      element.focus();
    }
    if (element.isContentEditable) {
      if (${literal(action)} === 'fill') {
        element.textContent = ${literal(value || '')};
      } else {
        element.textContent = String(element.textContent || '') + ${literal(value || '')};
      }
      dispatch('input');
      return { ok: true };
    }
    if ('value' in element) {
      if (${literal(action)} === 'fill') {
        element.value = ${literal(value || '')};
      } else {
        element.value = String(element.value || '') + ${literal(value || '')};
      }
      dispatch('input');
      dispatch('change');
      return { ok: true };
    }
    return { ok: false, error: 'UNSUPPORTED_ELEMENT' };
  })()`;
}

export function createScrollExpression(
  direction: BrowserPageScrollDirection,
  pixels: number,
): string {
  const delta = direction === 'up' ? -pixels : pixels;
  return `(() => {
    window.scrollBy({ top: ${literal(delta)}, left: 0, behavior: 'auto' });
    return { ok: true };
  })()`;
}

export function createGetExpression(
  what: BrowserPageGetWhat,
  ref?: string,
): string {
  if (what === 'title') {
    return '(() => ({ ok: true, value: document.title }))()';
  }
  if (what === 'url') {
    return '(() => ({ ok: true, value: location.href }))()';
  }

  return `(() => {
    const element = window[${literal(REF_MAP_KEY)}]?.[${literal(ref)}];
    if (!element) {
      return { ok: false, error: 'REF_NOT_FOUND' };
    }
    if (${literal(what)} === 'box') {
      const rect = element.getBoundingClientRect();
      return {
        ok: true,
        box: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height)
        }
      };
    }
    if (${literal(what)} === 'html') {
      return { ok: true, value: element.outerHTML };
    }
    if (${literal(what)} === 'value') {
      return { ok: true, value: 'value' in element ? element.value : null };
    }
    return { ok: true, value: element.innerText || element.textContent || '' };
  })()`;
}

export function createReadyStateExpression(load: string): string {
  if (load === 'domcontentloaded') {
    return "(() => ['interactive', 'complete'].includes(document.readyState))()";
  }

  return "(() => document.readyState === 'complete')()";
}
