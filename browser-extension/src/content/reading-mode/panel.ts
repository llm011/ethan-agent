// @ts-nocheck
/* eslint-disable */

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
      zIndex: String(Z_PANEL), overflow: 'hidden',
      background: dark ? '#1c1f26' : '#fafafa',
      color: dark ? '#e6e8ec' : '#1f2430',
      borderLeft: '1px solid ' + (dark ? '#333' : '#e5e7eb'),
      boxShadow: '-4px 0 24px rgba(0,0,0,0.1)',
      padding: '16px 14px', fontFamily: '-apple-system, system-ui, "PingFang SC", sans-serif',
      fontSize: '13px', lineHeight: '1.6',
      display: 'flex', flexDirection: 'column',
      transform: 'translateX(100%)', transition: 'transform 0.3s cubic-bezier(0.4,0,0.2,1)',
    });

    const charCount = (contentEl?.innerText || '').length;
    const formattedChar = charCount > 10000 ? (charCount / 10000).toFixed(1) + '万' : charCount.toLocaleString();
    const readTime = estimateReadTime(contentEl?.innerText || '');

    panel.innerHTML = [
      '<!-- Header -->',
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-shrink:0">',
      '  <div style="display:flex;align-items:center;gap:6px;min-width:0;flex:1">',
      '    <div style="width:7px;height:7px;border-radius:50%;background:#0d9488;flex-shrink:0"></div>',
      '    <strong style="font-size:14px;font-weight:600;flex-shrink:0">辅助阅读</strong>',
      '    <span style="font-size:11px;color:' + (dark ? '#6b7280' : '#9ca3af') + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis">约 ' + formattedChar + ' 字 · ' + readTime + '分钟</span>',
      '  </div>',
      '  <div style="display:flex;gap:4px;align-items:center;position:relative;flex-shrink:0">',
      '    <button id="__ethan_reading_settings_toggle" style="border:none;background:' + (dark ? '#2a2e37' : '#f3f4f6') + ';cursor:pointer;font-size:13px;padding:4px 7px;border-radius:6px;color:inherit" title="设置与更多">⚙</button>',
      '    <button id="__ethan_reading_collapse" style="border:none;background:' + (dark ? '#2a2e37' : '#f3f4f6') + ';cursor:pointer;font-size:13px;padding:4px 7px;border-radius:6px;color:inherit" title="折叠">❯</button>',
      '    <button id="__ethan_reading_close" style="border:none;background:' + (dark ? '#2a2e37' : '#f3f4f6') + ';cursor:pointer;font-size:13px;padding:4px 7px;border-radius:6px;color:inherit" title="退出 (Esc)">✕</button>',
      '    <!-- Popover Settings Menu -->',
      '    <div id="__ethan_reading_settings_menu" style="display:none;position:absolute;top:30px;right:0;z-index:20;width:190px;padding:6px;border-radius:10px;background:' + (dark ? '#2a2e37' : '#fff') + ';border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';box-shadow:0 10px 25px rgba(0,0,0,0.15)">',
      '      <button id="__ethan_reading_clear_cache" style="width:100%;text-align:left;padding:8px 10px;border:none;background:none;border-radius:6px;font-size:12px;cursor:pointer;color:' + (dark ? '#e6e8ec' : '#374151') + ';display:flex;align-items:center;gap:6px">',
      '        <span>🔄</span> <span>清除缓存（重新加载）</span>',
      '      </button>',
      '      <div style="margin-top:4px;padding:6px 10px;border-top:1px solid ' + (dark ? '#374151' : '#f3f4f6') + ';font-size:11px;color:' + (dark ? '#6b7280' : '#9ca3af') + '">',
      '        💡 正文可直接编辑 · Esc 退出',
      '      </div>',
      '    </div>',
      '  </div>',
      '</div>',
      '<!-- Segmented Control Bar -->',
      '<div style="display:flex;padding:3px;border-radius:10px;background:' + (dark ? '#2a2e37' : '#f3f4f6') + ';margin-bottom:12px;flex-shrink:0">',
      '  <button class="__ethan_main_tab" data-tab="summary" style="flex:1;padding:6px 0;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;background:' + (dark ? '#1c1f26' : '#fff') + ';color:#0d9488;box-shadow:0 1px 3px rgba(0,0,0,0.08);transition:all 0.2s">AI 解读</button>',
      '  <button class="__ethan_main_tab" data-tab="toc" style="flex:1;padding:6px 0;border:none;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;background:none;color:' + (dark ? '#9ca3af' : '#6b7280') + ';transition:all 0.2s">目录</button>',
      '  <button class="__ethan_main_tab" data-tab="anno" style="flex:1;padding:6px 0;border:none;border-radius:8px;font-size:12px;font-weight:500;cursor:pointer;background:none;color:' + (dark ? '#9ca3af' : '#6b7280') + ';transition:all 0.2s">标注 <span id="__ethan_anno_count_badge" style="font-size:10px;padding:1px 5px;border-radius:10px;background:' + (dark ? '#374151' : '#e5e7eb') + ';color:inherit">0</span></button>',
      '</div>',
      '<!-- Main Scrollable Body -->',
      '<div style="flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden">',
      '  <div style="flex:1;min-height:0;overflow-y:auto;padding-right:2px">',
      '    <!-- Tab 1: AI 解读 -->',
      '    <div id="__ethan_tab_summary" style="display:block">',
      '      <div style="padding:12px;border-radius:12px;background:' + (dark ? '#222630' : '#fff') + ';border:1px solid ' + (dark ? '#333' : '#e5e7eb') + ';box-shadow:0 1px 4px rgba(0,0,0,0.03)">',
      '        <div style="display:flex;gap:12px;margin-bottom:10px;border-bottom:1px solid ' + (dark ? '#2a2e37' : '#f3f4f6') + ';padding-bottom:8px">',
      '          <button class="__ethan_sum_tab" data-section="overview" style="border:none;background:none;padding:2px 0;font-size:12px;font-weight:600;letter-spacing:0.5px;cursor:pointer;color:#0d9488;border-bottom:2px solid #0d9488">概述</button>',
      '          <button class="__ethan_sum_tab" data-section="structure" style="border:none;background:none;padding:2px 0;font-size:12px;font-weight:600;letter-spacing:0.5px;cursor:pointer;color:' + (dark ? '#6b7280' : '#9ca3af') + ';border-bottom:2px solid transparent">结构</button>',
      '          <button class="__ethan_sum_tab" data-section="keypoints" style="border:none;background:none;padding:2px 0;font-size:12px;font-weight:600;letter-spacing:0.5px;cursor:pointer;color:' + (dark ? '#6b7280' : '#9ca3af') + ';border-bottom:2px solid transparent">重点</button>',
      '        </div>',
      '        <div id="__ethan_reading_summary_content" style="font-size:13px;max-height:360px;overflow-y:auto;scroll-behavior:smooth;position:relative"></div>',
      '      </div>',
      '    </div>',
      '    <!-- Tab 2: 目录 -->',
      '    <div id="__ethan_tab_toc" style="display:none">',
      '      <div style="padding:10px 12px;border-radius:12px;background:' + (dark ? '#222630' : '#fff') + ';border:1px solid ' + (dark ? '#333' : '#e5e7eb') + '">',
      '        <div id="__ethan_reading_toc" style="max-height:380px;overflow-y:auto"></div>',
      '      </div>',
      '    </div>',
      '    <!-- Tab 3: 标注 -->',
      '    <div id="__ethan_tab_anno" style="display:none">',
      '      <div style="padding:12px;border-radius:12px;background:' + (dark ? '#222630' : '#fff') + ';border:1px solid ' + (dark ? '#333' : '#e5e7eb') + '">',
      '        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">',
      '          <div style="font-weight:600;font-size:12px;color:' + (dark ? '#9ca3af' : '#6b7280') + '">标注与书签</div>',
      '          <div id="__ethan_reading_anno_filter" style="display:flex;gap:4px"></div>',
      '        </div>',
      '        <div id="__ethan_reading_anno_list" style="max-height:340px;overflow-y:auto"></div>',
      '      </div>',
      '    </div>',
      '  </div>',
      '  <!-- QA Section ("向 Ethan 提问") -->',
      '  <div style="margin-top:12px;padding:12px;border-radius:12px;background:' + (dark ? '#222630' : '#fff') + ';border:1px solid ' + (dark ? '#333' : '#e5e7eb') + ';flex-shrink:0">',
      '    <div style="font-weight:600;font-size:12px;color:' + (dark ? '#9ca3af' : '#6b7280') + ';margin-bottom:6px">向 Ethan 提问</div>',
      '    <div id="__ethan_reading_chat_log" style="max-height:160px;overflow-y:auto;margin-bottom:8px"></div>',
      '    <div style="display:flex;gap:6px;align-items:flex-end">',
      '      <textarea id="__ethan_reading_chat_input" rows="1" placeholder="就这篇文章提问…" style="flex:1;resize:none;padding:8px 10px;border-radius:8px;border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';background:' + (dark ? '#1c1f26' : '#fafafa') + ';color:inherit;font-size:12px;font-family:inherit;line-height:1.4;max-height:80px;outline:none"></textarea>',
      '      <button id="__ethan_reading_chat_send" style="flex:none;padding:7px 14px;border:none;border-radius:8px;background:#0d9488;color:#fff;font-size:12px;font-weight:500;cursor:pointer;transition:opacity 0.2s">发送</button>',
      '    </div>',
      '  </div>',
      '</div>',
      '<!-- Footer Action Bar -->',
      '<div style="padding-top:12px;margin-top:12px;border-top:1px solid ' + (dark ? '#333' : '#e5e7eb') + ';flex-shrink:0">',
      '  <button id="__ethan_reading_save_kb" style="width:100%;padding:10px;border:none;border-radius:10px;font-size:13px;font-weight:600;cursor:pointer;background:linear-gradient(135deg,#0d9488,#06b6d4);color:#fff;box-shadow:0 2px 8px rgba(13,148,136,0.25);transition:opacity 0.2s">存知识库</button>',
      '</div>',
    ].join('\n');

    document.body.appendChild(panel);
    requestAnimationFrame(() => { panel.style.transform = 'translateX(0)'; });

    // Render TOC & Annotations
    refreshToc();
    refreshAnnotations();

    // Header & Settings Events
    document.getElementById('__ethan_reading_close')!.onclick = exitReading;
    document.getElementById('__ethan_reading_collapse')!.onclick = collapsePanel;
    document.getElementById('__ethan_reading_save_kb')!.onclick = saveKnowledge;

    const settingsBtn = document.getElementById('__ethan_reading_settings_toggle');
    const settingsMenu = document.getElementById('__ethan_reading_settings_menu');
    if (settingsBtn && settingsMenu) {
      settingsBtn.onclick = (e) => {
        e.stopPropagation();
        settingsMenu.style.display = settingsMenu.style.display === 'none' ? 'block' : 'none';
      };
      document.addEventListener('click', (e) => {
        if (settingsMenu.style.display !== 'none' && !settingsMenu.contains(e.target) && e.target !== settingsBtn) {
          settingsMenu.style.display = 'none';
        }
      });
    }

    document.getElementById('__ethan_reading_clear_cache')!.onclick = () => {
      chrome.storage.local.remove([storageKey()], () => {
        showToast('已清除缓存');
        exitReading();
        setTimeout(() => enterReading(), 400);
      });
    };

    // Main Tab Bar Switching
    panel.querySelectorAll<HTMLButtonElement>('.__ethan_main_tab').forEach(tab => {
      tab.onclick = () => {
        const targetTab = tab.dataset.tab;
        panel.querySelectorAll<HTMLButtonElement>('.__ethan_main_tab').forEach(t => {
          const active = t.dataset.tab === targetTab;
          t.style.background = active ? (dark ? '#1c1f26' : '#fff') : 'none';
          t.style.color = active ? '#0d9488' : (dark ? '#9ca3af' : '#6b7280');
          t.style.fontWeight = active ? '600' : '500';
          t.style.boxShadow = active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none';
        });

        ['summary', 'toc', 'anno'].forEach(t => {
          const el = document.getElementById('__ethan_tab_' + t);
          if (el) el.style.display = t === targetTab ? 'block' : 'none';
        });
      };
    });

    // Summary sub-tab clicks → scroll to section anchors
    const dark2 = isDarkMode();
    panel.querySelectorAll<HTMLButtonElement>('.__ethan_sum_tab').forEach(tab => {
      tab.onclick = () => {
        const section = tab.dataset.section;
        const container = document.getElementById('__ethan_reading_summary_content');
        if (!container) return;
        panel.querySelectorAll<HTMLButtonElement>('.__ethan_sum_tab').forEach(t => {
          t.style.color = dark2 ? '#6b7280' : '#9ca3af';
          t.style.borderBottomColor = 'transparent';
        });
        tab.style.color = '#0d9488';
        tab.style.borderBottomColor = '#0d9488';
        const anchor = container.querySelector('[data-section="' + section + '"]') as HTMLElement | null;
        if (anchor) {
          container.scrollTo({ top: anchor.offsetTop, behavior: 'smooth' });
        } else {
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

  // ========== 标注管理（筛选/跳转/删除） ==========

  let annoFilter: 'all' | 'bookmark' = 'all';

  function collectAnnotations(): { el: HTMLElement; type: string; color: string; note?: string; text: string }[] {
    if (!contentEl) return [];
    const marks = Array.from(contentEl.querySelectorAll<HTMLElement>('mark[data-anno-type]'));
    return marks.map(m => ({
      el: m,
      type: m.dataset.annoType || 'highlight',
      color: ['yellow', 'blue', 'green', 'pink'].find(c => m.classList.contains('anno-' + c)) || 'yellow',
      note: m.dataset.note,
      text: (m.textContent || '').trim().slice(0, 60),
    }));
  }

  function refreshAnnotations() {
    const listEl = document.getElementById('__ethan_reading_anno_list');
    const filterEl = document.getElementById('__ethan_reading_anno_filter');
    if (!listEl || !filterEl) return;
    const dark = isDarkMode();
    const all = collectAnnotations();

    // Update main tab badge
    const badgeEl = document.getElementById('__ethan_anno_count_badge');
    if (badgeEl) badgeEl.textContent = String(all.length);

    // Filter tabs
    const bookmarkCount = all.filter(a => a.type === 'bookmark').length;
    const tabs: { key: 'all' | 'bookmark'; label: string }[] = [
      { key: 'all', label: '\u5168\u90e8 ' + all.length },
      { key: 'bookmark', label: '\u4e66\u7b7e ' + bookmarkCount },
    ];
    filterEl.innerHTML = '';
    tabs.forEach(t => {
      const btn = document.createElement('button');
      btn.textContent = t.label;
      const active = annoFilter === t.key;
      Object.assign(btn.style, {
        border: 'none', background: active ? '#0d9488' : (dark ? '#2a2e37' : '#f3f4f6'),
        color: active ? '#fff' : (dark ? '#9ca3af' : '#6b7280'),
        padding: '2px 6px', borderRadius: '4px', fontSize: '11px', cursor: 'pointer',
      });
      btn.onclick = () => { annoFilter = t.key; refreshAnnotations(); };
      filterEl.appendChild(btn);
    });

    // List
    const filtered = annoFilter === 'bookmark' ? all.filter(a => a.type === 'bookmark') : all;
    if (!filtered.length) {
      listEl.innerHTML = '<div style="color:' + (dark ? '#6b7280' : '#9ca3af') + ';font-size:12px;padding:8px 0">\u6682\u65e0\u6807\u6ce8</div>';
      return;
    }
    listEl.innerHTML = '';
    filtered.forEach(a => {
      const div = document.createElement('div');
      Object.assign(div.style, {
        display: 'flex', alignItems: 'flex-start', gap: '6px',
        padding: '6px 8px', borderRadius: '6px', marginBottom: '4px',
        cursor: 'pointer', transition: 'background 0.15s',
        background: dark ? '#2a2e37' : '#fff',
        border: '1px solid ' + (dark ? '#333' : '#e5e7eb'),
      });
      const icon = a.type === 'bookmark' ? '\uD83D\uDD16' : a.type === 'underline' ? 'U\u0332' : a.type === 'strike' ? 'S\u0336' : a.note ? '\uD83D\uDCAC' : '\uD83D\uDCDD';
      const colorDot = a.type === 'highlight' ? '\u25cf' : '';
      const dot = document.createElement('span');
      dot.textContent = icon;
      Object.assign(dot.style, { flexShrink: '0', fontSize: '12px', lineHeight: '1.4' });

      const textWrap = document.createElement('div');
      Object.assign(textWrap.style, { flex: '1', minWidth: '0' });
      const textEl = document.createElement('div');
      textEl.textContent = a.text || '(空)';
      Object.assign(textEl.style, {
        fontSize: '12px', lineHeight: '1.4',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        color: dark ? '#e6e8ec' : '#1f2430',
      });
      textWrap.appendChild(textEl);
      if (a.note) {
        const noteEl = document.createElement('div');
        noteEl.textContent = a.note;
        Object.assign(noteEl.style, {
          fontSize: '11px', color: dark ? '#9ca3af' : '#6b7280', marginTop: '2px',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        });
        textWrap.appendChild(noteEl);
      }
      if (colorDot) {
        const cd = document.createElement('span');
        cd.textContent = colorDot;
        const colors: Record<string, string> = { yellow: '#ca8a04', blue: '#2563eb', green: '#16a34a', pink: '#db2777' };
        cd.style.color = colors[a.color] || '#ca8a04';
        cd.style.marginRight = '2px';
        dot.textContent = colorDot + ' ' + icon;
        dot.style.color = colors[a.color] || '#ca8a04';
      }

      const delBtn = document.createElement('button');
      delBtn.textContent = '\u2715';
      delBtn.title = '\u5220\u9664';
      Object.assign(delBtn.style, {
        border: 'none', background: 'none', cursor: 'pointer',
        fontSize: '11px', color: dark ? '#6b7280' : '#9ca3af', padding: '0 2px', flexShrink: '0',
      });
      delBtn.onmouseenter = () => { delBtn.style.color = '#ef4444'; };
      delBtn.onmouseleave = () => { delBtn.style.color = dark ? '#6b7280' : '#9ca3af'; };
      delBtn.onclick = (e) => {
        e.stopPropagation();
        const parent = a.el.parentNode;
        if (parent) {
          while (a.el.firstChild) parent.insertBefore(a.el.firstChild, a.el);
          parent.removeChild(a.el);
          parent.normalize();
          saveContent();
          refreshAnnotations();
        }
      };

      div.onmouseenter = () => { div.style.background = dark ? '#333' : '#f3f4f6'; };
      div.onmouseleave = () => { div.style.background = dark ? '#2a2e37' : '#fff'; };
      div.onclick = () => {
        const reader = document.getElementById(READER_ID);
        if (reader) {
          // 用 getBoundingClientRect 相对 reader 计算滚动位置，避免 offsetParent 不一致
          const markRect = a.el.getBoundingClientRect();
          const readerRect = reader.getBoundingClientRect();
          const offsetTop = markRect.top - readerRect.top + reader.scrollTop;
          reader.scrollTo({ top: offsetTop - 80, behavior: 'smooth' });
        }
        // Flash highlight
        const orig = a.el.style.background;
        a.el.style.background = 'rgba(13,148,136,0.3)';
        setTimeout(() => { a.el.style.background = orig; }, 1000);
      };
      div.appendChild(dot);
      div.appendChild(textWrap);
      div.appendChild(delBtn);
      listEl.appendChild(div);
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
    tab.textContent = '\u276E';
    tab.title = '\u5c55\u5f00\u9762\u677f';
    tab.onclick = expandPanel;
    document.body.appendChild(tab);
  }

  function removeExpandTab() { document.getElementById(EXPAND_TAB_ID)?.remove(); }
