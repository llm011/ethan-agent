/* eslint-disable */
// 选中浮动工具条（经典脚本，声明式 content_scripts 常驻所有页面）。
//
// 选中文字 → 选区附近弹小工具条：翻译 / 解释 / 存知识库 / 提问。
// 「提问」展开一个输入框（补充 query 可空）→ 发送。所有动作走 background 的
// run-command（结果流式进右上角结果面板），或 reading:saveKnowledge（存库）。
//
// 为什么声明式常驻而非按需注入：工具条要「选中即现」，选中前没有触发点可注入。

(function () {
  const w = window as any;
  if (w.__ethanSelectionBarAdded) return;
  w.__ethanSelectionBarAdded = true;

  const BAR_ID = '__ethan_selection_bar';
  const DISABLED_KEY = '__ethan_selection_bar_disabled';
  const Z = 2147483644;
  let lastSelection = '';
  let disabled = localStorage.getItem(DISABLED_KEY) === '1';

  function isDark(): boolean {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function removeBar() {
    document.getElementById(BAR_ID)?.remove();
  }

  // 忽略在自家 UI（工具条 / 结果面板 / 阅读面板）内的选中，避免自弹
  function inOwnUi(node: Node | null): boolean {
    let el = node instanceof Element ? node : node?.parentElement || null;
    while (el) {
      const id = el.id || '';
      if (id === BAR_ID || id.startsWith('__ethan_')) return true;
      el = el.parentElement;
    }
    return false;
  }

  function currentSelectionText(): string {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return '';
    if (inOwnUi(sel.anchorNode)) return '';
    return (sel.toString() || '').trim();
  }

  function btnStyle(dark: boolean, primary = false): string {
    if (primary) {
      return 'border:none;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer;background:#0d9488;color:#fff;white-space:nowrap';
    }
    return 'border:none;border-radius:6px;padding:5px 8px;font-size:12px;cursor:pointer;background:none;color:' +
      (dark ? '#e6e8ec' : '#1f2430') + ';white-space:nowrap';
  }

  function showBar() {
    if (disabled) return;
    const text = currentSelectionText();
    if (!text) { removeBar(); return; }
    lastSelection = text;

    const sel = window.getSelection();
    const range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
    if (!range) return;
    const rect = range.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) return;

    removeBar();
    const dark = isDark();
    const bar = document.createElement('div');
    bar.id = BAR_ID;
    bar.style.cssText = [
      'position:fixed', 'z-index:' + Z,
      'display:flex', 'align-items:center', 'gap:2px', 'padding:4px',
      'background:' + (dark ? 'rgba(28,31,38,0.98)' : 'rgba(255,255,255,0.98)'),
      'border:1px solid ' + (dark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.12)'),
      'border-radius:9px', 'box-shadow:0 4px 18px rgba(0,0,0,0.22)',
      'backdrop-filter:blur(6px)',
      'font-family:-apple-system,system-ui,"PingFang SC",sans-serif',
    ].join(';');

    const mkBtn = (label: string, onClick: () => void, primary = false) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = btnStyle(dark, primary);
      // 用 mousedown + preventDefault，避免点击按钮时清掉页面选区
      b.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
      b.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); onClick(); });
      return b;
    };

    bar.appendChild(mkBtn('🌐 翻译', () => runCmd('translate-sel')));
    bar.appendChild(mkBtn('💡 解释', () => runCmd('explain')));
    bar.appendChild(mkBtn('📌 存', () => saveKnowledge()));
    bar.appendChild(mkBtn('⋯ 更多', () => showMoreMenu(bar, dark)));
    bar.appendChild(mkBtn('❓ 提问', () => showAskInput(bar, dark), true));

    // 关闭按钮：永久隐藏工具条
    const close = document.createElement('button');
    close.textContent = '✕';
    close.title = '关闭（不再显示选中工具条）';
    close.style.cssText = 'border:none;border-radius:50%;width:20px;height:20px;font-size:11px;line-height:20px;text-align:center;cursor:pointer;margin-left:2px;background:none;color:' + (dark ? '#888' : '#999');
    close.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
    close.addEventListener('click', (e) => {
      e.preventDefault(); e.stopPropagation();
      disabled = true;
      localStorage.setItem(DISABLED_KEY, '1');
      removeBar();
    });
    bar.appendChild(close);

    document.documentElement.appendChild(bar);

    // 定位：选区上方居中，空间不够则移到下方
    const bw = bar.offsetWidth || 220;
    const bh = bar.offsetHeight || 34;
    let left = rect.left + rect.width / 2 - bw / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - bw - 8));
    let top = rect.top - bh - 8;
    if (top < 8) top = rect.bottom + 8;
    bar.style.left = left + 'px';
    bar.style.top = top + 'px';
  }

  // 「提问」：把工具条内容换成输入框 + 发送
  function showAskInput(bar: HTMLElement, dark: boolean) {
    bar.innerHTML = '';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '补充问题（可空）后回车';
    input.style.cssText = [
      'border:1px solid ' + (dark ? '#3a3f4a' : '#e5e7eb'), 'border-radius:6px',
      'padding:5px 8px', 'font-size:12px', 'width:180px', 'outline:none',
      'background:' + (dark ? '#2a2e37' : '#fff'), 'color:' + (dark ? '#e6e8ec' : '#1f2430'),
    ].join(';');
    input.addEventListener('mousedown', (e) => e.stopPropagation());
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); runCmd('ask-selection', input.value.trim()); }
    });

    const send = document.createElement('button');
    send.textContent = '发送';
    send.style.cssText = btnStyle(dark, true);
    send.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
    send.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); runCmd('ask-selection', input.value.trim()); });

    bar.appendChild(input);
    bar.appendChild(send);
    input.focus();
  }

  // 「更多」：写作类 + 生词卡片，换成一排次级按钮
  function showMoreMenu(bar: HTMLElement, dark: boolean) {
    bar.innerHTML = '';
    const items: [string, string][] = [
      ['✨ 润色', 'polish'],
      ['🔄 改写', 'rewrite'],
      ['➕ 扩写', 'expand'],
      ['📖 生词', 'vocab'],
    ];
    for (const [label, id] of items) {
      const b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = btnStyle(dark);
      b.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
      b.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); runCmd(id); });
      bar.appendChild(b);
    }
  }

  function runCmd(commandId: string, query?: string) {
    const text = lastSelection;
    removeBar();
    if (!text) return;
    chrome.runtime.sendMessage({ type: 'run-command', commandId, selectionText: text, query });
  }

  function saveKnowledge() {
    const text = lastSelection;
    removeBar();
    if (!text) return;
    const title = (text.slice(0, 30) || document.title || '摘录') + ' · ' + (document.title || '');
    chrome.runtime.sendMessage({ type: 'reading:saveKnowledge', title, content: text });
  }

  // 选中变化 → 稍延迟后决定是否显示（避免拖选过程中频繁重建）
  let showTimer: number | null = null;
  function scheduleShow() {
    if (showTimer) clearTimeout(showTimer);
    showTimer = window.setTimeout(showBar, 10);
  }

  document.addEventListener('mouseup', (e) => {
    if (inOwnUi(e.target as Node)) return;
    scheduleShow();
  });
  // 点击空白 / 开始新选择时收起
  document.addEventListener('mousedown', (e) => {
    if (inOwnUi(e.target as Node)) return;
    removeBar();
  });
  document.addEventListener('scroll', removeBar, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') removeBar(); });
})();
