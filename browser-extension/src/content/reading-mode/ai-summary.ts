// @ts-nocheck
/* eslint-disable */

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
    h = h.replace(/`([^`]+?)`/g, '<code style="background:rgba(127,127,127,0.15);padding:1px 4px;border-radius:3px">$1</code>');
    // Bullet & Numbered lists (supports -, *, •, and 1. 2. 3.)
    h = h.replace(/^[-*•]\s*(.+)$/gm, '<div style="padding-left:12px;margin:2px 0">• $1</div>');
    h = h.replace(/^(\d+)\.\s*(.+)$/gm, '<div style="padding-left:12px;margin:2px 0"><span style="color:#0d9488;font-weight:500">$1.</span> $2</div>');
    // Remove redundant newlines before & after block tags
    h = h.replace(/(<\/(?:h3|h4|div|pre)>)\s*\n+/gi, '$1');
    h = h.replace(/\n+\s*(<(?:h3|h4|div|pre)[\s>])/gi, '$1');
    // Collapse consecutive newlines and convert remaining to <br>
    h = h.replace(/\n{2,}/g, '\n');
    h = h.replace(/\n/g, '<br>');
    return h;
  }

  // ========== Summary (with cache) ==========

  let summaryCountdownTimer: ReturnType<typeof setInterval> | null = null;

  function requestSummary(target: HTMLElement) {
    if (summaryText) { target.innerHTML = renderMdSimple(summaryText); return; }
    showSummaryCountdown(target);
  }

  function showSummaryCountdown(target: HTMLElement) {
    // 清理可能残留的旧 timer，避免重复进入时 interval 泄漏
    if (summaryCountdownTimer) { clearInterval(summaryCountdownTimer); summaryCountdownTimer = null; }
    let remaining = 5;
    const dark = isDarkMode();
    // structured 标志：首次创建完整 DOM，后续只更新数字，避免每秒重建丢失按钮 focus
    let structured = false;

    const bindButtons = () => {
      const cancelBtn = getPanelEl('__ethan_summary_cancel');
      const startBtn = getPanelEl('__ethan_summary_start');
      if (cancelBtn) cancelBtn.onclick = () => {
        // TODO(竞态窗口): 这里只清 timer 但无法撤销已经 setTimeout 排队的 doRequestSummary。
        //   归零瞬间（remaining==0 时已经 setTimeout 250ms 之后触发 doRequestSummary）点击取消，
        //   请求照样会发出。修复：引入全局 summaryCancelled 标志，doRequestSummary 入口检查。
        //   目前概率很低（<1%），暂不修。
        if (summaryCountdownTimer) { clearInterval(summaryCountdownTimer); summaryCountdownTimer = null; }
        target.innerHTML = '<div style="text-align:center;padding:16px 0;color:' + (dark ? '#6b7280' : '#9ca3af') + ';font-size:12px">' +
          '已取消自动解读 · <a id="__ethan_summary_retry" href="#" style="color:#0d9488;text-decoration:none">点此手动开始</a></div>';
        structured = false;
        const retry = getPanelEl('__ethan_summary_retry');
        if (retry) retry.onclick = (e) => { e.preventDefault(); doRequestSummary(target); };
      };
      if (startBtn) startBtn.onclick = () => {
        if (summaryCountdownTimer) { clearInterval(summaryCountdownTimer); summaryCountdownTimer = null; }
        doRequestSummary(target);
      };
    };

    const render = () => {
      if (!structured) {
        target.innerHTML = '<div style="text-align:center;padding:16px 0">' +
          '<div style="font-size:13px;color:' + (dark ? '#9ca3af' : '#6b7280') + ';margin-bottom:12px">' +
          '<span id="__ethan_summary_count" style="font-size:20px;font-weight:600;color:' + (dark ? '#e6e8ec' : '#1f2430') + '">' + remaining + '</span> 秒后开始解读文章</div>' +
          '<div style="display:flex;gap:8px;justify-content:center">' +
          '<button id="__ethan_summary_cancel" style="padding:6px 16px;border:1px solid ' + (dark ? '#4b5563' : '#d1d5db') + ';border-radius:8px;background:' + (dark ? '#2a2e37' : '#fff') + ';color:' + (dark ? '#e6e8ec' : '#374151') + ';font-size:12px;cursor:pointer">取消</button>' +
          '<button id="__ethan_summary_start" style="padding:6px 16px;border:none;border-radius:8px;background:#0d9488;color:#fff;font-size:12px;cursor:pointer;font-weight:500">立即开始</button>' +
          '</div></div>';
        structured = true;
        bindButtons();
      } else {
        // 只更新数字 span，不重建 DOM，保留按钮 focus 状态
        const countEl = getPanelEl('__ethan_summary_count');
        if (countEl) countEl.textContent = String(remaining);
      }
    };

    render();
    summaryCountdownTimer = setInterval(() => {
      remaining--;
      if (remaining <= 0) {
        // 归零时先显示 0 一帧，再触发请求，避免用户看不到 0
        const countEl = getPanelEl('__ethan_summary_count');
        if (countEl) countEl.textContent = String(remaining);
        clearInterval(summaryCountdownTimer!); summaryCountdownTimer = null;
        setTimeout(() => doRequestSummary(target), 250);
      } else {
        render();
      }
    }, 1000);
  }

  function doRequestSummary(target: HTMLElement) {
    const text = contentEl?.innerText || cleanedText;
    const prompt = '\u8fd9\u662f\u4e00\u7bc7\u6587\u7ae0\u7684\u6b63\u6587\uff0c\u8bf7\u7528\u4e2d\u6587\u56de\u590d\u3002\u8bf7\u4e25\u683c\u6309\u4ee5\u4e0b\u4e09\u4e2a\u90e8\u5206\u8f93\u51fa\uff1a\n\n## \u6982\u8ff0\n\u7528 1-2 \u53e5\u8bdd\u6982\u62ec\u6587\u7ae0\u4e3b\u65e8\u3002\n\n## \u7ed3\u6784\n\u5206\u5757\u5217\u51fa\u6587\u7ae0\u7ed3\u6784\uff08\u6bcf\u5757\u4e00\u884c\uff0c\u7528\u65e0\u5e8f\u5217\u8868\uff09\u3002\n\n## \u91cd\u70b9\n\u6307\u51fa 1-3 \u5904\u6700\u503c\u5f97\u5173\u6ce8\u7684\u5185\u5bb9\u3002\n\n\u6b63\u6587\u5982\u4e0b\uff1a\n\n' + text.slice(0, 8000);
    requestChat(prompt, target, {
      sessionId: chatSessionId,
      onDone: (result) => {
        summaryText = result;
        saveContent();
      },
    });
  }

  // ========== Save Knowledge ==========

  function saveKnowledge() {
    if (!contentEl) return;
    const btn = getPanelEl('__ethan_reading_save_kb') as HTMLButtonElement | null;
    if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }
    const title = document.title || 'Untitled';
    const md = ethanReader().htmlToMarkdown(contentEl);
    chrome.runtime.sendMessage({ type: 'reading:saveKnowledge', title, content: md }, (resp) => {
      if (resp?.ok) { showToast('已存入知识库'); if (btn) btn.textContent = '✓ 已保存'; }
      else { showToast('保存失败'); if (btn) { btn.disabled = false; btn.textContent = '📥 存知识库'; } }
    });
  }
