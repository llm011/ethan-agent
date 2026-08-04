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
    let codeLang = '';
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
        if (i === 1 && cells.every(c => /^:?-{3,}:?$/.test(c))) return;  // 表格对齐行
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
      if (inCode) {
        if (/^```\s*$/.test(line)) {
          inCode = false;
          out.push('</code></pre>');
          continue;
        }
        out.push(escapeHtml(line) + '\n');
        continue;
      }
      const fence = line.match(/^```(\w*)\s*$/);
      if (fence) {
        closeLists(); flushTable();
        inCode = true; codeLang = fence[1] || '';
        out.push(`<pre><code${codeLang ? ` class="language-${codeLang}"` : ''}>`);
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
      // 引用
      if (/^>\s?/.test(line)) {
        closeLists();
        out.push(`<blockquote>${inline(escapeHtml(line.replace(/^>\s?/, '')))}</blockquote>`);
        continue;
      }
      // 无序列表
      if (/^[-*+]\s+/.test(line)) {
        if (inOl) { out.push('</ol>'); inOl = false; }
        if (!inUl) { out.push('<ul>'); inUl = true; }
        out.push(`<li>${inline(escapeHtml(line.replace(/^[-*+]\s+/, '')))}</li>`);
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
      if (!line.trim()) { out.push('<p><br/></p>'); continue; }
      out.push(`<p>${inline(escapeHtml(line))}</p>`);
    }
    flushTable(); closeLists();
    if (inCode) out.push('</code></pre>');
    return out.join('\n');
  }

  function enterReading(opts?: { presetMarkdown?: string; presetTitle?: string }) {
    if (active) return;
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
      // 创建 reader（不经过 loadContent —— loadContent 是按 URL 缓存 HTML，我们这里直接从 Markdown 生成）
      const md = String(opts?.presetMarkdown || '');
      const titleStr = String(opts?.presetTitle || document.title || '');
      const dark = isDarkMode();
      const titleHtml = '<h1>' + escapeHtml(titleStr) + '</h1>';
      let hostStr = '';
      try { hostStr = new URL(currentUrl).hostname; } catch {}
      const metaHtml = '<p style="font-size:13px;color:#9ca3af;border-bottom:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';padding-bottom:16px;margin-bottom:24px">' +
        escapeHtml(hostStr) + ' · 已从飞书 API 拉取全文</p>';
      const html = titleHtml + metaHtml + mdToHtml(md);
      createReader(html);
      // 直接保存内容（沿用同一 storageKey，后续刷新仍能从 loadContent 读回）
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
      return;
    }

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
      if (msg.type === 'start') enterReading({ presetMarkdown: msg.presetMarkdown, presetTitle: msg.presetTitle });
      return false;
    });
  }
})();
