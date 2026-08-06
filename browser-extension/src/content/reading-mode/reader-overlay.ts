// @ts-nocheck
/* eslint-disable */

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

    // 语法高亮 + 复制/换行按钮
    enhanceCodeBlocks(content, dark);

    // Fade in给正文图片绑定 hover 放大/删除按钮
    setupImageOverlays();

    // Fade in
    requestAnimationFrame(() => { reader.style.opacity = '1'; });
    document.body.style.overflow = 'hidden';

    // contentEditable 模式下 <a> 链接不可点击，需要手动委托
    content.addEventListener('click', (e) => {
      const target = (e.target as HTMLElement).closest('a') as HTMLAnchorElement | null;
      if (target && target.href) {
        e.preventDefault();
        window.open(target.href, '_blank');
      }
    });

    // Auto-save on edit
    content.addEventListener('input', () => { if (suppressInput) return; saveContent(); scheduleRefresh(); });
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
      '#' + CONTENT_ID + ' .callout { border-left:4px solid ' + (dark ? '#34d399' : '#16a34a') + '; border-radius:6px; padding:12px 16px; margin:16px 0; color:' + (dark ? '#d1d5db' : '#1f2937') + '; font-style:normal; line-height:1.7; background:' + (dark ? '#2a2e37' : '#f0fdf4') + '; }',
      '#' + CONTENT_ID + ' .callout-red { border-left-color:' + (dark ? '#f87171' : '#dc2626') + '; background:' + (dark ? '#2a2025' : '#fef2f2') + '; }',
      '#' + CONTENT_ID + ' .callout-yellow { border-left-color:' + (dark ? '#fbbf24' : '#d97706') + '; background:' + (dark ? '#2a2820' : '#fffbeb') + '; }',
      '#' + CONTENT_ID + ' .callout-purple { border-left-color:' + (dark ? '#a78bfa' : '#7c3aed') + '; background:' + (dark ? '#252030' : '#f5f3ff') + '; }',
      '#' + CONTENT_ID + ' .callout-blue { border-left-color:' + (dark ? '#60a5fa' : '#2563eb') + '; background:' + (dark ? '#202530' : '#eff6ff') + '; }',
      '#' + CONTENT_ID + ' .doc-meta { background:' + (dark ? '#1f2937' : '#f9fafb') + '; border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + '; border-radius:8px; padding:12px 16px; margin:0 0 24px 0; color:' + (dark ? '#9ca3af' : '#6b7280') + '; font-size:14px; line-height:1.8; }',
      '#' + CONTENT_ID + ' .grid-layout { display:flex; gap:16px; margin:16px 0; }',
      '#' + CONTENT_ID + ' .grid-col { flex:1; min-width:0; }',
      '#' + CONTENT_ID + ' ul,#' + CONTENT_ID + ' ol { padding-left:24px; margin-bottom:1em; }',
      '#' + CONTENT_ID + ' ol { list-style:none; counter-reset:ol-counter; }',
      '#' + CONTENT_ID + ' ol > li { counter-increment:ol-counter; }',
      '#' + CONTENT_ID + ' ol > li::before { content:counter(ol-counter) "."; color:' + (dark ? '#34d399' : '#0d9488') + '; font-weight:600; margin-right:6px; margin-left:-24px; display:inline-block; width:18px; }',
      '#' + CONTENT_ID + ' li { margin-bottom:0.4em; }',
      '#' + CONTENT_ID + ' li.task-item { list-style:none; margin-left:-20px; }',
      '#' + CONTENT_ID + ' li.task-item.checked { color:' + (dark ? '#6b7280' : '#9ca3af') + '; text-decoration:line-through; }',
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
      '#' + CONTENT_ID + ' mark.anno-underline { background:transparent; border-bottom:2px solid currentColor; font-weight:400; }',
      '#' + CONTENT_ID + ' mark.anno-underline.anno-yellow { border-bottom-color:#ca8a04; }',
      '#' + CONTENT_ID + ' mark.anno-underline.anno-blue { border-bottom-color:#2563eb; }',
      '#' + CONTENT_ID + ' mark.anno-underline.anno-green { border-bottom-color:#16a34a; }',
      '#' + CONTENT_ID + ' mark.anno-underline.anno-pink { border-bottom-color:#db2777; }',
      '#' + CONTENT_ID + ' mark.anno-strike { background:transparent; text-decoration:line-through; text-decoration-color:#9ca3af; text-decoration-thickness:2px; font-weight:400; }',
      '#' + CONTENT_ID + ' mark.anno-bookmark { background:transparent; border-left:3px solid #ec4899; padding-left:4px; font-weight:400; }',
      '#' + CONTENT_ID + ' mark.anno-bookmark::before { content:"🔖"; font-size:11px; vertical-align:super; margin-right:2px; }',
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
