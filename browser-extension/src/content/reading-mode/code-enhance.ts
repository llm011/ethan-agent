// @ts-nocheck
/* eslint-disable */

  // ========== 代码块增强：语法高亮 + 复制 + 换行切换 ==========
  // highlight.js 由 vite 构建时用 esbuild 预打包成 IIFE，注入为全局变量 __hljs。
  // 此模块在 concat 顺序中位于 reader-overlay 之后、entry 之前。

  // GitHub 风格高亮主题（精简版，只保留常见 token 类型）
  const HLJS_DARK_CSS = `
#${CONTENT_ID} .hljs { color: #e2e4e8; background: transparent; }
#${CONTENT_ID} .hljs-comment, #${CONTENT_ID} .hljs-quote { color: #8b949e; font-style: italic; }
#${CONTENT_ID} .hljs-keyword, #${CONTENT_ID} .hljs-selector-tag, #${CONTENT_ID} .hljs-literal, #${CONTENT_ID} .hljs-section, #${CONTENT_ID} .hljs-link { color: #ff7b72; }
#${CONTENT_ID} .hljs-string, #${CONTENT_ID} .hljs-attr, #${CONTENT_ID} .hljs-template-tag, #${CONTENT_ID} .hljs-addition, #${CONTENT_ID} .hljs-meta .hljs-string { color: #a5d6ff; }
#${CONTENT_ID} .hljs-title, #${CONTENT_ID} .hljs-title.function_, #${CONTENT_ID} .hljs-name { color: #d2a8ff; }
#${CONTENT_ID} .hljs-number, #${CONTENT_ID} .hljs-symbol, #${CONTENT_ID} .hljs-bullet, #${CONTENT_ID} .hljs-variable, #${CONTENT_ID} .hljs-template-variable { color: #79c0ff; }
#${CONTENT_ID} .hljs-type, #${CONTENT_ID} .hljs-built_in, #${CONTENT_ID} .hljs-class .hljs-title { color: #ffa657; }
#${CONTENT_ID} .hljs-meta, #${CONTENT_ID} .hljs-deletion { color: #8b949e; }
#${CONTENT_ID} .hljs-regexp { color: #a5d6ff; }
#${CONTENT_ID} .hljs-attribute { color: #79c0ff; }
#${CONTENT_ID} .hljs-params { color: #e2e4e8; }
#${CONTENT_ID} .hljs-property { color: #79c0ff; }
`;

  const HLJS_LIGHT_CSS = `
#${CONTENT_ID} .hljs { color: #24292e; background: transparent; }
#${CONTENT_ID} .hljs-comment, #${CONTENT_ID} .hljs-quote { color: #6a737d; font-style: italic; }
#${CONTENT_ID} .hljs-keyword, #${CONTENT_ID} .hljs-selector-tag, #${CONTENT_ID} .hljs-literal, #${CONTENT_ID} .hljs-section, #${CONTENT_ID} .hljs-link { color: #d73a49; }
#${CONTENT_ID} .hljs-string, #${CONTENT_ID} .hljs-attr, #${CONTENT_ID} .hljs-template-tag, #${CONTENT_ID} .hljs-addition, #${CONTENT_ID} .hljs-meta .hljs-string { color: #032f62; }
#${CONTENT_ID} .hljs-title, #${CONTENT_ID} .hljs-title.function_, #${CONTENT_ID} .hljs-name { color: #6f42c1; }
#${CONTENT_ID} .hljs-number, #${CONTENT_ID} .hljs-symbol, #${CONTENT_ID} .hljs-bullet, #${CONTENT_ID} .hljs-variable, #${CONTENT_ID} .hljs-template-variable { color: #005cc5; }
#${CONTENT_ID} .hljs-type, #${CONTENT_ID} .hljs-built_in, #${CONTENT_ID} .hljs-class .hljs-title { color: #e36209; }
#${CONTENT_ID} .hljs-meta, #${CONTENT_ID} .hljs-deletion { color: #6a737d; }
#${CONTENT_ID} .hljs-regexp { color: #032f62; }
#${CONTENT_ID} .hljs-attribute { color: #005cc5; }
#${CONTENT_ID} .hljs-params { color: #24292e; }
#${CONTENT_ID} .hljs-property { color: #005cc5; }
`;

  // SVG 图标（与 web/desktop CodeBlock 使用的 lucide 图标一致）
  const ICON_COPY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const ICON_CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  const ICON_WRAP = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><path d="M3 12h15a3 3 0 0 1 0 6h-4"/><polyline points="16 16 14 18 16 20"/><line x1="3" y1="18" x2="10" y2="18"/></svg>';

  function enhanceCodeBlocks(container: HTMLElement, dark: boolean) {
    const codeBlocks = container.querySelectorAll('pre code');
    if (!codeBlocks.length) return;

    // 注入高亮主题 CSS
    injectHljsTheme(dark);

    codeBlocks.forEach((codeEl: HTMLElement) => {
      const pre = codeEl.parentElement;
      if (!pre || pre.tagName !== 'PRE') return;
      // 跳过已高亮的（如从缓存恢复时 innerHTML 已含高亮 span）
      if (codeEl.dataset.highlighted === 'yes') {
        addCodeToolbar(pre, codeEl, dark);
        return;
      }

      // 语法高亮
      if (typeof (self as any).__hljs !== 'undefined') {
        suppressInput = true;
        try { (self as any).__hljs.highlightElement(codeEl); } catch (e) { /* ignore */ }
        // 用微任务重置标志，确保 hljs 注入 span 触发的 input 事件被吞掉
        queueMicrotask(() => { suppressInput = false; });
      }

      // 工具栏
      addCodeToolbar(pre, codeEl, dark);
    });
  }

  function injectHljsTheme(dark: boolean) {
    const id = '__ethan_hljs_theme';
    if (document.getElementById(id)) return;
    const style = document.createElement('style');
    style.id = id;
    style.textContent = dark ? HLJS_DARK_CSS : HLJS_LIGHT_CSS;
    document.head.appendChild(style);
  }

  function addCodeToolbar(pre: HTMLElement, codeEl: HTMLElement, dark: boolean) {
    // 避免重复添加
    if (pre.parentElement && pre.parentElement.dataset.codeWrapper === 'yes') return;

    const wrapper = document.createElement('div');
    wrapper.dataset.codeWrapper = 'yes';
    Object.assign(wrapper.style, {
      position: 'relative' as const,
      margin: '16px 0',
    });

    pre.parentElement!.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);

    // 工具栏容器
    const toolbar = document.createElement('div');
    Object.assign(toolbar.style, {
      position: 'absolute' as const,
      right: '8px',
      top: '8px',
      zIndex: '10',
      display: 'flex' as const,
      gap: '4px',
      opacity: '0',
      transition: 'opacity 0.15s',
    });
    wrapper.onmouseenter = () => { toolbar.style.opacity = '1'; };
    wrapper.onmouseleave = () => { toolbar.style.opacity = '0'; };

    // 换行切换
    const wrapBtn = createToolbarBtn(dark, ICON_WRAP, '切换换行');
    wrapBtn.onclick = () => {
      const wrapped = pre.dataset.wrapped === 'yes';
      if (wrapped) {
        pre.style.whiteSpace = 'pre';
        pre.style.overflowX = 'auto';
        pre.style.wordBreak = 'normal';
        pre.dataset.wrapped = 'no';
      } else {
        pre.style.whiteSpace = 'pre-wrap';
        pre.style.overflowX = 'hidden';
        pre.style.wordBreak = 'break-all';
        pre.dataset.wrapped = 'yes';
      }
    };
    toolbar.appendChild(wrapBtn);

    // 复制
    const copyBtn = createToolbarBtn(dark, ICON_COPY, '复制代码');
    copyBtn.onclick = async () => {
      const text = codeEl.textContent || '';
      try {
        await navigator.clipboard.writeText(text);
        copyBtn.innerHTML = ICON_CHECK;
        copyBtn.style.color = '#4ade80';
        setTimeout(() => { copyBtn.innerHTML = ICON_COPY; copyBtn.style.color = ''; }, 2000);
      } catch (e) {
        // fallback: 选中文本
        const range = document.createRange();
        range.selectNodeContents(codeEl);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(range);
      }
    };
    toolbar.appendChild(copyBtn);

    wrapper.appendChild(toolbar);
  }

  function createToolbarBtn(dark: boolean, iconHtml: string, title: string): HTMLElement {
    const btn = document.createElement('button');
    btn.innerHTML = iconHtml;
    btn.title = title;
    Object.assign(btn.style, {
      border: 'none',
      borderRadius: '4px',
      padding: '4px',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: dark ? 'rgba(55,65,81,0.8)' : 'rgba(0,0,0,0.06)',
      color: dark ? '#d1d5db' : '#4b5563',
      transition: 'background 0.1s, color 0.1s',
      lineHeight: '0',
    });
    btn.onmouseenter = () => { btn.style.background = dark ? 'rgba(75,85,99,0.9)' : 'rgba(0,0,0,0.12)'; };
    btn.onmouseleave = () => { btn.style.background = dark ? 'rgba(55,65,81,0.8)' : 'rgba(0,0,0,0.06)'; };
    return btn;
  }
