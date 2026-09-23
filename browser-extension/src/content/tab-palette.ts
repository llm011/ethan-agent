/* eslint-disable */
// Tab 搜索命令面板（注入到页面里的浮层）。
//
// 设计要点：**完全不依赖 ethan**。tab 列表和关键词匹配都在扩展侧完成
// （chrome.tabs + tabGroups），所以只要装了扩展，无论 ethan 是否在跑、
// 网络是否通、代理是否拦了 localhost，这个面板都能用。
//
// 通信：面板不直接调 chrome.tabs（它是页面上下文，调用要走 background）。
// 面板只负责 UI 和按键，数据通过 chrome.runtime.sendMessage 发给 background。

interface PaletteMatch {
  tab: {
    tabId: number;
    windowId: number;
    url?: string;
    title?: string;
    active?: boolean;
    favIconUrl?: string;
  };
  groupTitle?: string;
}

interface PaletteResults {
  matches: PaletteMatch[];
  scanned: number;
  total: number;
  error?: string;
}

interface PaletteState {
  open: boolean;
  query: string;
  matches: PaletteMatch[];
  activeIndex: number;
  scanned: number;
  total: number;
  loading: boolean;
  error: string;
  /** 请求序号：避免快速输入时旧响应盖掉新结果 */
  seq: number;
  lastFocused: HTMLElement | null;
}

type ElProps = Record<string, unknown>;

(function () {
  'use strict';

  const win = window as unknown as { __ethanTabPaletteInstalled?: boolean };
  if (win.__ethanTabPaletteInstalled) return;
  win.__ethanTabPaletteInstalled = true;

  const ROOT_ID = '__ethan_tab_palette';
  const Z_INDEX = '2147483647';

  const state: PaletteState = {
    open: false,
    query: '',
    matches: [],
    activeIndex: 0,
    scanned: 0,
    total: 0,
    loading: false,
    error: '',
    seq: 0,
    lastFocused: null,
  };

  let root: HTMLElement | null = null;
  let inputEl: HTMLInputElement | null = null;
  let listEl: HTMLElement | null = null;
  let metaEl: HTMLElement | null = null;
  let styleEl: HTMLStyleElement | null = null;

  function el(tag: string, props?: ElProps, children?: (Node | null)[]): HTMLElement {
    const node = document.createElement(tag);
    if (props) {
      for (const k of Object.keys(props)) {
        const v = props[k];
        if (k === 'style' && v && typeof v === 'object') {
          Object.assign(node.style, v as Record<string, string>);
        } else if (k === 'text') {
          node.textContent = String(v);
        } else if (k.indexOf('on') === 0 && typeof v === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
        } else if (v != null) {
          node.setAttribute(k, String(v));
        }
      }
    }
    (children || []).forEach(c => {
      if (c) node.appendChild(c);
    });
    return node;
  }

  function injectStyles() {
    if (styleEl) return;
    styleEl = document.createElement('style');
    styleEl.textContent = [
      '#' + ROOT_ID + ' * { box-sizing: border-box; }',
      '#' + ROOT_ID + ' { position: fixed; inset: 0; z-index: ' + Z_INDEX + ';',
      '  display: flex; align-items: flex-start; justify-content: center;',
      '  padding-top: 12vh; background: rgba(15,18,25,0.45);',
      '  backdrop-filter: blur(2px);',
      '  font-family: -apple-system, system-ui, "PingFang SC", sans-serif; }',
      '#' + ROOT_ID + ' .panel { width: 620px; max-width: calc(100vw - 32px);',
      '  background: #fff; border-radius: 12px; overflow: hidden;',
      '  box-shadow: 0 20px 60px rgba(0,0,0,0.35); display: flex; flex-direction: column;',
      '  max-height: 70vh; color: #1f2430; }',
      '@media (prefers-color-scheme: dark) {',
      '  #' + ROOT_ID + ' .panel { background: #1f2430; color: #e6e8ec; }',
      '  #' + ROOT_ID + ' .row.sel { background: #2f3646 !important; }',
      '  #' + ROOT_ID + ' .q { color: #e6e8ec !important; }',
      '  #' + ROOT_ID + ' .meta, #' + ROOT_ID + ' .url, #' + ROOT_ID + ' .empty { color: #8b909a !important; }',
      '  #' + ROOT_ID + ' .sep { border-top-color: #2a2e37 !important; }',
      '}',
      '#' + ROOT_ID + ' .q { width: 100%; border: 0; outline: 0; padding: 16px 18px;',
      '  font-size: 16px; background: transparent; color: #1f2430; }',
      '#' + ROOT_ID + ' .sep { border-top: 1px solid #eceef2; }',
      '#' + ROOT_ID + ' .list { overflow-y: auto; max-height: 46vh; }',
      '#' + ROOT_ID + ' .row { display: flex; align-items: center; gap: 10px;',
      '  padding: 9px 16px; cursor: pointer; }',
      '#' + ROOT_ID + ' .row.sel { background: #eef0ff; }',
      '#' + ROOT_ID + ' .fav { width: 18px; height: 18px; flex: none; border-radius: 4px; }',
      '#' + ROOT_ID + ' .body { min-width: 0; flex: 1; }',
      '#' + ROOT_ID + ' .t { font-size: 14px; white-space: nowrap;',
      '  overflow: hidden; text-overflow: ellipsis; }',
      '#' + ROOT_ID + ' .url { font-size: 11px; color: #9aa0aa; white-space: nowrap;',
      '  overflow: hidden; text-overflow: ellipsis; margin-top: 1px; }',
      '#' + ROOT_ID + ' .tag { font-size: 10px; padding: 1px 6px; border-radius: 999px;',
      '  background: rgba(127,127,127,0.16); flex: none; white-space: nowrap; }',
      '#' + ROOT_ID + ' .hd { font-size: 10px; font-weight: 600; padding: 6px 16px 2px;',
      '  color: #9aa0aa; letter-spacing: 0.04em; }',
      '#' + ROOT_ID + ' .meta { padding: 8px 16px; font-size: 11px; color: #9aa0aa;',
      '  display: flex; justify-content: space-between; gap: 12px; }',
      '#' + ROOT_ID + ' .empty { padding: 22px 16px; text-align: center;',
      '  font-size: 13px; color: #9aa0aa; }',
      '#' + ROOT_ID + ' kbd { font-family: inherit; font-size: 10px; padding: 1px 4px;',
      '  border-radius: 4px; background: rgba(127,127,127,0.18); }',
    ].join('\n');
    (document.head || document.documentElement).appendChild(styleEl);
  }

  function hostOf(url?: string): string {
    if (!url) return '';
    try {
      return new URL(url).host;
    } catch (_) {
      return url || '';
    }
  }

  /** 把 "Cmd+Shift+K" 之类的串解析成匹配函数。空串 → null（禁用）。 */
  function parseCombo(combo?: string): ((e: KeyboardEvent) => boolean) | null {
    if (!combo || typeof combo !== 'string') return null;
    var parts = combo
      .split('+')
      .map(function (p) {
        return p.trim().toLowerCase();
      })
      .filter(Boolean);
    if (!parts.length) return null;
    const need = { mod: false, shift: false, alt: false, ctrl: false, meta: false };
    let key = '';
    for (let i = 0; i < parts.length; i++) {
      const p = parts[i]!;
      if (p === 'mod') need.mod = true;
      else if (p === 'cmd' || p === 'meta' || p === 'command') need.meta = true;
      else if (p === 'ctrl' || p === 'control') need.ctrl = true;
      else if (p === 'shift') need.shift = true;
      else if (p === 'alt' || p === 'option') need.alt = true;
      else key = p;
    }
    if (!key) return null;
    return function (e: KeyboardEvent) {
      if (e.key.toLowerCase() !== key) return false;
      if (!!e.shiftKey !== need.shift) return false;
      if (!!e.altKey !== need.alt) return false;
      // mod = 当前平台的命令键（mac 上是 Cmd，其它是 Ctrl）
      const wantMeta = need.meta || (need.mod && isMac());
      const wantCtrl = need.ctrl || (need.mod && !isMac());
      if (!!e.metaKey !== wantMeta) return false;
      if (!!e.ctrlKey !== wantCtrl) return false;
      return true;
    };
  }

  function isMac(): boolean {
    return /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent || '');
  }

  function render() {
    if (!listEl) return;
    listEl.textContent = '';

    if (state.loading && !state.matches.length) {
      listEl.appendChild(el('div', { class: 'empty', text: '搜索中…' }));
      return;
    }
    if (state.error) {
      listEl.appendChild(el('div', { class: 'empty', text: state.error }));
      return;
    }
    if (!state.matches.length) {
      listEl.appendChild(
        el('div', {
          class: 'empty',
          text: state.query ? '没有匹配的标签页' : '没有可显示的标签页',
        }),
      );
      return;
    }

    // 按窗口分组显示（多窗口时一眼能分清）
    let lastWindow: number | undefined;
    state.matches.forEach((m, idx) => {
      const tab = m.tab;
      if (tab.windowId !== lastWindow) {
        lastWindow = tab.windowId;
        listEl!.appendChild(el('div', { class: 'hd', text: '窗口 ' + tab.windowId }));
      }
      const fav = el('img', { class: 'fav', alt: '' }) as HTMLImageElement;
      // chrome://favicon 在 MV3 里走 _favicon 权限；tab.favIconUrl 更省事
      if (tab.favIconUrl) {
        fav.src = tab.favIconUrl;
        fav.addEventListener('error', function () {
          fav.style.visibility = 'hidden';
        });
      } else {
        fav.style.visibility = 'hidden';
      }

      const row = el(
        'div',
        {
          class: 'row' + (idx === state.activeIndex ? ' sel' : ''),
          onmouseenter: () => {
            if (state.activeIndex === idx) return;
            state.activeIndex = idx;
            render();
          },
          onclick: () => {
            activate(idx);
          },
        },
        [
          fav,
          el('div', { class: 'body' }, [
            el('div', { class: 't', text: tab.title || '(无标题)' }),
            el('div', { class: 'url', text: hostOf(tab.url) }),
          ]),
          m.groupTitle ? el('span', { class: 'tag', text: m.groupTitle }) : null,
          tab.active ? el('span', { class: 'tag', text: '当前' }) : null,
        ],
      );
      listEl!.appendChild(row);
    });
  }

  function updateMeta() {
    if (!metaEl) return;
    metaEl.textContent = '';
    const left = el('span', {
      text: state.loading
        ? '搜索中…'
        : state.total
          ? '匹配 ' + state.total + ' / ' + state.scanned + ' 个标签页'
          : '共 ' + state.scanned + ' 个标签页',
    });
    const right = el('span', {}, [
      el('kbd', { text: '↑↓' }),
      document.createTextNode(' 选择  '),
      el('kbd', { text: 'Enter' }),
      document.createTextNode(' 跳转  '),
      el('kbd', { text: 'Esc' }),
      document.createTextNode(' 关闭'),
    ]);
    metaEl.appendChild(left);
    metaEl.appendChild(right);
  }

  function setResults(res: PaletteResults | undefined) {
    state.matches = (res && res.matches) || [];
    state.scanned = (res && res.scanned) || 0;
    state.total = (res && res.total) || 0;
    if (state.matches.length) state.error = '';
    state.activeIndex = 0;
    state.loading = false;
    render();
    updateMeta();
  }

  function search() {
    state.loading = true;
    state.error = '';
    const mySeq = ++state.seq;
    render();
    updateMeta();
    try {
      chrome.runtime.sendMessage(
        { target: 'tabPalette', type: 'search', query: state.query },
        (res: PaletteResults | undefined) => {
          // 忽略过期响应（用户已经继续打字）
          if (mySeq !== state.seq) return;
          if (chrome.runtime.lastError) {
            state.loading = false;
            state.error = '扩展通信失败：' + chrome.runtime.lastError.message;
            render();
            updateMeta();
            return;
          }
          setResults(res);
        },
      );
    } catch {
      state.loading = false;
      state.error = '扩展上下文已失效，请刷新页面';
      render();
      updateMeta();
    }
  }

  function activate(idx: number) {
    const m = state.matches[idx];
    if (!m || !m.tab) return;
    close();
    try {
      chrome.runtime.sendMessage({
        target: 'tabPalette',
        type: 'activate',
        tabId: m.tab.tabId,
        windowId: m.tab.windowId,
      });
    } catch (_) {
      /* 忽略 */
    }
  }

  function move(delta: number) {
    if (!state.matches.length) return;
    let next = state.activeIndex + delta;
    if (next < 0) next = state.matches.length - 1;
    if (next >= state.matches.length) next = 0;
    state.activeIndex = next;
    render();
    // 保证选中项可见
    const rows = listEl!.querySelectorAll('.row');
    const row = rows[state.activeIndex] as HTMLElement | undefined;
    if (row && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
  }

  function onKeydown(e: KeyboardEvent) {
    if (!state.open) return;

    // 面板自己处理导航键，别让页面也收到
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      close();
      return;
    }
    if (e.key === 'ArrowDown' || (e.key === 'n' && e.ctrlKey)) {
      e.preventDefault();
      e.stopPropagation();
      move(1);
      return;
    }
    if (e.key === 'ArrowUp' || (e.key === 'p' && e.ctrlKey)) {
      e.preventDefault();
      e.stopPropagation();
      move(-1);
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      e.stopPropagation();
      activate(state.activeIndex);
      return;
    }
    // 输入期间的按键不要穿透给页面的快捷键
    e.stopPropagation();
  }

  function open() {
    if (state.open) return;
    injectStyles();

    state.lastFocused = document.activeElement as HTMLElement | null;

    const input = el('input', {
      class: 'q',
      type: 'text',
      placeholder: '搜索标签页标题或网址…',
      autocomplete: 'off',
      spellcheck: 'false',
    }) as HTMLInputElement;
    inputEl = input;
    input.addEventListener('input', () => {
      state.query = input.value;
      search();
    });
    input.addEventListener('keydown', onKeydown);

    const list = el('div', { class: 'list' });
    const meta = el('div', { class: 'meta' });
    listEl = list;
    metaEl = meta;

    const container = el(
      'div',
      { id: ROOT_ID },
      [
        el('div', { class: 'panel' }, [
          input,
          el('div', { class: 'sep' }),
          list,
          meta,
        ]),
      ],
    );
    root = container;
    // 点遮罩关闭
    container.addEventListener('mousedown', (e: Event) => {
      if (e.target === container) close();
    });

    (document.body || document.documentElement).appendChild(container);
    state.open = true;

    // 捕获阶段拦住按键，避免页面自己的快捷键（比如 GitHub 的 / 搜索）抢走
    document.addEventListener('keydown', onKeydown, true);

    input.focus();
    search();
  }

  function close() {
    if (!state.open) return;
    document.removeEventListener('keydown', onKeydown, true);

    if (root && root.parentNode) root.parentNode.removeChild(root);
    root = null;
    inputEl = null;
    listEl = null;
    metaEl = null;

    state.open = false;
    state.query = '';
    state.matches = [];
    state.activeIndex = 0;
    state.error = '';
    state.seq++; // 让在途响应失效

    if (state.lastFocused && state.lastFocused.focus) {
      try {
        state.lastFocused.focus();
      } catch (_) {
        /* 忽略 */
      }
    }
    state.lastFocused = null;
  }

  function toggle() {
    if (state.open) close();
    else open();
  }

  // ---- 快捷键（页面内那一层，可在 popup 里改）----
  let comboMatcher: ((e: KeyboardEvent) => boolean) | null = null;

  function applyShortcut(combo?: string) {
    comboMatcher = parseCombo(combo);
  }

  document.addEventListener(
    'keydown',
    (e: KeyboardEvent) => {
      if (state.open) return; // 开着的时候由面板自己处理
      if (e.repeat) return;
      if (!comboMatcher) return;
      // 别抢输入框里的按键（用户正在页面里打字）
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || ''))) {
        return;
      }
      if (!comboMatcher(e)) return;
      e.preventDefault();
      e.stopPropagation();
      open();
    },
    true,
  );

  chrome.runtime.onMessage.addListener(
    (msg: { target?: string; type?: string; combo?: string }, _sender, sendResponse) => {
      if (!msg || msg.target !== 'tabPalette') return undefined;
      if (msg.type === 'toggle') {
        toggle();
        sendResponse({ ok: true });
        return undefined;
      }
      if (msg.type === 'setShortcut') {
        applyShortcut(msg.combo);
        sendResponse({ ok: true });
        return undefined;
      }
      if (msg.type === 'ping') {
        sendResponse({ ok: true });
        return undefined;
      }
      return undefined;
    },
  );

  // 启动时同步一次快捷键配置
  try {
    chrome.storage.local.get(['tabPaletteShortcut'], (stored: { tabPaletteShortcut?: string }) => {
      if (chrome.runtime.lastError) return;
      applyShortcut(stored && stored.tabPaletteShortcut);
    });
  } catch {
    /* 忽略 */
  }

  // 监听设置变化，popup 改完立即生效，不必刷新页面
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local' || !changes['tabPaletteShortcut']) return;
      applyShortcut(changes['tabPaletteShortcut'].newValue as string | undefined);
    });
  } catch {
    /* 忽略 */
  }
})();
