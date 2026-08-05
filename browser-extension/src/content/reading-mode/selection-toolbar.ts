// @ts-nocheck
/* eslint-disable */

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

    // Underline button
    const underlineBtn = document.createElement('button');
    underlineBtn.textContent = 'U\u0332';
    underlineBtn.title = '\u5212\u7ebf';
    Object.assign(underlineBtn.style, {
      border: 'none', background: 'none', fontSize: '14px', fontWeight: '600', cursor: 'pointer',
      padding: '4px 6px', borderRadius: '6px', transition: 'background 0.1s', color: dark ? '#e6e8ec' : '#374151',
    });
    underlineBtn.onmousedown = (e) => e.preventDefault();
    underlineBtn.onmouseenter = () => { underlineBtn.style.background = dark ? '#374151' : '#f3f4f6'; };
    underlineBtn.onmouseleave = () => { underlineBtn.style.background = ''; };
    underlineBtn.onclick = () => {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        applyAnnotation(sel.getRangeAt(0), 'underline', 'yellow');
        sel.removeAllRanges();
      }
      removeToolbar();
    };
    bar.appendChild(underlineBtn);

    // Bookmark button
    const bookmarkBtn = document.createElement('button');
    bookmarkBtn.textContent = '\uD83D\uDD16';
    bookmarkBtn.title = '\u4E66\u7B7E';
    Object.assign(bookmarkBtn.style, {
      border: 'none', background: 'none', fontSize: '14px', cursor: 'pointer',
      padding: '4px 6px', borderRadius: '6px', transition: 'background 0.1s',
    });
    bookmarkBtn.onmousedown = (e) => e.preventDefault();
    bookmarkBtn.onmouseenter = () => { bookmarkBtn.style.background = dark ? '#374151' : '#f3f4f6'; };
    bookmarkBtn.onmouseleave = () => { bookmarkBtn.style.background = ''; };
    bookmarkBtn.onclick = () => {
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.rangeCount > 0) {
        applyAnnotation(sel.getRangeAt(0), 'bookmark', 'pink');
        sel.removeAllRanges();
      }
      removeToolbar();
    };
    bar.appendChild(bookmarkBtn);

    // Separator
    const sep2 = document.createElement('div');
    Object.assign(sep2.style, { width: '1px', height: '18px', background: dark ? '#4b5563' : '#e5e7eb', margin: '0 4px' });
    bar.appendChild(sep2);

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
    applyAnnotation(range, 'comment', color, note);
  }

  function removeToolbar() {
    document.getElementById(TOOLBAR_ID)?.remove();
  }
