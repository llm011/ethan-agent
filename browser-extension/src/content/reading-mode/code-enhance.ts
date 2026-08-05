// @ts-nocheck
/* eslint-disable */

  // ========== 代码块增强：语法高亮 + 行号 + 复制 + 换行切换 ==========
  // highlight.js 由 vite 构建时用 esbuild 预打包成 IIFE，注入为全局变量 __hljs。

  const CODE_FONT = "'SF Mono', Menlo, Monaco, 'Cascadia Code', Consolas, 'Liberation Mono', 'Courier New', monospace";

  // ---------- 主题 CSS ----------
  // 暗色（GitHub Dark + 精致细节）
  const CODE_DARK_CSS = `
#${CONTENT_ID} .code-wrapper {
  margin: 18px 0;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #30363d;
  box-shadow:
    0 6px 18px rgba(0,0,0,0.38),
    0 1px 0 rgba(255,255,255,0.04) inset,
    0 -1px 0 rgba(0,0,0,0.2) inset;
  background: #0d1117;
  position: relative;
}
#${CONTENT_ID} .code-wrapper::before {
  content: "";
  position: absolute; left: 0; right: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, rgba(88,166,255,0.0), rgba(88,166,255,0.35), rgba(210,153,34,0.25), rgba(88,166,255,0.0));
  pointer-events: none; z-index: 2;
}
#${CONTENT_ID} .code-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 14px; height: 38px;
  background: linear-gradient(180deg, #1c2129 0%, #161b22 100%);
  border-bottom: 1px solid #21262d;
}
#${CONTENT_ID} .code-header-left {
  display: flex; align-items: center; gap: 10px; min-width: 0;
}
#${CONTENT_ID} .code-dots {
  display: flex; gap: 6px; align-items: center;
  padding: 2px 0;
}
#${CONTENT_ID} .code-dot {
  width: 11px; height: 11px; border-radius: 50%;
  box-shadow: 0 0 0 0.5px rgba(0,0,0,0.4) inset;
}
#${CONTENT_ID} .code-dot.red   { background: #ff5f56; }
#${CONTENT_ID} .code-dot.yellow{ background: #ffbd2e; }
#${CONTENT_ID} .code-dot.green { background: #27c93f; }
#${CONTENT_ID} .code-lang {
  font-family: ${CODE_FONT}; font-size: 11px; font-weight: 600;
  color: #8b949e; letter-spacing: 0.5px; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#${CONTENT_ID} .code-toolbar { display: flex; gap: 2px; align-items: center; }
#${CONTENT_ID} .code-body { position: relative; background: #0d1117; }
#${CONTENT_ID} .code-gutter {
  position: absolute; left: 0; top: 0; bottom: 0;
  box-sizing: border-box;
  padding: 14px 10px 14px 10px; text-align: right;
  min-width: 40px;
  color: #484f58; font-family: ${CODE_FONT}; font-size: 12.5px; line-height: 1.6;
  user-select: none; pointer-events: none;
  background: #0a0e14;
  border-right: 1px solid #21262d;
  white-space: pre; z-index: 1;
}
#${CONTENT_ID} .code-wrapper pre {
  margin: 0 !important;
  background: transparent !important; border-radius: 0 !important;
  font-size: 12.5px !important; line-height: 1.6 !important;
  font-family: ${CODE_FONT} !important;
  color: #c9d1d9; border: none !important;
  overflow-x: auto !important;
}
#${CONTENT_ID} .code-wrapper pre code {
  padding: 0 !important; background: none !important;
  font-size: inherit !important; font-family: inherit !important;
  color: inherit; border-radius: 0 !important;
}
#${CONTENT_ID} .code-wrapper pre code.hljs { background: transparent; }
#${CONTENT_ID} .code-btn {
  border: none; border-radius: 6px;
  padding: 6px 7px;
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  background: rgba(110,118,129,0.1);
  color: #8b949e;
  transition: background 0.12s ease, color 0.12s ease;
  line-height: 0;
}
#${CONTENT_ID} .code-btn:hover { background: rgba(110,118,129,0.25); color: #e6edf3; }
#${CONTENT_ID} .code-btn:active { background: rgba(110,118,129,0.4); transform: translateY(0.5px); }
#${CONTENT_ID} .code-btn.copied { background: rgba(63,185,80,0.12); color: #3fb950; }
#${CONTENT_ID} .code-btn.wrap-on  { background: rgba(88,166,255,0.14); color: #58a6ff; }
/* hljs (GitHub Dark) */
#${CONTENT_ID} .hljs { color: #c9d1d9; background: transparent; }
#${CONTENT_ID} .hljs-comment, #${CONTENT_ID} .hljs-quote { color: #8b949e; font-style: italic; }
#${CONTENT_ID} .hljs-keyword, #${CONTENT_ID} .hljs-selector-tag, #${CONTENT_ID} .hljs-literal, #${CONTENT_ID} .hljs-section, #${CONTENT_ID} .hljs-link { color: #ff7b72; }
#${CONTENT_ID} .hljs-string, #${CONTENT_ID} .hljs-attr, #${CONTENT_ID} .hljs-template-tag, #${CONTENT_ID} .hljs-addition, #${CONTENT_ID} .hljs-meta .hljs-string { color: #a5d6ff; }
#${CONTENT_ID} .hljs-title, #${CONTENT_ID} .hljs-title.function_, #${CONTENT_ID} .hljs-name { color: #d2a8ff; }
#${CONTENT_ID} .hljs-number, #${CONTENT_ID} .hljs-symbol, #${CONTENT_ID} .hljs-bullet, #${CONTENT_ID} .hljs-variable, #${CONTENT_ID} .hljs-template-variable { color: #79c0ff; }
#${CONTENT_ID} .hljs-type, #${CONTENT_ID} .hljs-built_in, #${CONTENT_ID} .hljs-class .hljs-title { color: #ffa657; }
#${CONTENT_ID} .hljs-meta, #${CONTENT_ID} .hljs-deletion { color: #8b949e; }
#${CONTENT_ID} .hljs-regexp { color: #a5d6ff; }
#${CONTENT_ID} .hljs-attribute { color: #79c0ff; }
#${CONTENT_ID} .hljs-params { color: #c9d1d9; }
#${CONTENT_ID} .hljs-property { color: #79c0ff; }
#${CONTENT_ID} .hljs-tag { color: #7ee787; }
#${CONTENT_ID} .hljs-title.class_, #${CONTENT_ID} .hljs-class .hljs-title { color: #ffa657; }
`;

  // 亮色
  const CODE_LIGHT_CSS = `
#${CONTENT_ID} .code-wrapper {
  margin: 18px 0;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #d0d7de;
  box-shadow:
    0 1px 3px rgba(31,35,40,0.08),
    0 10px 28px rgba(31,35,40,0.06);
  background: #ffffff;
  position: relative;
}
#${CONTENT_ID} .code-wrapper::before {
  content: "";
  position: absolute; left: 0; right: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, rgba(9,105,218,0.0), rgba(9,105,218,0.25), rgba(149,56,0,0.18), rgba(9,105,218,0.0));
  pointer-events: none; z-index: 2;
}
#${CONTENT_ID} .code-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 14px; height: 38px;
  background: linear-gradient(180deg, #fafbfc 0%, #f2f4f7 100%);
  border-bottom: 1px solid #d0d7de;
}
#${CONTENT_ID} .code-header-left {
  display: flex; align-items: center; gap: 10px; min-width: 0;
}
#${CONTENT_ID} .code-dots {
  display: flex; gap: 6px; align-items: center;
  padding: 2px 0;
}
#${CONTENT_ID} .code-dot {
  width: 11px; height: 11px; border-radius: 50%;
  box-shadow: 0 0 0 0.5px rgba(0,0,0,0.08) inset;
}
#${CONTENT_ID} .code-dot.red   { background: #ff5f56; }
#${CONTENT_ID} .code-dot.yellow{ background: #ffbd2e; }
#${CONTENT_ID} .code-dot.green { background: #27c93f; }
#${CONTENT_ID} .code-lang {
  font-family: ${CODE_FONT}; font-size: 11px; font-weight: 600;
  color: #636c76; letter-spacing: 0.5px; text-transform: uppercase;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#${CONTENT_ID} .code-toolbar { display: flex; gap: 2px; align-items: center; }
#${CONTENT_ID} .code-body { position: relative; background: #ffffff; }
#${CONTENT_ID} .code-gutter {
  position: absolute; left: 0; top: 0; bottom: 0;
  box-sizing: border-box;
  padding: 14px 10px 14px 10px; text-align: right;
  min-width: 40px;
  color: #8c959f; font-family: ${CODE_FONT}; font-size: 12.5px; line-height: 1.6;
  user-select: none; pointer-events: none;
  background: #f6f8fa;
  border-right: 1px solid #d0d7de;
  white-space: pre; z-index: 1;
}
#${CONTENT_ID} .code-wrapper pre {
  margin: 0 !important;
  background: transparent !important; border-radius: 0 !important;
  font-size: 12.5px !important; line-height: 1.6 !important;
  font-family: ${CODE_FONT} !important;
  color: #24292f; border: none !important;
  overflow-x: auto !important;
}
#${CONTENT_ID} .code-wrapper pre code {
  padding: 0 !important; background: none !important;
  font-size: inherit !important; font-family: inherit !important;
  color: inherit; border-radius: 0 !important;
}
#${CONTENT_ID} .code-wrapper pre code.hljs { background: transparent; }
#${CONTENT_ID} .code-btn {
  border: none; border-radius: 6px;
  padding: 6px 7px;
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  background: rgba(175,184,193,0.18);
  color: #636c76;
  transition: background 0.12s ease, color 0.12s ease, transform 0.05s ease;
  line-height: 0;
}
#${CONTENT_ID} .code-btn:hover { background: rgba(175,184,193,0.4); color: #1f2328; }
#${CONTENT_ID} .code-btn:active { background: rgba(175,184,193,0.55); transform: translateY(0.5px); }
#${CONTENT_ID} .code-btn.copied { background: rgba(26,127,55,0.12); color: #1a7f37; }
#${CONTENT_ID} .code-btn.wrap-on  { background: rgba(9,105,218,0.1); color: #0969da; }
/* hljs (GitHub Light) */
#${CONTENT_ID} .hljs { color: #24292f; background: transparent; }
#${CONTENT_ID} .hljs-comment, #${CONTENT_ID} .hljs-quote { color: #6e7781; font-style: italic; }
#${CONTENT_ID} .hljs-keyword, #${CONTENT_ID} .hljs-selector-tag, #${CONTENT_ID} .hljs-literal, #${CONTENT_ID} .hljs-section, #${CONTENT_ID} .hljs-link { color: #cf222e; }
#${CONTENT_ID} .hljs-string, #${CONTENT_ID} .hljs-attr, #${CONTENT_ID} .hljs-template-tag, #${CONTENT_ID} .hljs-addition, #${CONTENT_ID} .hljs-meta .hljs-string { color: #0a3069; }
#${CONTENT_ID} .hljs-title, #${CONTENT_ID} .hljs-title.function_, #${CONTENT_ID} .hljs-name { color: #8250df; }
#${CONTENT_ID} .hljs-number, #${CONTENT_ID} .hljs-symbol, #${CONTENT_ID} .hljs-bullet, #${CONTENT_ID} .hljs-variable, #${CONTENT_ID} .hljs-template-variable { color: #0550ae; }
#${CONTENT_ID} .hljs-type, #${CONTENT_ID} .hljs-built_in, #${CONTENT_ID} .hljs-class .hljs-title { color: #953800; }
#${CONTENT_ID} .hljs-meta, #${CONTENT_ID} .hljs-deletion { color: #6e7781; }
#${CONTENT_ID} .hljs-regexp { color: #0a3069; }
#${CONTENT_ID} .hljs-attribute { color: #0550ae; }
#${CONTENT_ID} .hljs-params { color: #24292f; }
#${CONTENT_ID} .hljs-property { color: #0550ae; }
#${CONTENT_ID} .hljs-tag { color: #116329; }
#${CONTENT_ID} .hljs-title.class_, #${CONTENT_ID} .hljs-class .hljs-title { color: #953800; }
`;

  // ---------- SVG 图标 ----------
  const ICON_COPY = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2.5" ry="2.5"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  const ICON_CHECK = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  const ICON_WRAP = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="6" x2="21" y2="6"/><path d="M3 12h15a3 3 0 0 1 0 6h-4"/><polyline points="16 16 14 18 16 20"/><line x1="3" y1="18" x2="10" y2="18"/></svg>';

  // ---------- 入口 ----------
  /** 代码脏行清理：对付一些博客/文档站会把"复制代码/代码解读/代码展开"这类按钮文字或语言标签
   *  通过 div/span/text 混进 <code> 内部（不是 <pre> 的兄弟，而是 <code> 的直系文本节点/子元素）。
   *  这一步在 highlight 之前做，改 <code> 的 innerHTML 后 hljs.highlightElement 仍能跑。
   *
   *  启发式（保守）：
   *  1) 以"整行"为单位匹配按钮文字。文字里不允许有代码字符（ASCII 可打印里的运算符/标点/数字/引号都少），
   *     只允许常见的 2~6 个中文汉字/英文单词（"复制代码"、"代码解读"、"Copy code"、"Copy"、"复制"、"展开代码"、"折叠代码"等）。
   *  2) 行首出现 `}<1-16 个纯字母>`（例如 `}css`、`}javascript`、`}scss`）这种"闭合大括号 + 语言名"，
   *     几乎可以肯定是上一段代码闭合字符 + 被塞在 code 开头的语言标签 span 粘到了一行——清理掉。
   *  3) 行首/行尾单独出现形如 `css` / `javascript` 这种纯字母、长度 <=16 的语言名（与 detectLang 同一行的语言标签），
   *     如果这一行没有任何其他代码字符（空格/tab/换行之外没有别的东西），删掉。
   */
  function sanitizeCodeContent(codeEl: HTMLElement) {
    // 用 innerText 拿到行（考虑 <br>/块级元素的可视换行），再按可视换行拆分，把脏行从 DOM 里删掉。
    // 为了避免误伤真正的代码（比如某一行恰好就是注释 "// 复制代码"），我们额外要求：脏行必须"完全不含 ASCII 可打印代码字符"。
    const raw = codeEl.innerText || '';
    const lines = raw.replace(/\n$/, '').split('\n');
    if (!lines.length) return;

    // 常见代码块按钮/标签文字（中英文）——整行完全匹配其中之一就删掉。
    const BUTTON_WHOLE_LINE = new Set([
      '复制代码', '复制', '拷贝代码', '拷贝',
      '代码解读', '代码解释', '代码注释',
      '展开代码', '展开', '查看全部', '查看完整代码',
      '折叠代码', '折叠',
      'Copy code', 'Copy', 'COPY CODE', 'COPY',
      '复制到剪贴板', '复制到剪切板', '复制至剪贴板',
      '在线运行', '运行代码', 'Playground', 'PLAYGROUND',
    ]);

    // 语言名识别（和 detectLang 里 language- 后出现的字符串集合近似）。
    // 用于行"单独就是一个语言名"的情况（语言标签栏被吸进 code）。
    const COMMON_LANG = new Set([
      'js', 'javascript', 'ts', 'typescript',
      'css', 'scss', 'sass', 'less', 'html', 'xml', 'vue', 'svelte',
      'py', 'python', 'rb', 'ruby', 'php', 'java', 'kt', 'kotlin', 'go', 'rust', 'rs',
      'c', 'cpp', 'cxx', 'h', 'hpp', 'cs', 'csharp', 'swift', 'oc', 'objc',
      'sh', 'bash', 'shell', 'zsh', 'fish', 'ps', 'powershell', 'cmd', 'bat',
      'sql', 'mysql', 'pgsql', 'sqlite', 'json', 'yaml', 'yml', 'toml', 'ini',
      'md', 'markdown', 'tex', 'latex', 'lua', 'r', 'dart', 'scala', 'perl',
      'wasm', 'wat', 'dockerfile', 'makefile', 'nginx', 'vim', 'diff', 'patch',
    ]);

    // 判断一行是不是"非代码"：长度 <=24 且整行没有 ASCII 代码字符集合。
    // 允许的字符仅为：CJK 汉字/字母/空格/tab；一旦出现 !@#$%^&*()_+-=[]{}|;':",./<>? 或数字，就认为是代码行不删。
    const reNonCodeLine = /^[\s\u4e00-\u9fa5A-Za-z·]{0,24}$/;
    const isNonCodeLine = (s: string) => reNonCodeLine.test(s.trim());

    const dirtyIdx = new Set<number>();
    lines.forEach((rawLine, i) => {
      const line = rawLine.trim();
      if (!line) return;
      // 1) 按钮整行匹配
      if (BUTTON_WHOLE_LINE.has(line) && isNonCodeLine(line)) {
        dirtyIdx.add(i);
        return;
      }
      // 2) 首行：} + 语言名（无空格，纯字母）
      if (i === 0) {
        const m = line.match(/^}\s*([A-Za-z]{1,16})$/);
        if (m && COMMON_LANG.has(m[1].toLowerCase())) {
          dirtyIdx.add(i);
          return;
        }
      }
      // 3) 单独的语言名行（没有其他字符），出现在代码首行或末行才删（中间行比如 "sql" 可能是真的 SQL 语句）
      if ((i === 0 || i === lines.length - 1) && line.length <= 16 && /^[A-Za-z]+$/.test(line)) {
        if (COMMON_LANG.has(line.toLowerCase())) {
          dirtyIdx.add(i);
          return;
        }
      }
    });

    if (!dirtyIdx.size) return;

    // 应用删除：用 line 索引和 visual 换行对齐比较难（因为 innerText 换行源可能是 <br> 或块元素闭合），
    // 这里走更简单的做法——直接把 codeEl.textContent 按行重建，再用 splitText/append/prepend 调整文本节点。
    // 不过 codeEl 里可能已经有 hljs 的 span（本函数在 highlight 前调用，所以应该没有），所以直接处理 innerText 重建就够了：
    // 逐行保留，最后用 "\n" join 回去，塞回 codeEl 纯文本。
    // 代价：如果 <code> 里本身就含有"非 <span> 高亮用的其他 DOM 结构"（比如 <a>、<em> 等）会丢失——现实中 <code> 里不会放这些，丢失无影响。
    const kept = lines.filter((_, i) => !dirtyIdx.has(i));
    suppressInput = true;
    try {
      codeEl.textContent = kept.join('\n');
    } finally {
      queueMicrotask(() => { suppressInput = false; });
    }
  }

  function enhanceCodeBlocks(container: HTMLElement, dark: boolean) {
    const codeBlocks = container.querySelectorAll('pre code');
    if (!codeBlocks.length) return;

    injectCodeTheme(dark);

    codeBlocks.forEach((codeEl: HTMLElement) => {
      const pre = codeEl.parentElement;
      if (!pre || pre.tagName !== 'PRE') return;
      // 缓存恢复时：把旧 wrapper 剥离，重绑事件
      const oldWrapper = pre.closest('.code-wrapper');
      if (oldWrapper) {
        oldWrapper.parentElement!.insertBefore(pre, oldWrapper);
        oldWrapper.remove();
      }

      // 先做内容清洗（脏行：按钮文字/语言标签），再高亮——顺序很重要，高亮后再改 textContent 会把 span 色丢了。
      sanitizeCodeContent(codeEl);

      if (codeEl.dataset.highlighted !== 'yes' && typeof (self as any).__hljs !== 'undefined') {
        suppressInput = true;
        try {
          (self as any).__hljs.highlightElement(codeEl);
          codeEl.dataset.highlighted = 'yes';
        } catch (e) { /* ignore */ }
        queueMicrotask(() => { suppressInput = false; });
      }

      wrapCodeBlock(pre, codeEl);
    });
  }

  function injectCodeTheme(dark: boolean) {
    const id = '__ethan_code_theme';
    const existing = document.getElementById(id) as HTMLStyleElement | null;
    if (existing) {
      existing.textContent = dark ? CODE_DARK_CSS : CODE_LIGHT_CSS;
      return;
    }
    const style = document.createElement('style');
    style.id = id;
    style.textContent = dark ? CODE_DARK_CSS : CODE_LIGHT_CSS;
    document.head.appendChild(style);
  }

  // ---------- 包装代码块 ----------
  function wrapCodeBlock(pre: HTMLElement, codeEl: HTMLElement) {
    const wrapper = document.createElement('div');
    wrapper.className = 'code-wrapper';
    (wrapper as any).contentEditable = 'false';

    pre.parentElement!.insertBefore(wrapper, pre);

    // --- Header ---
    const header = document.createElement('div');
    header.className = 'code-header';

    const headerLeft = document.createElement('div');
    headerLeft.className = 'code-header-left';

    // 红黄绿三个小圆点（mac 风格）
    const dots = document.createElement('div');
    dots.className = 'code-dots';
    ['red', 'yellow', 'green'].forEach(c => {
      const d = document.createElement('span');
      d.className = 'code-dot ' + c;
      dots.appendChild(d);
    });
    headerLeft.appendChild(dots);

    // 语言名
    const langSpan = document.createElement('span');
    langSpan.className = 'code-lang';
    langSpan.textContent = detectLang(codeEl);
    headerLeft.appendChild(langSpan);

    const toolbar = document.createElement('div');
    toolbar.className = 'code-toolbar';

    header.appendChild(headerLeft);
    header.appendChild(toolbar);

    // --- Body: gutter + pre ---
    const body = document.createElement('div');
    body.className = 'code-body';

    const gutter = document.createElement('div');
    gutter.className = 'code-gutter';
    // 防止 contentEditable 点击 gutter 区域时光标跳行
    (gutter as any).contentEditable = 'false';

    body.appendChild(gutter);
    body.appendChild(pre);
    wrapper.appendChild(header);
    wrapper.appendChild(body);

    // 行号（并返回 gutter 总渲染宽度 border-box，用来同步 pre padding）
    const gutterWidth = rebuildGutter(codeEl, gutter);

    // pre padding-left = gutter 总宽 (含 border) + 12px 间距
    const codePadLeft = gutterWidth + 12;
    pre.style.padding = '14px 16px 14px ' + codePadLeft + 'px';

    // --- 工具栏按钮 ---
    const wrapBtn = createBtn(ICON_WRAP, '切换换行');
    const copyBtn = createBtn(ICON_COPY, '复制代码');

    // 换行切换
    let wrapped = false;
    wrapBtn.addEventListener('mousedown', (e) => e.preventDefault());
    wrapBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      wrapped = !wrapped;
      if (wrapped) {
        pre.style.whiteSpace = 'pre-wrap';
        pre.style.wordBreak = 'break-word';
        pre.style.overflowX = 'hidden';
        gutter.style.display = 'none';
        pre.style.paddingLeft = '16px';
        wrapBtn.classList.add('wrap-on');
      } else {
        pre.style.whiteSpace = 'pre';
        pre.style.wordBreak = 'normal';
        pre.style.overflowX = 'auto';
        gutter.style.display = '';
        pre.style.paddingLeft = codePadLeft + 'px';
        wrapBtn.classList.remove('wrap-on');
      }
    });

    // 复制
    copyBtn.addEventListener('mousedown', (e) => e.preventDefault());
    copyBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const text = codeEl.textContent || '';
      // 1. 用 textarea + execCommand (在 content script DOM 中可靠工作)
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      document.execCommand('copy');
      ta.remove();
      // 视觉反馈
      copyBtn.innerHTML = ICON_CHECK;
      copyBtn.classList.add('copied');
      setTimeout(() => {
        copyBtn.innerHTML = ICON_COPY;
        copyBtn.classList.remove('copied');
      }, 1800);
    });

    toolbar.appendChild(wrapBtn);
    toolbar.appendChild(copyBtn);

    // 编辑时同步行号（debounce）
    let gutterTimer: number | null = null;
    const mo = new MutationObserver(() => {
      if (suppressInput) return;
      if (gutterTimer) clearTimeout(gutterTimer);
      gutterTimer = window.setTimeout(() => {
        if (!pre.isConnected) return;
        const newW = rebuildGutter(codeEl, gutter);
        if (!wrapped) pre.style.paddingLeft = (newW + 12) + 'px';
      }, 220);
    });
    mo.observe(codeEl, { childList: true, characterData: true, subtree: true });
  }

  // ---------- 行号生成 ----------
  function rebuildGutter(codeEl: HTMLElement, gutter: HTMLElement): number {
    // innerText 能正确反映可视换行（<br>、block 元素），textContent 不行
    const text = codeEl.innerText || '';
    const lines = text.replace(/\n$/, '').split('\n');
    const lineCount = lines.length;
    // border-box: width = padding-left(10) + 数字内容 + padding-right(10) + border-right(1)
    const digitContentW = Math.max(14, String(lineCount).length * 9);
    const totalWidth = 10 + digitContentW + 10 + 1; // pad-L + content + pad-R + border
    gutter.style.width = totalWidth + 'px';
    let nums = '';
    for (let i = 1; i <= lineCount; i++) nums += i + '\n';
    gutter.textContent = nums;
    return totalWidth;
  }

  // ---------- 语言检测 ----------
  function detectLang(codeEl: HTMLElement): string {
    const cls = codeEl.className || '';
    const m = cls.match(/language-([\w+-]+)/);
    if (m) return m[1].toLowerCase();
    const m2 = (codeEl.parentElement?.className || '').match(/language-([\w+-]+)/);
    if (m2) return m2[1].toLowerCase();
    return 'text';
  }

  // ---------- 工具栏按钮 ----------
  function createBtn(iconHtml: string, title: string): HTMLElement {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'code-btn';
    btn.innerHTML = iconHtml;
    btn.title = title;
    return btn;
  }
