/* eslint-disable */
// 辅助阅读模式 Content Script（经典脚本，不能 import）
// Reader View：白底浮层 + contenteditable 正文 + 本地缓存

(function () {
  const PANEL_ID = '__ethan_reading_panel';
  const READER_ID = '__ethan_reading_reader';
  const CONTENT_ID = '__ethan_reading_content';
  const TOOLBAR_ID = '__ethan_reading_toolbar';
  const FORMAT_BAR_ID = '__ethan_reading_format_bar';
  const PROGRESS_ID = '__ethan_reading_progress';
  const REENTER_ID = '__ethan_reading_reenter';
  const EXPAND_TAB_ID = '__ethan_reading_expand_tab';
  const DELETE_POPUP_ID = '__ethan_reading_delete_popup';
  const Z_READER = 2147483640;
  const Z_PANEL = 2147483645;
  const Z_TOOLBAR = 2147483647;
  const Z_FORMAT_BAR = 2147483643;
  const Z_PROGRESS = 2147483646;
  const Z_REENTER = 2147483620;

  let active = false;
  let contentEl: HTMLElement | null = null;
  let cleanedText = '';
  let summaryText = '';
  let currentUrl = location.href;
  let scrollHandler: (() => void) | null = null;
  let panelCollapsed = false;
  let activeChatHandlers: Set<(msg: any) => void> = new Set();
  let saveTimer: number | null = null;
  // 内联多轮对话：每次进入阅读模式生成一个 session（服务端按此维护上下文），
  // 首轮把正文塞进 prompt，后续轮只发问题、历史由服务端拼。
  let chatSessionId = '';
  let chatBusy = false;

  // ========== Utilities ==========

  function genId(): string { return Math.random().toString(36).slice(2, 10) + Date.now().toString(36); }
  function escapeHtml(s: string): string { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function estimateReadTime(text: string): number { return Math.max(1, Math.ceil(text.length / 400)); }
  function clamp(v: number, min: number, max: number): number { return Math.max(min, Math.min(max, v)); }
  function isDarkMode(): boolean { return window.matchMedia('(prefers-color-scheme: dark)').matches; }

  function storageKey(): string {
    let hash = 0;
    for (let i = 0; i < currentUrl.length; i++) hash = ((hash << 5) - hash + currentUrl.charCodeAt(i)) | 0;
    return 'reading_' + Math.abs(hash).toString(36);
  }

  // ========== Local Storage (chrome.storage.local) ==========

  interface SavedData {
    url: string;
    title: string;
    html: string;
    summary?: string;
    savedAt: number;
  }

  function saveContent() {
    if (!contentEl) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      const data: SavedData = {
        url: currentUrl,
        title: document.title || '',
        html: contentEl!.innerHTML,
        summary: summaryText || undefined,
        savedAt: Date.now(),
      };
      chrome.storage.local.set({ [storageKey()]: data });
    }, 800);
  }

  function loadContent(cb: (data: SavedData | null) => void) {
    chrome.storage.local.get([storageKey()], (result) => {
      const data = result[storageKey()] as SavedData | undefined;
      cb(data && data.url === currentUrl ? data : null);
    });
  }

  // ========== Content Detection & Cleaning ==========
  // 检测正文 / 清洗 / 转 Markdown 统一走 reader-extract.js 暴露的 window.__ethanReader，
  // 注入顺序由 reading-injector.ts 保证（reader-extract 先于 reading-mode）。

  interface EthanReaderApi {
    detectArticle(): HTMLElement;
    cleanArticle(el: HTMLElement): HTMLElement;
    htmlToMarkdown(root: HTMLElement): string;
    extractMarkdown(): { markdown: string; length: number; title: string; url: string };
  }

  function ethanReader(): EthanReaderApi {
    const api = (window as any).__ethanReader as EthanReaderApi | undefined;
    if (!api) throw new Error('__ethanReader not injected');
    return api;
  }

  // ========== TOC from content ==========

  interface TocItem { level: number; text: string; el: HTMLElement; }

  function generateToc(root: HTMLElement): TocItem[] {
    const items: TocItem[] = [];
    root.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
      const el = h as HTMLElement;
      const text = el.textContent?.trim() || '';
      if (!text || text.length > 80) return;
      items.push({ level: parseInt(el.tagName[1]), text, el });
    });
    return items;
  }

  // ========== Reader Overlay ==========

  function createReader(html: string) {
    removeReader();
    const dark = isDarkMode();
    const reader = document.createElement('div');
    reader.id = READER_ID;
    Object.assign(reader.style, {
      position: 'fixed', top: '0', left: '0', right: '0', bottom: '0',
      zIndex: String(Z_READER),
      background: dark ? '#1a1d24' : '#ffffff',
      overflowY: 'auto', overflowX: 'hidden',
      opacity: '0', transition: 'opacity 0.3s ease',
    });

    // Format bar
    const formatBar = createFormatBar(dark);
    reader.appendChild(formatBar);

    // Content
    const content = document.createElement('div');
    content.id = CONTENT_ID;
    content.contentEditable = 'true';
    content.spellcheck = false;
    Object.assign(content.style, {
      maxWidth: '720px', margin: '64px auto 100px', padding: '0 40px',
      fontSize: '17px', lineHeight: '1.9',
      color: dark ? '#e2e4e8' : '#1f2430',
      fontFamily: '-apple-system, "PingFang SC", "Noto Sans SC", system-ui, sans-serif',
      wordBreak: 'break-word', outline: 'none', minHeight: '60vh',
    });
    content.innerHTML = html;
    reader.appendChild(content);

    document.body.appendChild(reader);
    contentEl = content;
    cleanedText = content.innerText || '';

    // Style content
    styleContent(content, dark);

    // Fade in
    requestAnimationFrame(() => { reader.style.opacity = '1'; });
    document.body.style.overflow = 'hidden';

    // Auto-save on edit
    content.addEventListener('input', () => { saveContent(); refreshToc(); });
  }

  function styleContent(container: HTMLElement, dark: boolean) {
    const css = document.createElement('style');
    css.id = '__ethan_reading_content_styles';
    css.textContent = [
      '#' + CONTENT_ID + ' h1,#' + CONTENT_ID + ' h2,#' + CONTENT_ID + ' h3,#' + CONTENT_ID + ' h4,#' + CONTENT_ID + ' h5,#' + CONTENT_ID + ' h6 { position:relative; }',
      '#' + CONTENT_ID + ' h1::before,#' + CONTENT_ID + ' h2::before,#' + CONTENT_ID + ' h3::before,#' + CONTENT_ID + ' h4::before,#' + CONTENT_ID + ' h5::before,#' + CONTENT_ID + ' h6::before { font-size:10px; font-weight:500; color:' + (dark ? '#6b7280' : '#9ca3af') + '; margin-right:6px; vertical-align:middle; letter-spacing:0.3px; }',
      '#' + CONTENT_ID + ' h1::before { content:"H1"; }',
      '#' + CONTENT_ID + ' h2::before { content:"H2"; }',
      '#' + CONTENT_ID + ' h3::before { content:"H3"; }',
      '#' + CONTENT_ID + ' h4::before { content:"H4"; }',
      '#' + CONTENT_ID + ' h5::before { content:"H5"; }',
      '#' + CONTENT_ID + ' h6::before { content:"H6"; }',
      '#' + CONTENT_ID + ' h1 { font-size:24px; font-weight:700; margin:1.8em 0 0.6em; line-height:1.3; color:' + (dark ? '#f3f4f6' : '#111827') + '; }',
      '#' + CONTENT_ID + ' h2 { font-size:21px; font-weight:600; margin:1.6em 0 0.5em; line-height:1.3; color:' + (dark ? '#f3f4f6' : '#111827') + '; }',
      '#' + CONTENT_ID + ' h3 { font-size:18px; font-weight:600; margin:1.4em 0 0.5em; line-height:1.4; color:' + (dark ? '#f3f4f6' : '#111827') + '; }',
      '#' + CONTENT_ID + ' h4,#' + CONTENT_ID + ' h5,#' + CONTENT_ID + ' h6 { font-size:16px; font-weight:600; margin:1.2em 0 0.4em; }',
      '#' + CONTENT_ID + ' p { margin-bottom:1.1em; }',
      '#' + CONTENT_ID + ' img { max-width:100%; height:auto; border-radius:8px; margin:20px 0; display:block; }',
      '#' + CONTENT_ID + ' pre { font-size:14px; border-radius:8px; padding:16px 20px; overflow-x:auto; background:' + (dark ? '#2a2e37' : '#f5f5f5') + '; margin:16px 0; line-height:1.5; }',
      '#' + CONTENT_ID + ' code { font-size:14px; border-radius:4px; padding:2px 6px; background:' + (dark ? '#2a2e37' : '#f5f5f5') + '; }',
      '#' + CONTENT_ID + ' pre code { padding:0; background:none; }',
      '#' + CONTENT_ID + ' blockquote { border-left:3px solid ' + (dark ? '#4b5563' : '#d1d5db') + '; padding-left:16px; margin:16px 0; color:' + (dark ? '#9ca3af' : '#6b7280') + '; font-style:italic; }',
      '#' + CONTENT_ID + ' ul,#' + CONTENT_ID + ' ol { padding-left:24px; margin-bottom:1em; }',
      '#' + CONTENT_ID + ' li { margin-bottom:0.4em; }',
      '#' + CONTENT_ID + ' a { color:#0d9488; text-decoration:underline; text-underline-offset:3px; }',
      '#' + CONTENT_ID + ' table { border-collapse:collapse; width:100%; margin:16px 0; font-size:14px; }',
      '#' + CONTENT_ID + ' th,#' + CONTENT_ID + ' td { border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + '; padding:8px 12px; text-align:left; }',
      '#' + CONTENT_ID + ' th { background:' + (dark ? '#2a2e37' : '#f9fafb') + '; font-weight:600; }',
      '#' + CONTENT_ID + ' mark { border-radius:0.2em; padding:0.04em 0.02em; cursor:pointer; }',
      '#' + CONTENT_ID + ' mark.anno-yellow { background:oklch(0.92 0.16 105/0.85); font-weight:600; }',
      '#' + CONTENT_ID + ' mark.anno-blue { background:oklch(0.90 0.13 230/0.75); font-weight:600; }',
      '#' + CONTENT_ID + ' mark.anno-green { background:oklch(0.92 0.14 150/0.70); font-weight:600; }',
      '#' + CONTENT_ID + ' mark.anno-pink { background:oklch(0.92 0.14 350/0.70); font-weight:600; }',
      '#' + CONTENT_ID + ' mark.anno-commented { border-bottom:2px dashed #0d9488; cursor:help; }',
      '#' + CONTENT_ID + ' mark.anno-commented::after { content:"💬"; font-size:10px; vertical-align:super; margin-left:2px; }',
      '#' + CONTENT_ID + ' hr { border:none; border-top:1px solid ' + (dark ? '#374151' : '#e5e7eb') + '; margin:2em 0; }',
      '#' + READER_ID + '::-webkit-scrollbar { width:8px; }',
      '#' + READER_ID + '::-webkit-scrollbar-thumb { background:rgba(127,127,127,0.2); border-radius:4px; }',
      '#' + READER_ID + '::-webkit-scrollbar-thumb:hover { background:rgba(127,127,127,0.4); }',
    ].join('\n');
    document.head.appendChild(css);
  }

  function removeReader() {
    document.getElementById(READER_ID)?.remove();
    document.getElementById('__ethan_reading_content_styles')?.remove();
    document.body.style.overflow = '';
    contentEl = null;
  }

  // ========== Format Bar ==========

  function createFormatBar(dark: boolean): HTMLElement {
    const bar = document.createElement('div');
    bar.id = FORMAT_BAR_ID;
    Object.assign(bar.style, {
      position: 'sticky', top: '0', left: '0', right: '0',
      zIndex: String(Z_FORMAT_BAR),
      background: dark ? '#1c1f26ee' : '#ffffffee',
      backdropFilter: 'blur(8px)',
      borderBottom: '1px solid ' + (dark ? '#333' : '#e5e7eb'),
      padding: '8px 16px', display: 'flex', gap: '4px', alignItems: 'center',
      justifyContent: 'center', flexWrap: 'wrap',
    });

    const cmds: { label: string; cmd: string; arg?: string; title: string }[] = [
      { label: 'H1', cmd: 'formatBlock', arg: 'h1', title: '\u6807\u9898 1' },
      { label: 'H2', cmd: 'formatBlock', arg: 'h2', title: '\u6807\u9898 2' },
      { label: 'H3', cmd: 'formatBlock', arg: 'h3', title: '\u6807\u9898 3' },
      { label: 'P', cmd: 'formatBlock', arg: 'p', title: '\u6b63\u6587' },
      { label: 'B', cmd: 'bold', title: '\u52a0\u7c97 (Ctrl+B)' },
      { label: 'I', cmd: 'italic', title: '\u659c\u4f53 (Ctrl+I)' },
      { label: 'U', cmd: 'underline', title: '\u4e0b\u5212\u7ebf (Ctrl+U)' },
      { label: '\u2022', cmd: 'insertUnorderedList', title: '\u65e0\u5e8f\u5217\u8868' },
      { label: '1.', cmd: 'insertOrderedList', title: '\u6709\u5e8f\u5217\u8868' },
      { label: '\u201c', cmd: 'formatBlock', arg: 'blockquote', title: '\u5f15\u7528' },
      { label: '\u2015', cmd: 'insertHorizontalRule', title: '\u5206\u5272\u7ebf' },
    ];

    cmds.forEach(c => {
      const btn = document.createElement('button');
      btn.textContent = c.label;
      btn.title = c.title;
      Object.assign(btn.style, {
        border: 'none', borderRadius: '4px', padding: '4px 10px',
        cursor: 'pointer', fontSize: '13px', fontWeight: '600',
        background: dark ? '#374151' : '#f3f4f6', color: dark ? '#e6e8ec' : '#374151',
        transition: 'background 0.1s', minWidth: '28px',
      });
      btn.onmouseenter = () => { btn.style.background = dark ? '#4b5563' : '#e5e7eb'; };
      btn.onmouseleave = () => { btn.style.background = dark ? '#374151' : '#f3f4f6'; };
      btn.onmousedown = (e) => e.preventDefault(); // Keep selection
      btn.onclick = () => {
        if (c.arg) document.execCommand(c.cmd, false, c.arg);
        else document.execCommand(c.cmd);
        saveContent();
      };
      bar.appendChild(btn);
    });

    // Separator
    const sep = document.createElement('div');
    Object.assign(sep.style, { width: '1px', height: '20px', background: dark ? '#4b5563' : '#d1d5db', margin: '0 6px' });
    bar.appendChild(sep);

    // Highlight colors
    const colors = [
      { color: 'yellow', bg: '#fef08a', title: '\u91cd\u70b9' },
      { color: 'blue', bg: '#bfdbfe', title: '\u7591\u95ee' },
      { color: 'green', bg: '#bbf7d0', title: '\u5f85\u529e' },
      { color: 'pink', bg: '#fecdd3', title: '\u4e0d\u540c\u610f' },
    ];
    colors.forEach(c => {
      const btn = document.createElement('button');
      btn.textContent = '\u25cf';
      btn.title = '\u9ad8\u4eae: ' + c.title;
      Object.assign(btn.style, {
        border: 'none', borderRadius: '4px', padding: '4px 8px',
        cursor: 'pointer', fontSize: '14px', color: c.bg,
        background: dark ? '#374151' : '#f3f4f6', transition: 'background 0.1s',
      });
      btn.onmouseenter = () => { btn.style.background = dark ? '#4b5563' : '#e5e7eb'; };
      btn.onmouseleave = () => { btn.style.background = dark ? '#374151' : '#f3f4f6'; };
      btn.onmousedown = (e) => e.preventDefault();
      btn.onclick = () => applyHighlightColor(c.color);
      bar.appendChild(btn);
    });

    // Remove highlight button
    const rmHl = document.createElement('button');
    rmHl.textContent = '\u2718';
    rmHl.title = '\u53bb\u9664\u9ad8\u4eae';
    Object.assign(rmHl.style, {
      border: 'none', borderRadius: '4px', padding: '4px 8px',
      cursor: 'pointer', fontSize: '12px', color: dark ? '#9ca3af' : '#6b7280',
      background: dark ? '#374151' : '#f3f4f6', transition: 'background 0.1s',
    });
    rmHl.onmouseenter = () => { rmHl.style.background = dark ? '#4b5563' : '#e5e7eb'; };
    rmHl.onmouseleave = () => { rmHl.style.background = dark ? '#374151' : '#f3f4f6'; };
    rmHl.onmousedown = (e) => e.preventDefault();
    rmHl.onclick = () => removeHighlightFromSelection();
    bar.appendChild(rmHl);

    return bar;
  }

  // ========== Highlight ==========

  function applyHighlightColor(color: string) {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !contentEl) return;
    const range = sel.getRangeAt(0);
    if (!contentEl.contains(range.startContainer)) return;

    // Collect text nodes in range, then wrap each individually
    const textNodes: Text[] = [];
    const walker = document.createTreeWalker(
      range.commonAncestorContainer.nodeType === Node.TEXT_NODE
        ? range.commonAncestorContainer.parentElement!
        : range.commonAncestorContainer as HTMLElement,
      NodeFilter.SHOW_TEXT
    );
    let node: Node | null;
    while ((node = walker.nextNode())) {
      if (range.intersectsNode(node) && (node as Text).nodeValue?.trim()) {
        textNodes.push(node as Text);
      }
    }
    if (!textNodes.length) return;

    for (const tn of textNodes) {
      let target = tn;
      let startOff = 0;
      let endOff = tn.nodeValue!.length;

      if (tn === range.startContainer) startOff = range.startOffset;
      if (tn === range.endContainer) endOff = range.endOffset;

      // Split if partial
      if (startOff > 0) {
        target = tn.splitText(startOff);
        endOff -= startOff;
      }
      if (endOff < target.nodeValue!.length) {
        target.splitText(endOff);
      }

      const mark = document.createElement('mark');
      mark.className = 'anno-' + color;
      target.parentNode!.insertBefore(mark, target);
      mark.appendChild(target);
    }

    sel.removeAllRanges();
    saveContent();
  }

  function removeHighlightFromSelection() {
    const sel = window.getSelection();
    if (!sel || !contentEl) return;
    // If cursor is inside a mark, unwrap it
    const node = sel.anchorNode;
    const mark = node?.parentElement?.closest('mark') || (node as HTMLElement)?.closest?.('mark');
    if (mark && contentEl.contains(mark)) {
      const parent = mark.parentNode;
      if (parent) {
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
        parent.normalize();
      }
      saveContent();
    }
  }

  // ========== Selection Toolbar (highlight + comment) ==========

  let selectionListener: ((e: MouseEvent) => void) | null = null;
  let mousedownListener: ((e: MouseEvent) => void) | null = null;

  function setupSelectionListener() {
    selectionListener = (e: MouseEvent) => {
      if (!active || !contentEl) return;
      const target = e.target as HTMLElement;
      if (target.closest('#' + TOOLBAR_ID) || target.closest('#' + FORMAT_BAR_ID) || target.closest('#' + PANEL_ID)) return;
      setTimeout(() => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) { removeToolbar(); return; }
        const range = sel.getRangeAt(0);
        if (!contentEl!.contains(range.startContainer)) { removeToolbar(); return; }
        showToolbar(range.getBoundingClientRect());
      }, 10);
    };
    mousedownListener = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('#' + TOOLBAR_ID)) removeToolbar();
    };
    document.addEventListener('mouseup', selectionListener);
    document.addEventListener('mousedown', mousedownListener);
  }

  function teardownSelectionListener() {
    if (selectionListener) document.removeEventListener('mouseup', selectionListener);
    if (mousedownListener) document.removeEventListener('mousedown', mousedownListener);
    selectionListener = null; mousedownListener = null;
  }

  function showToolbar(rect: DOMRect) {
    removeToolbar();
    const dark = isDarkMode();
    const bar = document.createElement('div');
    bar.id = TOOLBAR_ID;
    Object.assign(bar.style, {
      position: 'fixed', zIndex: String(Z_TOOLBAR),
      left: (rect.left + rect.width / 2) + 'px', top: (rect.top - 44) + 'px',
      background: dark ? '#1f2937' : '#ffffff',
      border: '1px solid ' + (dark ? '#374151' : '#e5e7eb'),
      borderRadius: '10px', padding: '4px 6px',
      boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
      display: 'flex', alignItems: 'center', gap: '2px',
      opacity: '0', transform: 'translateX(-50%) translateY(4px)',
      transition: 'opacity 0.12s, transform 0.12s',
    });

    const colors = [
      { color: 'yellow', emoji: '\uD83D\uDFE1' },
      { color: 'blue', emoji: '\uD83D\uDD35' },
      { color: 'green', emoji: '\uD83D\uDFE2' },
      { color: 'pink', emoji: '\uD83D\uDFE3' },
    ];
    colors.forEach(c => {
      const btn = document.createElement('button');
      btn.textContent = c.emoji;
      Object.assign(btn.style, {
        border: 'none', background: 'none', fontSize: '14px', cursor: 'pointer',
        padding: '4px 6px', borderRadius: '6px', transition: 'background 0.1s',
      });
      btn.onmousedown = (e) => e.preventDefault();
      btn.onmouseenter = () => { btn.style.background = dark ? '#374151' : '#f3f4f6'; };
      btn.onmouseleave = () => { btn.style.background = ''; };
      btn.onclick = () => { removeToolbar(); applyHighlightColor(c.color); };
      bar.appendChild(btn);
    });

    // Separator
    const sep = document.createElement('div');
    Object.assign(sep.style, { width: '1px', height: '18px', background: dark ? '#4b5563' : '#e5e7eb', margin: '0 4px' });
    bar.appendChild(sep);

    // Comment button
    const commentBtn = document.createElement('button');
    commentBtn.textContent = '\uD83D\uDCAC';
    commentBtn.title = '\u6DFB\u52A0\u8BC4\u8BBA';
    Object.assign(commentBtn.style, {
      border: 'none', background: 'none', fontSize: '14px', cursor: 'pointer',
      padding: '4px 6px', borderRadius: '6px', transition: 'background 0.1s',
    });
    commentBtn.onmousedown = (e) => e.preventDefault();
    commentBtn.onmouseenter = () => { commentBtn.style.background = dark ? '#374151' : '#f3f4f6'; };
    commentBtn.onmouseleave = () => { commentBtn.style.background = ''; };
    // Save range before showing input (selection will be lost on focus)
    commentBtn.onclick = () => {
      const sel = window.getSelection();
      const savedRange = sel && sel.rangeCount > 0 ? sel.getRangeAt(0).cloneRange() : null;
      showCommentInput(bar, savedRange);
    };
    bar.appendChild(commentBtn);

    document.body.appendChild(bar);
    requestAnimationFrame(() => { bar.style.opacity = '1'; bar.style.transform = 'translateX(-50%) translateY(0)'; });
  }

  function showCommentInput(toolbar: HTMLElement, savedRange: Range | null) {
    const existing = toolbar.querySelector('.__ethan_comment_input_wrap');
    if (existing) return;
    const dark = isDarkMode();
    const wrap = document.createElement('div');
    wrap.className = '__ethan_comment_input_wrap';
    Object.assign(wrap.style, {
      position: 'absolute', top: '100%', left: '50%', transform: 'translateX(-50%)',
      marginTop: '6px', background: dark ? '#1f2937' : '#fff',
      border: '1px solid ' + (dark ? '#374151' : '#e5e7eb'),
      borderRadius: '8px', padding: '8px', boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
      display: 'flex', gap: '6px', alignItems: 'center', minWidth: '220px',
    });
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '\u8F93\u5165\u8BC4\u8BBA\u2026';
    Object.assign(input.style, {
      flex: '1', border: '1px solid ' + (dark ? '#4b5563' : '#d1d5db'),
      borderRadius: '6px', padding: '6px 10px', fontSize: '13px', outline: 'none',
      background: dark ? '#374151' : '#f9fafb', color: dark ? '#e6e8ec' : '#1f2430',
    });
    const okBtn = document.createElement('button');
    okBtn.textContent = '\u2713';
    Object.assign(okBtn.style, {
      border: 'none', background: '#0d9488', color: '#fff', borderRadius: '6px',
      padding: '6px 10px', cursor: 'pointer', fontSize: '13px',
    });
    okBtn.onclick = () => {
      const note = input.value.trim();
      if (note && savedRange && contentEl) {
        applyHighlightFromRange(savedRange, 'yellow', note);
      }
      removeToolbar();
    };
    input.onkeydown = (e) => { if (e.key === 'Enter') okBtn.click(); if (e.key === 'Escape') removeToolbar(); };
    wrap.appendChild(input);
    wrap.appendChild(okBtn);
    toolbar.appendChild(wrap);
    setTimeout(() => input.focus(), 50);
  }

  function applyHighlightFromRange(range: Range, color: string, note?: string) {
    if (!contentEl || !contentEl.contains(range.startContainer)) return;
    // Collect text nodes in range
    const textNodes: Text[] = [];
    const walker = document.createTreeWalker(
      range.commonAncestorContainer.nodeType === Node.TEXT_NODE
        ? range.commonAncestorContainer.parentElement!
        : range.commonAncestorContainer as HTMLElement,
      NodeFilter.SHOW_TEXT
    );
    let node: Node | null;
    while ((node = walker.nextNode())) {
      if (range.intersectsNode(node) && (node as Text).nodeValue?.trim()) {
        textNodes.push(node as Text);
      }
    }
    if (!textNodes.length) return;

    let firstMark: HTMLElement | null = null;
    for (const tn of textNodes) {
      let target = tn;
      let startOff = 0;
      let endOff = tn.nodeValue!.length;
      if (tn === range.startContainer) startOff = range.startOffset;
      if (tn === range.endContainer) endOff = range.endOffset;
      if (startOff > 0) { target = tn.splitText(startOff); endOff -= startOff; }
      if (endOff < target.nodeValue!.length) target.splitText(endOff);

      const mark = document.createElement('mark');
      mark.className = 'anno-' + color + (note ? ' anno-commented' : '');
      if (note) { mark.title = note; mark.dataset.note = note; }
      target.parentNode!.insertBefore(mark, target);
      mark.appendChild(target);
      if (!firstMark) firstMark = mark;
    }
    saveContent();
  }

  function removeToolbar() {
    document.getElementById(TOOLBAR_ID)?.remove();
  }

  // ========== Click mark to show delete ==========

  let markClickListener: ((e: MouseEvent) => void) | null = null;

  function setupMarkClickListener() {
    markClickListener = (e: MouseEvent) => {
      if (!active || !contentEl) return;
      const mark = (e.target as HTMLElement).closest('mark') as HTMLElement | null;
      if (!mark || !contentEl.contains(mark)) { removeDeletePopup(); return; }
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;
      showDeletePopup(mark);
    };
    document.addEventListener('click', markClickListener, true);
  }

  function teardownMarkClickListener() {
    if (markClickListener) document.removeEventListener('click', markClickListener, true);
    markClickListener = null;
  }

  function showDeletePopup(mark: HTMLElement) {
    removeDeletePopup();
    const rect = mark.getBoundingClientRect();
    const dark = isDarkMode();
    const popup = document.createElement('div');
    popup.id = DELETE_POPUP_ID;
    Object.assign(popup.style, {
      position: 'fixed', zIndex: String(Z_TOOLBAR),
      left: (rect.left + rect.width / 2 - 16) + 'px',
      top: (rect.top - 36) + 'px',
      background: dark ? '#374151' : '#ffffff',
      border: '1px solid ' + (dark ? '#4b5563' : '#e5e7eb'),
      borderRadius: '8px', padding: '2px 4px',
      boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
      display: 'flex', alignItems: 'center',
      opacity: '0', transform: 'translateY(4px)',
      transition: 'opacity 0.12s, transform 0.12s',
    });
    const delBtn = document.createElement('button');
    delBtn.textContent = '\uD83D\uDDD1';
    Object.assign(delBtn.style, {
      border: 'none', background: 'none', fontSize: '15px', cursor: 'pointer',
      padding: '4px 8px', borderRadius: '4px', transition: 'background 0.1s',
    });
    delBtn.title = '\u5220\u9664\u9ad8\u4eae';
    delBtn.onmouseenter = () => { delBtn.style.background = dark ? '#4b5563' : '#fee2e2'; };
    delBtn.onmouseleave = () => { delBtn.style.background = ''; };
    delBtn.onclick = (ev) => {
      ev.stopPropagation();
      removeDeletePopup();
      const parent = mark.parentNode;
      if (parent) {
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
        parent.normalize();
      }
      saveContent();
    };
    popup.appendChild(delBtn);

    // Show comment if exists
    const note = mark.dataset.note;
    if (note) {
      const noteEl = document.createElement('span');
      noteEl.textContent = note.length > 30 ? note.slice(0, 30) + '\u2026' : note;
      Object.assign(noteEl.style, {
        fontSize: '11px', color: dark ? '#9ca3af' : '#6b7280',
        padding: '2px 6px', maxWidth: '180px', overflow: 'hidden',
        whiteSpace: 'nowrap', textOverflow: 'ellipsis',
      });
      popup.appendChild(noteEl);
    }

    document.body.appendChild(popup);
    requestAnimationFrame(() => { popup.style.opacity = '1'; popup.style.transform = 'translateY(0)'; });
    setTimeout(() => { if (document.getElementById(DELETE_POPUP_ID)) removeDeletePopup(); }, 3500);
  }

  function removeDeletePopup() {
    document.getElementById(DELETE_POPUP_ID)?.remove();
  }

  // ========== Progress Bar ==========

  function createProgressBar() {
    if (document.getElementById(PROGRESS_ID)) return;
    const bar = document.createElement('div');
    bar.id = PROGRESS_ID;
    Object.assign(bar.style, {
      position: 'fixed', top: '0', left: '0', height: '3px',
      background: 'linear-gradient(90deg, #0d9488, #06b6d4)',
      zIndex: String(Z_PROGRESS), width: '0%', transition: 'width 0.15s linear',
      borderRadius: '0 2px 2px 0',
    });
    document.body.appendChild(bar);
  }

  function updateProgress() {
    const bar = document.getElementById(PROGRESS_ID);
    const reader = document.getElementById(READER_ID);
    if (!bar || !reader) return;
    const pct = reader.scrollHeight > reader.clientHeight
      ? Math.min(100, (reader.scrollTop / (reader.scrollHeight - reader.clientHeight)) * 100) : 0;
    bar.style.width = pct + '%';
  }

  function removeProgressBar() { document.getElementById(PROGRESS_ID)?.remove(); }

  // ========== Toast ==========

  function showToast(msg: string) {
    const existing = document.getElementById('__ethan_reading_toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.id = '__ethan_reading_toast';
    Object.assign(toast.style, {
      position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%) translateY(10px)',
      zIndex: String(Z_TOOLBAR), background: '#1f2937', color: '#fff',
      padding: '8px 16px', borderRadius: '8px', fontSize: '13px', fontWeight: '500',
      boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
      opacity: '0', transition: 'opacity 0.2s, transform 0.2s',
    });
    toast.textContent = msg;
    document.body.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; toast.style.transform = 'translateX(-50%) translateY(0)'; });
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 200); }, 1800);
  }

  // ========== AI Chat ==========

  // sessionId \u4f20\u5165\u65f6\u8d70\u591a\u8f6e\u5bf9\u8bdd\uff08\u670d\u52a1\u7aef\u6309 session \u62fc\u5386\u53f2\uff09\uff1b\u4e0d\u4f20\u8d70\u5355\u8f6e\uff08\u6458\u8981\uff09\u3002
  function requestChat(
    prompt: string,
    target: HTMLElement,
    opts: { sessionId?: string; onDone?: (text: string) => void } = {},
  ) {
    const reqId = genId();
    let buffer = '';
    target.innerHTML = '<span style="color:#9aa0aa;font-style:italic">\u601d\u8003\u4e2d\u2026</span>';
    const handler = (msg: any) => {
      if (msg?.target !== 'reading') return;
      if (msg.type === 'chatChunk' && msg.requestId === reqId) {
        buffer += msg.delta;
        target.innerHTML = renderMdSimple(buffer);
        target.scrollTop = target.scrollHeight;
      }
      if (msg.type === 'chatDone' && msg.requestId === reqId) {
        if (msg.error) target.innerHTML = '<span style="color:#ef4444">\u9519\u8bef: ' + escapeHtml(msg.error) + '</span>';
        activeChatHandlers.delete(handler);
        chrome.runtime.onMessage.removeListener(handler);
        if (opts.onDone) opts.onDone(buffer);
      }
    };
    activeChatHandlers.add(handler);
    chrome.runtime.onMessage.addListener(handler);
    chrome.runtime.sendMessage({ type: 'reading:chat', requestId: reqId, prompt, sessionId: opts.sessionId });
  }

  function renderMdSimple(md: string): string {
    let h = escapeHtml(md);
    // Tag section headers with data-section for tab scrolling
    h = h.replace(/^## .*\u6982\u8ff0.*$/gm, '<h3 data-section="overview" style="margin:10px 0 4px;font-size:14px;font-weight:600">\u6982\u8ff0</h3>');
    h = h.replace(/^## .*\u7ed3\u6784.*$/gm, '<h3 data-section="structure" style="margin:10px 0 4px;font-size:14px;font-weight:600">\u7ed3\u6784</h3>');
    h = h.replace(/^## .*\u91cd\u70b9.*$/gm, '<h3 data-section="keypoints" style="margin:10px 0 4px;font-size:14px;font-weight:600">\u91cd\u70b9</h3>');
    h = h.replace(/^### (.+)$/gm, '<h4 style="margin:8px 0 4px;font-size:13px;font-weight:600;color:#0d9488">$1</h4>');
    h = h.replace(/^## (.+)$/gm, '<h3 style="margin:10px 0 4px;font-size:14px;font-weight:600">$1</h3>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/^[-*] (.+)$/gm, '<div style="padding-left:12px;margin:2px 0">\u2022 $1</div>');
    h = h.replace(/\n/g, '<br>');
    return h;
  }

  // ========== Summary (with cache) ==========

  function requestSummary(target: HTMLElement) {
    if (summaryText) { target.innerHTML = renderMdSimple(summaryText); return; }
    const text = contentEl?.innerText || cleanedText;
    const prompt = '\u8fd9\u662f\u4e00\u7bc7\u6587\u7ae0\u7684\u6b63\u6587\uff0c\u8bf7\u7528\u4e2d\u6587\u56de\u590d\u3002\u8bf7\u4e25\u683c\u6309\u4ee5\u4e0b\u4e09\u4e2a\u90e8\u5206\u8f93\u51fa\uff1a\n\n## \u6982\u8ff0\n\u7528 1-2 \u53e5\u8bdd\u6982\u62ec\u6587\u7ae0\u4e3b\u65e8\u3002\n\n## \u7ed3\u6784\n\u5206\u5757\u5217\u51fa\u6587\u7ae0\u7ed3\u6784\uff08\u6bcf\u5757\u4e00\u884c\uff0c\u7528\u65e0\u5e8f\u5217\u8868\uff09\u3002\n\n## \u91cd\u70b9\n\u6307\u51fa 1-3 \u5904\u6700\u503c\u5f97\u5173\u6ce8\u7684\u5185\u5bb9\u3002\n\n\u6b63\u6587\u5982\u4e0b\uff1a\n\n' + text.slice(0, 8000);
    requestChat(prompt, target, {
      onDone: (result) => {
        summaryText = result;
        saveContent();
      },
    });
  }

  // ========== Save Knowledge ==========

  function saveKnowledge() {
    if (!contentEl) return;
    const btn = document.getElementById('__ethan_reading_save_kb') as HTMLButtonElement | null;
    if (btn) { btn.disabled = true; btn.textContent = '\u4fdd\u5b58\u4e2d\u2026'; }
    const title = document.title || 'Untitled';
    const md = ethanReader().htmlToMarkdown(contentEl);
    chrome.runtime.sendMessage({ type: 'reading:saveKnowledge', title, content: md }, (resp) => {
      if (resp?.ok) { showToast('\u5df2\u5b58\u5165\u77e5\u8bc6\u5e93'); if (btn) btn.textContent = '\u5df2\u4fdd\u5b58 \u2713'; }
      else { showToast('\u4fdd\u5b58\u5931\u8d25'); if (btn) { btn.disabled = false; btn.textContent = '\u5b58\u77e5\u8bc6\u5e93'; } }
    });
  }

  // ========== Panel ==========

  const PANEL_WIDTH = 320;
  let tocItemsRef: TocItem[] = [];

  function createPanel() {
    if (document.getElementById(PANEL_ID)) return;
    const dark = isDarkMode();
    const panel = document.createElement('div');
    panel.id = PANEL_ID;
    Object.assign(panel.style, {
      position: 'fixed', top: '0', right: '0', width: PANEL_WIDTH + 'px', height: '100vh',
      zIndex: String(Z_PANEL), overflowY: 'auto', overflowX: 'hidden',
      background: dark ? '#1c1f26' : '#fafafa',
      color: dark ? '#e6e8ec' : '#1f2430',
      borderLeft: '1px solid ' + (dark ? '#333' : '#e5e7eb'),
      boxShadow: '-4px 0 24px rgba(0,0,0,0.1)',
      padding: '20px 16px', fontFamily: '-apple-system, system-ui, "PingFang SC", sans-serif',
      fontSize: '13px', lineHeight: '1.6',
      transform: 'translateX(100%)', transition: 'transform 0.3s cubic-bezier(0.4,0,0.2,1)',
    });

    const secTitle = (t: string) => '<div style="font-weight:600;margin-bottom:8px;font-size:11px;letter-spacing:0.5px;color:' + (dark ? '#6b7280' : '#9ca3af') + '">' + t + '</div>';
    const btnS = 'width:100%;padding:10px;border:none;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;transition:opacity 0.2s;';
    const charCount = (contentEl?.innerText || '').length;

    panel.innerHTML = [
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">',
      '  <div style="display:flex;align-items:center;gap:8px"><div style="width:8px;height:8px;border-radius:50%;background:#0d9488"></div><strong style="font-size:15px">\u8f85\u52a9\u9605\u8bfb</strong></div>',
      '  <div style="display:flex;gap:4px">',
      '    <button id="__ethan_reading_collapse" style="border:none;background:' + (dark ? '#374151' : '#f3f4f6') + ';cursor:pointer;font-size:14px;padding:4px 8px;border-radius:6px;color:inherit" title="\u6298\u53e0">\u25C0</button>',
      '    <button id="__ethan_reading_close" style="border:none;background:' + (dark ? '#374151' : '#f3f4f6') + ';cursor:pointer;font-size:14px;padding:4px 8px;border-radius:6px;color:inherit" title="\u9000\u51fa (Esc)">\u2715</button>',
      '  </div>',
      '</div>',
      '<div style="display:flex;gap:8px;margin-bottom:16px;font-size:12px;color:' + (dark ? '#9ca3af' : '#6b7280') + '">',
      '  <span>\u7ea6 ' + charCount.toLocaleString() + ' \u5b57</span><span>\u00b7</span><span>\u9884\u8ba1 ' + estimateReadTime(contentEl?.innerText || '') + ' \u5206\u949f</span>',
      '</div>',
      '<div style="margin-bottom:20px;padding:12px;border-radius:10px;background:' + (dark ? '#2a2e37' : '#fff') + ';border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + '">',
      '  <div style="display:flex;gap:12px;margin-bottom:10px">' +
      '    <button class="__ethan_sum_tab" data-section="overview" style="border:none;background:none;padding:2px 0;font-size:11px;font-weight:600;letter-spacing:0.5px;cursor:pointer;color:#0d9488;border-bottom:2px solid #0d9488">\u6982\u8ff0</button>' +
      '    <button class="__ethan_sum_tab" data-section="structure" style="border:none;background:none;padding:2px 0;font-size:11px;font-weight:600;letter-spacing:0.5px;cursor:pointer;color:' + (dark ? '#6b7280' : '#9ca3af') + ';border-bottom:2px solid transparent">\u7ed3\u6784</button>' +
      '    <button class="__ethan_sum_tab" data-section="keypoints" style="border:none;background:none;padding:2px 0;font-size:11px;font-weight:600;letter-spacing:0.5px;cursor:pointer;color:' + (dark ? '#6b7280' : '#9ca3af') + ';border-bottom:2px solid transparent">\u91cd\u70b9</button>' +
      '  </div>',
      '  <div id="__ethan_reading_summary_content" style="font-size:13px;max-height:400px;overflow-y:auto;scroll-behavior:smooth;position:relative"></div>',
      '</div>',
      '<div style="margin-bottom:20px">' + secTitle('\u76ee\u5f55') + '<div id="__ethan_reading_toc" style="max-height:240px;overflow-y:auto"></div></div>',
      '<div style="margin-bottom:20px">' + secTitle('\u5411 Ethan \u63d0\u95ee') +
      '  <div id="__ethan_reading_chat_log" style="max-height:280px;overflow-y:auto;margin-bottom:8px"></div>' +
      '  <div style="display:flex;gap:6px;align-items:flex-end">' +
      '    <textarea id="__ethan_reading_chat_input" rows="1" placeholder="\u5c31\u8fd9\u7bc7\u6587\u7ae0\u63d0\u95ee\u2026" style="flex:1;resize:none;padding:8px 10px;border-radius:8px;border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';background:' + (dark ? '#2a2e37' : '#fff') + ';color:inherit;font-size:13px;font-family:inherit;line-height:1.4;max-height:96px;outline:none"></textarea>' +
      '    <button id="__ethan_reading_chat_send" style="flex:none;padding:8px 12px;border:none;border-radius:8px;background:#0d9488;color:#fff;font-size:13px;font-weight:500;cursor:pointer">\u53d1\u9001</button>' +
      '  </div>' +
      '</div>',
      '<div style="margin-top:auto;padding-top:12px;border-top:1px solid ' + (dark ? '#374151' : '#f3f4f6') + '">',
      '  <button id="__ethan_reading_save_kb" style="' + btnS + 'background:linear-gradient(135deg,#0d9488,#06b6d4);color:#fff;margin-bottom:8px">\u5b58\u77e5\u8bc6\u5e93</button>',
      '  <button id="__ethan_reading_clear_cache" style="' + btnS + 'background:' + (dark ? '#374151' : '#f3f4f6') + ';color:' + (dark ? '#9ca3af' : '#6b7280') + '">\u6e05\u9664\u7f13\u5b58\uff08\u91cd\u65b0\u52a0\u8f7d\uff09</button>',
      '</div>',
      '<div style="margin-top:12px;padding:8px;border-radius:8px;background:' + (dark ? '#2a2e37' : '#fff') + ';font-size:11px;color:' + (dark ? '#6b7280' : '#9ca3af') + ';border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + '">',
      '  \u5185\u5bb9\u53ef\u76f4\u63a5\u7f16\u8f91 \u00b7 \u81ea\u52a8\u4fdd\u5b58 \u00b7 <kbd style="padding:1px 4px;border-radius:3px;background:' + (dark ? '#374151' : '#e5e7eb') + '">Esc</kbd> \u9000\u51fa',
      '</div>',
    ].join('\n');

    document.body.appendChild(panel);
    requestAnimationFrame(() => { panel.style.transform = 'translateX(0)'; });

    // Render TOC
    refreshToc();

    // Events
    document.getElementById('__ethan_reading_close')!.onclick = exitReading;
    document.getElementById('__ethan_reading_collapse')!.onclick = collapsePanel;
    document.getElementById('__ethan_reading_save_kb')!.onclick = saveKnowledge;
    document.getElementById('__ethan_reading_clear_cache')!.onclick = () => {
      chrome.storage.local.remove([storageKey()], () => {
        showToast('\u5df2\u6e05\u9664\u7f13\u5b58');
        exitReading();
        setTimeout(() => enterReading(), 400);
      });
    };

    // Summary tab clicks → scroll to section anchors
    const dark2 = isDarkMode();
    panel.querySelectorAll<HTMLButtonElement>('.__ethan_sum_tab').forEach(tab => {
      tab.onclick = () => {
        const section = tab.dataset.section;
        const container = document.getElementById('__ethan_reading_summary_content');
        if (!container) return;
        // Update tab active styles
        panel.querySelectorAll<HTMLButtonElement>('.__ethan_sum_tab').forEach(t => {
          t.style.color = dark2 ? '#6b7280' : '#9ca3af';
          t.style.borderBottomColor = 'transparent';
        });
        tab.style.color = '#0d9488';
        tab.style.borderBottomColor = '#0d9488';
        // Find section anchor and scroll
        const anchor = container.querySelector('[data-section="' + section + '"]') as HTMLElement | null;
        if (anchor) {
          container.scrollTo({ top: anchor.offsetTop, behavior: 'smooth' });
        } else {
          // Fallback: if AI hasn't output this section yet, scroll to top/middle/bottom
          const fallback = section === 'overview' ? 0 : section === 'structure' ? container.scrollHeight * 0.33 : container.scrollHeight * 0.66;
          container.scrollTo({ top: fallback, behavior: 'smooth' });
        }
      };
    });

    // Inline chat
    setupChat(dark);
  }

  // ========== Inline Chat（多轮对话）==========

  function setupChat(dark: boolean) {
    const input = document.getElementById('__ethan_reading_chat_input') as HTMLTextAreaElement | null;
    const sendBtn = document.getElementById('__ethan_reading_chat_send') as HTMLButtonElement | null;
    if (!input || !sendBtn) return;

    // 自适应高度
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 96) + 'px';
    });
    // Enter 发送，Shift+Enter 换行
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(dark); }
    });
    sendBtn.onclick = () => sendChat(dark);
  }

  let firstChatTurn = true;

  function sendChat(dark: boolean) {
    const input = document.getElementById('__ethan_reading_chat_input') as HTMLTextAreaElement | null;
    const log = document.getElementById('__ethan_reading_chat_log');
    if (!input || !log || chatBusy) return;
    const question = input.value.trim();
    if (!question) return;

    input.value = '';
    input.style.height = 'auto';
    chatBusy = true;

    // 用户气泡
    const userBubble = document.createElement('div');
    Object.assign(userBubble.style, {
      margin: '8px 0', padding: '8px 10px', borderRadius: '8px',
      background: dark ? '#374151' : '#eef2ff', fontSize: '13px', lineHeight: '1.5',
      wordBreak: 'break-word',
    });
    userBubble.textContent = question;
    log.appendChild(userBubble);

    // 助手气泡（流式填充）
    const answer = document.createElement('div');
    Object.assign(answer.style, {
      margin: '8px 0 12px', padding: '8px 10px', borderRadius: '8px',
      background: dark ? '#2a2e37' : '#fff', border: '1px solid ' + (dark ? '#374151' : '#e5e7eb'),
      fontSize: '13px', lineHeight: '1.6', wordBreak: 'break-word',
    });
    log.appendChild(answer);
    log.scrollTop = log.scrollHeight;

    // 首轮把正文塞进 prompt，后续轮只发问题（历史由服务端按 session 拼）
    let prompt = question;
    if (firstChatTurn) {
      const body = (contentEl?.innerText || cleanedText).slice(0, 8000);
      prompt = '下面是一篇文章的正文，请阅读后用中文回答我的问题。回答后无需重复正文。\n\n===== 正文开始 =====\n'
        + body + '\n===== 正文结束 =====\n\n我的问题：' + question;
      firstChatTurn = false;
    }

    requestChat(prompt, answer, {
      sessionId: chatSessionId,
      onDone: () => {
        chatBusy = false;
        log.scrollTop = log.scrollHeight;
      },
    });
  }

  function refreshToc() {
    if (!contentEl) return;
    tocItemsRef = generateToc(contentEl);
    const tocEl = document.getElementById('__ethan_reading_toc');
    if (!tocEl) return;
    const dark = isDarkMode();
    if (!tocItemsRef.length) {
      tocEl.innerHTML = '<div style="color:' + (dark ? '#6b7280' : '#9ca3af') + ';font-size:12px">\u672a\u68c0\u6d4b\u5230\u6807\u9898</div>';
      return;
    }
    tocEl.innerHTML = '';
    const minLevel = Math.min(...tocItemsRef.map(t => t.level));
    tocItemsRef.forEach((item, i) => {
      const indent = (item.level - minLevel) * 14;
      const div = document.createElement('div');
      Object.assign(div.style, {
        padding: '4px 6px 4px ' + (indent + 6) + 'px',
        borderRadius: '6px', fontSize: '12px', cursor: 'pointer',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        transition: 'background 0.15s', borderLeft: '2px solid transparent',
      });
      div.textContent = item.text;
      div.dataset.tocIdx = String(i);
      div.onmouseenter = () => { div.style.background = dark ? '#374151' : '#f3f4f6'; };
      div.onmouseleave = () => { div.style.background = ''; };
      div.onclick = () => {
        const reader = document.getElementById(READER_ID);
        if (reader && item.el) { reader.scrollTo({ top: item.el.offsetTop - 80, behavior: 'smooth' }); }
      };
      tocEl.appendChild(div);
    });
  }

  // ========== Panel Collapse / Expand ==========

  function collapsePanel() {
    const p = document.getElementById(PANEL_ID);
    if (!p) return;
    panelCollapsed = true;
    p.style.transform = 'translateX(100%)';
    const reader = document.getElementById(READER_ID);
    if (reader) reader.style.paddingRight = '0';
    showExpandTab();
  }

  function expandPanel() {
    const p = document.getElementById(PANEL_ID);
    if (!p) return;
    panelCollapsed = false;
    p.style.transform = 'translateX(0)';
    const reader = document.getElementById(READER_ID);
    if (reader) reader.style.paddingRight = PANEL_WIDTH + 'px';
    removeExpandTab();
  }

  function showExpandTab() {
    if (document.getElementById(EXPAND_TAB_ID)) return;
    const dark = isDarkMode();
    const tab = document.createElement('button');
    tab.id = EXPAND_TAB_ID;
    Object.assign(tab.style, {
      position: 'fixed', top: '50%', right: '0', transform: 'translateY(-50%)',
      zIndex: String(Z_PANEL + 1), width: '24px', height: '56px',
      background: dark ? '#2a2e37' : '#fff', border: '1px solid ' + (dark ? '#374151' : '#e5e7eb'),
      borderRight: 'none', borderRadius: '8px 0 0 8px',
      cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: '-2px 0 8px rgba(0,0,0,0.08)', color: '#0d9488', fontSize: '12px',
    });
    tab.textContent = '\u25C0';
    tab.title = '\u5c55\u5f00\u9762\u677f';
    tab.onclick = expandPanel;
    document.body.appendChild(tab);
  }

  function removeExpandTab() { document.getElementById(EXPAND_TAB_ID)?.remove(); }

  // ========== Scroll Spy ==========

  function setupScrollSpy() {
    const reader = document.getElementById(READER_ID);
    if (!reader) return;
    let ticking = false;
    scrollHandler = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => { updateProgress(); highlightToc(); ticking = false; });
    };
    reader.addEventListener('scroll', scrollHandler, { passive: true });
  }

  function teardownScrollSpy() {
    if (scrollHandler) {
      const reader = document.getElementById(READER_ID);
      if (reader) reader.removeEventListener('scroll', scrollHandler);
    }
    scrollHandler = null;
  }

  function highlightToc() {
    if (!tocItemsRef.length) return;
    const tocEl = document.getElementById('__ethan_reading_toc');
    const reader = document.getElementById(READER_ID);
    if (!tocEl || !reader) return;
    const scrollTop = reader.scrollTop;
    let activeIdx = 0;
    for (let i = tocItemsRef.length - 1; i >= 0; i--) {
      if (tocItemsRef[i].el.offsetTop <= scrollTop + 120) { activeIdx = i; break; }
    }
    tocEl.querySelectorAll<HTMLElement>('[data-toc-idx]').forEach((el, i) => {
      el.style.fontWeight = i === activeIdx ? '600' : '';
      el.style.color = i === activeIdx ? '#0d9488' : '';
      el.style.borderLeftColor = i === activeIdx ? '#0d9488' : 'transparent';
    });
  }

  // ========== Keyboard ==========

  let keydownListener: ((e: KeyboardEvent) => void) | null = null;

  function setupKeyboard() {
    keydownListener = (e: KeyboardEvent) => {
      if (!active) return;
      if (e.key === 'Escape') exitReading();
    };
    document.addEventListener('keydown', keydownListener);
  }

  function teardownKeyboard() {
    if (keydownListener) document.removeEventListener('keydown', keydownListener);
    keydownListener = null;
  }

  // ========== Re-enter Button ==========

  function showReenterButton() {
    if (document.getElementById(REENTER_ID)) return;
    const btn = document.createElement('button');
    btn.id = REENTER_ID;
    Object.assign(btn.style, {
      position: 'fixed', bottom: '20px', right: '20px', zIndex: String(Z_REENTER),
      width: '44px', height: '44px', borderRadius: '50%',
      background: 'linear-gradient(135deg,#0d9488,#06b6d4)', border: 'none',
      color: '#fff', fontSize: '18px', cursor: 'pointer',
      boxShadow: '0 4px 16px rgba(13,148,136,0.4)',
      transition: 'transform 0.2s',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    });
    btn.textContent = '\uD83D\uDCD6';
    btn.title = '\u91cd\u65b0\u8fdb\u5165\u9605\u8bfb\u6a21\u5f0f';
    btn.onmouseenter = () => { btn.style.transform = 'scale(1.1)'; };
    btn.onmouseleave = () => { btn.style.transform = ''; };
    btn.onclick = () => { btn.remove(); enterReading(); };
    document.body.appendChild(btn);
  }

  function removeReenterButton() { document.getElementById(REENTER_ID)?.remove(); }

  // ========== Enter / Exit ==========

  function enterReading() {
    if (active) return;
    active = true;
    panelCollapsed = false;
    // 每次进入生成一个新对话 session；首轮问题会带上正文，后续轮由服务端按此拼历史
    chatSessionId = 'read-' + genId();
    chatBusy = false;
    firstChatTurn = true;
    removeReenterButton();
    removeExpandTab();

    loadContent((cached) => {
      if (cached) {
        // Load from cache
        summaryText = cached.summary || '';
        createReader(cached.html);
      } else {
        // Fresh: detect + clean
        const article = ethanReader().detectArticle();
        const cleanDom = ethanReader().cleanArticle(article);
        // Build initial HTML with title
        const dark = isDarkMode();
        const titleHtml = '<h1>' + escapeHtml(document.title || '') + '</h1>';
        const metaHtml = '<p style="font-size:13px;color:#9ca3af;border-bottom:1px solid #e5e7eb;padding-bottom:16px;margin-bottom:24px">' +
          escapeHtml(new URL(currentUrl).hostname) + '</p>';
        const html = titleHtml + metaHtml + cleanDom.innerHTML;
        createReader(html);
        saveContent();
      }

      // Reserve panel space
      const reader = document.getElementById(READER_ID);
      if (reader) reader.style.paddingRight = PANEL_WIDTH + 'px';

      createProgressBar();
      createPanel();
      setupScrollSpy();
      setupSelectionListener();
      setupMarkClickListener();
      setupKeyboard();

      // AI summary
      const summaryEl = document.getElementById('__ethan_reading_summary_content');
      if (summaryEl) requestSummary(summaryEl);
    });
  }

  function exitReading() {
    if (!active) return;
    active = false;
    panelCollapsed = false;

    // Final save
    if (contentEl) saveContent();

    teardownScrollSpy();
    teardownSelectionListener();
    teardownMarkClickListener();
    teardownKeyboard();
    activeChatHandlers.forEach(h => chrome.runtime.onMessage.removeListener(h));
    activeChatHandlers.clear();

    removeReader();
    removeToolbar();
    removeProgressBar();
    removeExpandTab();
    removeDeletePopup();

    const panel = document.getElementById(PANEL_ID);
    if (panel) { panel.style.transform = 'translateX(100%)'; setTimeout(() => panel.remove(), 300); }

    document.getElementById('__ethan_reading_toast')?.remove();
    contentEl = null;
    cleanedText = '';
    summaryText = '';

    showReenterButton();
  }

  // ========== Message Listener ==========

  const w = window as any;
  if (!w.__ethanReadingListenerAdded) {
    w.__ethanReadingListenerAdded = true;
    chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
      if (msg?.target !== 'reading') return;
      if (msg.type === 'start') enterReading();
      return false;
    });
  }
})();
