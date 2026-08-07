// @ts-nocheck
/* eslint-disable */

  // ========== Enter / Exit ==========

  /** Markdown 快速转 HTML（给飞书文档全文用：reader-extract 只处理 DOM，纯 Markdown 需要本地渲染）。
   * 用 result-panel.ts 的精简版：标题 / 加粗 / 斜体 / 行内代码 / 无序列表 / 表格 / 换行。 */
  function mdToHtml(md: string): string {
    const lines = md.replace(/\r\n?/g, '\n').split('\n');
    const out: string[] = [];
    let inUl = false;
    let inOl = false;
    let inCode = false;
    let inHtmlBlock = '';
    let htmlBlockBuf: string[] = [];
    let htmlBlockDepth = 0;
    let codeLang = '';
    let codeBuf: string[] = [];
    let tableBuf: string[] = [];
    const closeLists = () => {
      if (inUl) { out.push('</ul>'); inUl = false; }
      if (inOl) { out.push('</ol>'); inOl = false; }
    };
    const flushTable = () => {
      if (!tableBuf.length) return;
      // 简化：所有行都当 <tr><td>...</td></tr>，保留格式
      out.push('<table>');
      tableBuf.forEach((row, i) => {
        const cells = row.split('|').filter((c, idx, arr) => {
          // 丢弃开头 / 结尾的空字符串（由首尾的 | 产生）
          if (idx === 0 && !c.trim()) return false;
          if (idx === arr.length - 1 && !c.trim()) return false;
          return true;
        }).map(c => c.trim());
        if (i === 1 && cells.every(c => /^:?-+:?$/.test(c))) return;  // 表格对齐行
        const tag = i === 0 ? 'th' : 'td';
        out.push('<tr>' + cells.map(c => `<${tag}>${inline(escapeHtml(c))}</${tag}>`).join('') + '</tr>');
      });
      out.push('</table>');
      tableBuf = [];
    };

    function inline(s: string): string {
      // 行内代码：`xxx`
      s = s.replace(/`([^`]+)`/g, (_m, c) => `<code>${c}</code>`);
      // 加粗：**xxx**
      s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
      // 斜体：*xxx*（注意与 ** 的冲突：粗体已处理过）
      s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
      // 链接：[text](url)
      s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
      // 图片：![alt](url)
      s = s.replace(/!\[([^\]]*)\]\((https?:\/\/[^)\s]+)\)/g, '<img alt="$1" src="$2" />');
      return s;
    }

    for (const rawLine of lines) {
      const line = rawLine.trimEnd();
      // HTML 块透传：遇到 <table/<grid/<blockquote 开始收集，遇到对应闭合标签结束
      if (inHtmlBlock) {
        htmlBlockBuf.push(rawLine);
        const openRe = new RegExp(`<${inHtmlBlock}[\\s>]`, 'gi');
        const closeRe = new RegExp(`</${inHtmlBlock}\\s*>`, 'gi');
        htmlBlockDepth += (line.match(openRe) || []).length - (line.match(closeRe) || []).length;
        if (htmlBlockDepth <= 0) {
          inHtmlBlock = '';
          out.push(htmlBlockBuf.join('\n'));
          htmlBlockBuf = [];
        }
        continue;
      }
      const htmlBlockMatch = line.match(/^<(table|grid|blockquote|div)[\s>]/i);
      if (htmlBlockMatch) {
        closeLists(); flushTable();
        inHtmlBlock = htmlBlockMatch[1].toLowerCase();
        htmlBlockBuf = [rawLine];
        const openRe = new RegExp(`<${inHtmlBlock}[\\s>]`, 'gi');
        const closeRe = new RegExp(`</${inHtmlBlock}\\s*>`, 'gi');
        htmlBlockDepth = (line.match(openRe) || []).length - (line.match(closeRe) || []).length;
        if (htmlBlockDepth <= 0) {
          out.push(htmlBlockBuf.join('\n'));
          inHtmlBlock = '';
          htmlBlockBuf = [];
        }
        continue;
      }
      if (inCode) {
        if (/^```\s*$/.test(line)) {
          inCode = false;
          // 去掉收集内容的首尾空行，拼成整块
          while (codeBuf.length && codeBuf[0].trim() === '') codeBuf.shift();
          while (codeBuf.length && codeBuf[codeBuf.length - 1].trim() === '') codeBuf.pop();
          out.push(`<pre><code${codeLang ? ` class="language-${codeLang}"` : ''}>${codeBuf.join('\n')}</code></pre>`);
          codeBuf = [];
          continue;
        }
        codeBuf.push(escapeHtml(line));
        continue;
      }
      const fence = line.match(/^```(.*)$/);
      if (fence) {
        closeLists(); flushTable();
        inCode = true; codeLang = fence[1].trim().split(/\s+/)[0].toLowerCase() || '';
        codeBuf = [];
        continue;
      }
      // 表格行
      if (/^\|.*\|\s*$/.test(line) && line.includes('|')) {
        closeLists();
        tableBuf.push(line);
        continue;
      } else {
        flushTable();
      }
      // 标题
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeLists();
        const level = h[1].length;
        out.push(`<h${level}>${inline(escapeHtml(h[2]))}</h${level}>`);
        continue;
      }
      // 引用（连续 > 行合并为同一个 blockquote）
      if (/^>\s?/.test(line)) {
        closeLists();
        const bqLines: string[] = [line.replace(/^>\s?/, '')];
        // 向前看：后续连续引用行一起收集（rawLine 数组已经通过 for-of 遍历，这里用 peek 方式不行，
        // 改为在 out 里检测上一个元素是否是未关闭的 blockquote 来追加）
        const last = out[out.length - 1];
        if (last && last.startsWith('<blockquote>') && last.endsWith('</blockquote>')) {
          // 追加到上一个 blockquote
          const inner = last.slice('<blockquote>'.length, -'</blockquote>'.length);
          out[out.length - 1] = `<blockquote>${inner}<br/>${inline(escapeHtml(bqLines[0]))}</blockquote>`;
        } else {
          out.push(`<blockquote>${inline(escapeHtml(bqLines[0]))}</blockquote>`);
        }
        continue;
      }
      // 无序列表（含 checkbox）
      if (/^[-*+]\s+/.test(line)) {
        if (inOl) { out.push('</ol>'); inOl = false; }
        if (!inUl) { out.push('<ul>'); inUl = true; }
        const stripped = line.replace(/^[-*+]\s+/, '');
        const cbMatch = stripped.match(/^\[([ xX])\]\s*(.*)/);
        if (cbMatch) {
          const checked = cbMatch[1] !== ' ';
          const icon = checked ? '☑' : '☐';
          out.push(`<li class="task-item${checked ? ' checked' : ''}">${icon} ${inline(escapeHtml(cbMatch[2]))}</li>`);
        } else {
          out.push(`<li>${inline(escapeHtml(stripped))}</li>`);
        }
        continue;
      }
      // 有序列表
      const ol = line.match(/^\d+\.\s+(.*)$/);
      if (ol) {
        if (inUl) { out.push('</ul>'); inUl = false; }
        if (!inOl) { out.push('<ol>'); inOl = true; }
        out.push(`<li>${inline(escapeHtml(ol[1]))}</li>`);
        continue;
      }
      // hr
      if (/^\s*(---\s*|___\s*|\*\*\*\s*)$/.test(line)) {
        closeLists(); out.push('<hr/>'); continue;
      }
      closeLists();
      if (!line.trim()) {
        // 空行发出段落分隔，避免相邻 blockquote 被合并成一个；
        // 连续空行不叠加，只保留一个分隔。
        if (out[out.length - 1] !== '<p class="sep"></p>') {
          out.push('<p class="sep"></p>');
        }
        continue;
      }
      out.push(`<p>${inline(escapeHtml(line))}</p>`);
    }
    flushTable(); closeLists();
    if (inCode) {
      while (codeBuf.length && codeBuf[0].trim() === '') codeBuf.shift();
      while (codeBuf.length && codeBuf[codeBuf.length - 1].trim() === '') codeBuf.pop();
      out.push(`<pre><code${codeLang ? ` class="language-${codeLang}"` : ''}>${codeBuf.join('\n')}</code></pre>`);
    }
    return out.join('\n');
  }

  let lastPresetOpts: { presetMarkdown?: string; presetTitle?: string } | undefined;

  function enterReading(opts?: { presetMarkdown?: string; presetTitle?: string }) {
    if (active) return;
    if (opts?.presetMarkdown) lastPresetOpts = opts;
    active = true;
    panelCollapsed = false;
    // 每次进入生成一个新对话 session；首轮问题会带上正文，后续轮由服务端按此拼历史
    chatSessionId = 'read-' + genId();
    chatBusy = false;
    firstChatTurn = true;
    removeReenterButton();
    removeExpandTab();

    // presetMarkdown：飞书文档全文，background 预先抓的 Markdown，直接跳过 DOM 检测
    if (opts?.presetMarkdown || false) {
      let md = String(opts?.presetMarkdown || '');
      const titleStr = String(opts?.presetTitle || document.title || '');
      // 去掉正文中的首个 # 标题行（前端已单独渲染 presetTitle）
      md = md.replace(/^#\s+[^\n]*\n*/, '');

      // 先尝试从 storage 恢复已有 summary（避免退出再进入时重复请求 AI）
      loadContent((cached) => {
        if (cached?.summary) summaryText = cached.summary;
        const savedScrollTop = cached?.scrollTop;

        const dark = isDarkMode();
        const titleHtml = '<h1>' + escapeHtml(titleStr) + '</h1>';
        let hostStr = '';
        try { hostStr = new URL(currentUrl).hostname; } catch {}
        const metaHtml = '<p style="font-size:13px;color:#9ca3af;border-bottom:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';padding-bottom:16px;margin-bottom:24px">' +
          escapeHtml(hostStr) + ' · 已从飞书 API 拉取全文</p>';
        const html = titleHtml + metaHtml + mdToHtml(md);
        createReader(html);
        if (savedScrollTop) {
          const reader = document.getElementById(READER_ID);
          if (reader) requestAnimationFrame(() => { reader.scrollTop = savedScrollTop; });
        }
        saveContent();
        // Reserve panel space
        const reader = document.getElementById(READER_ID);
        if (reader) reader.style.paddingRight = PANEL_WIDTH + 'px';
        createProgressBar();
        createPanel();
        setupScrollSpy();
        setupSelectionListener();
        setupMarkClickListener();
        setupKeyboard();
        const summaryEl = getPanelEl('__ethan_reading_summary_content');
        if (summaryEl) requestSummary(summaryEl);
      });
      return;
    }

    loadContent((cached) => {
      if (cached) {
        // Load from cache
        summaryText = cached.summary || '';
        createReader(cached.html);
        // 恢复滚动位置
        if (cached.scrollTop) {
          const reader = document.getElementById(READER_ID);
          if (reader) requestAnimationFrame(() => { reader.scrollTop = cached.scrollTop!; });
        }
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
      const summaryEl = getPanelEl('__ethan_reading_summary_content');
      if (summaryEl) requestSummary(summaryEl);
    });
  }

  function exitReading() {
    if (!active) return;
    active = false;
    panelCollapsed = false;
    chatMode = false;
    if (summaryCountdownTimer) { clearInterval(summaryCountdownTimer); summaryCountdownTimer = null; }

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
      if (msg.type === 'start') {
        if (active) {
          // 已在阅读模式：如果面板折叠了就展开，否则不做重复进入
          const panel = document.getElementById(PANEL_ID);
          if (panel && panelCollapsed) {
            panel.style.transform = 'translateX(0)';
            panelCollapsed = false;
            const reader = document.getElementById(READER_ID);
            if (reader) reader.style.paddingRight = PANEL_WIDTH + 'px';
          }
        } else {
          enterReading({ presetMarkdown: msg.presetMarkdown, presetTitle: msg.presetTitle });
        }
      }
      return false;
    });
  }
})();
