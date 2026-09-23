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
  /** 'open' = 当前还开着；'closed' = 历史（今天已关闭）。 */
  source?: 'open' | 'closed';
  /** 仅 closed：关闭时间（毫秒）。 */
  closedAt?: number;
}

interface PaletteResults {
  matches: PaletteMatch[];
  scanned: number;
  total: number;
  error?: string;
  /** 开关开着但取历史失败时的原因（例如权限缺失），面板据此提示而不是假装没有。 */
  closedError?: string;
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
  /** 是否把「今天已关闭的 tab」也算进来。默认关，每次打开面板都重置。 */
  includeClosed: boolean;
  /** 开关开着却取不到历史时的原因，直接显示给用户 */
  closedError: string;
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
    includeClosed: false,
    closedError: '',
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
      '#' + ROOT_ID + ' .head { display: flex; align-items: center; gap: 8px;',
      '  padding: 0 16px 10px; }',
      '#' + ROOT_ID + ' .tgl { display: inline-flex; align-items: center; gap: 6px;',
      '  font-size: 11px; color: #6b7280; cursor: pointer; padding: 3px 9px;',
      '  border-radius: 999px; border: 1px solid #e2e5ea; user-select: none; flex: none; }',
      '#' + ROOT_ID + ' .tgl:hover { border-color: #c9ced6; }',
      '#' + ROOT_ID + ' .tgl .sw { width: 24px; height: 13px; border-radius: 999px;',
      '  background: #d3d7de; position: relative; transition: background .12s; flex: none; }',
      '#' + ROOT_ID + ' .tgl .sw::after { content: ""; position: absolute; top: 1.5px; left: 1.5px;',
      '  width: 10px; height: 10px; border-radius: 50%; background: #fff;',
      '  transition: transform .12s; }',
      '#' + ROOT_ID + ' .tgl.on { color: #4f46e5; border-color: #c7c9f7; background: #f5f5ff; }',
      '#' + ROOT_ID + ' .tgl.on .sw { background: #6366f1; }',
      '#' + ROOT_ID + ' .tgl.on .sw::after { transform: translateX(11px); }',
      '#' + ROOT_ID + ' .row .src { font-size: 10px; padding: 1px 6px; border-radius: 999px;',
      '  flex: none; white-space: nowrap; background: rgba(217,119,6,0.14); color: #b45309; }',
      '#' + ROOT_ID + ' .row.closed .t, #' + ROOT_ID + ' .row.closed .url { opacity: 0.72; }',
      '@media (prefers-color-scheme: dark) {',
      '  #' + ROOT_ID + ' .tgl { color: #9aa0aa; border-color: #343a46; }',
      '  #' + ROOT_ID + ' .tgl.on { color: #a5b4fc; border-color: #4c4f86; background: #262a3f; }',
      '  #' + ROOT_ID + ' .row .src { background: rgba(251,191,36,0.16); color: #fbbf24; }',
      '}',
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

  /** 历史条目右侧的标记：能算出时间就显示 HH:MM，否则只写「已关闭」。 */
  function closedLabel(m: PaletteMatch): string {
    if (!m.closedAt) return '已关闭';
    const d = new Date(m.closedAt);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return '已关闭 ' + hh + ':' + mm;
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
      // 开关开着但历史取不到：说清原因，别让用户以为「今天确实没关过 tab」
      if (state.includeClosed && state.closedError) {
        listEl.appendChild(
          el('div', { class: 'empty', text: '历史读取失败：' + state.closedError }),
        );
      }
      return;
    }

    // 按窗口分组显示（多窗口时一眼能分清）。
    // 历史条目没有窗口归属，单独归到「已关闭」一段——它排在最后，
    // 所以「窗口 N」标题只会出现在前面连续的开着的那批里。
    let lastWindow: number | undefined;
    let closedHeaderDone = false;
    state.matches.forEach((m, idx) => {
      const tab = m.tab;
      const closed = m.source === 'closed';
      if (closed) {
        if (!closedHeaderDone) {
          closedHeaderDone = true;
          listEl!.appendChild(
            el('div', { class: 'hd', text: '今天已关闭' }),
          );
        }
      } else if (tab.windowId !== lastWindow) {
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
          class:
            'row' +
            (idx === state.activeIndex ? ' sel' : '') +
            (closed ? ' closed' : ''),
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
          closed ? el('span', { class: 'src', text: closedLabel(m) }) : null,
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
          ? '匹配 ' + state.total + ' / ' + state.scanned + ' 个' +
            (state.includeClosed ? '标签页与历史' : '标签页')
          : '共 ' + state.scanned + ' 个' +
            (state.includeClosed ? '标签页与历史' : '标签页'),
    });
    // 历史取不到时，即便有开着的命中也要让用户知道开关那半边是坏的
    if (state.includeClosed && state.closedError) {
      left.textContent = '历史读取失败：' + state.closedError;
    }
    const right = el('span', {}, []);
    if (state.includeClosed) {
      right.appendChild(el('kbd', { text: 'Alt+H' }));
      right.appendChild(document.createTextNode(' 隐藏已关闭  '));
    } else {
      right.appendChild(el('kbd', { text: 'Alt+H' }));
      right.appendChild(document.createTextNode(' 搜历史  '));
    }
    right.appendChild(el('kbd', { text: '↑↓' }));
    right.appendChild(document.createTextNode(' 选择  '));
    right.appendChild(el('kbd', { text: 'Enter' }));
    right.appendChild(document.createTextNode(' 跳转  '));
    right.appendChild(el('kbd', { text: 'Esc' }));
    right.appendChild(document.createTextNode(' 关闭'));
    metaEl.appendChild(left);
    metaEl.appendChild(right);
  }

  function setResults(res: PaletteResults | undefined) {
    state.matches = (res && res.matches) || [];
    state.scanned = (res && res.scanned) || 0;
    state.total = (res && res.total) || 0;
    state.closedError = (res && res.closedError) || '';
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
        {
          target: 'tabPalette',
          type: 'search',
          query: state.query,
          includeClosed: state.includeClosed,
        },
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
    // Alt+H：不用离开键盘去点开关。跟 Enter/↑↓ 一样在输入框里也能按。
    if (e.altKey && (e.key === 'h' || e.key === 'H')) {
      e.preventDefault();
      e.stopPropagation();
      toggleClosed();
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

    // 历史开关：默认关（只搜还开着的 tab），点了才把「今天已关闭的」并进来。
    // 用 tabindex=-1 而不是 button：输入框要一直保持焦点，否则用户打不了字；
    // 鼠标点它一下仍然会触发 click，键盘上则用 Alt+H 切换。
    const toggle = el(
      'div',
      {
        class: 'tgl' + (state.includeClosed ? ' on' : ''),
        role: 'button',
        tabindex: '-1',
        title: '把今天已关闭的标签页也一起搜（Alt+H）',
        onclick: () => {
          toggleClosed();
        },
      },
      [
        el('span', { class: 'sw' }),
        el('span', { text: '含已关闭' }),
      ],
    );

    const container = el(
      'div',
      { id: ROOT_ID },
      [
        el('div', { class: 'panel' }, [
          input,
          el('div', { class: 'head' }, [toggle]),
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

  /** 切换「含已关闭」。开关状态不持久化：每次开面板都从默认关开始。 */
  function toggleClosed() {
    state.includeClosed = !state.includeClosed;
    // 开关要立刻反映在视觉上，不等 search 回来
    if (root) root.querySelectorAll('.tgl').forEach(n => n.classList.toggle('on', state.includeClosed));
    search();
    if (inputEl) inputEl.focus();
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
    // 下次打开回到默认「只搜还开着的 tab」——用户按快捷键时多半是想找开着的
    state.includeClosed = false;
    state.closedError = '';
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
  //
  // 必须兜底默认值：全新安装时 storage 里还没有这个 key，直接用 undefined 会让
  // parseCombo 返回 null，页面内快捷键就完全不生效——而 popup 那边有兜底、显示的是
  // 默认键，用户看到的是「设置里明明写着 ⌘⇧K，按了却没反应」。
  //
  // 经典脚本不能 import，所以这里内联一份与 shared/tab-palette-config.ts 的
  // resolveShortcut 相同的语义（没存过→默认；显式空串→停用）。改一边要改另一边，
  // shared/tab-palette-config.spec.ts 里有断言钉住默认值本身。
  const DEFAULT_SHORTCUT = 'mod+shift+k';
  function resolve(combo: unknown): string {
    return typeof combo === 'string' ? combo : DEFAULT_SHORTCUT;
  }
  try {
    chrome.storage.local.get(['tabPaletteShortcut'], (stored: { tabPaletteShortcut?: unknown }) => {
      if (chrome.runtime.lastError) {
        applyShortcut(DEFAULT_SHORTCUT);
        return;
      }
      applyShortcut(resolve(stored && stored.tabPaletteShortcut));
    });
  } catch {
    applyShortcut(DEFAULT_SHORTCUT);
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
