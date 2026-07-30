/* eslint-disable */
// 页面内结果面板（经典脚本，不能 import）：右上角浮层，流式展示指令/对话结果。
//
// 所有页面内 AI 指令（summary/翻译/解释/写作…）的结果都往这里灌。挂到
// window.__ethanResultPanel，供 background 注入后调用。UI 风格对齐 overlay.ts
// 的卡片，但独立 DOM（id __ethan_result_panel）与消息通道（target='result'）。
//
// 消息协议（background → 本脚本，均带 target:'result'）：
//   { type:'chatChunk', requestId, delta }  流式追加
//   { type:'chatDone',  requestId, error? } 本轮结束
// 面板 → background：
//   { type:'result:chat', requestId, prompt, sessionId }  追问（走多轮）
//   { type:'reading:saveKnowledge', title, content }       存知识库（复用现有通道）

interface ResultItem {
  title: string;       // 指令名，如「摘要」「翻译」
  sessionId: string;   // 多轮追问共用一个 session
  markdown: string;    // 累积的结果文本
  done: boolean;
  error?: string;
}

interface EthanResultPanelApi {
  // 开一条新结果：显示面板、切到新条目、返回该条目的 requestId 供 background 回推。
  newResult(opts: { title: string; sessionId: string; requestId: string }): void;
  show(): void;
  hide(): void;
}

(function () {
  const w = window as any;
  if (w.__ethanResultPanel) return;

  const PANEL_ID = '__ethan_result_panel';
  const Z = 2147483646;

  let items: ResultItem[] = [];
  let cur = -1;                       // 当前查看的结果索引
  let activeReqId = '';               // 正在流式接收的 requestId
  const MAX_ITEMS = 20;

  function isDark(): boolean {
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function escapeHtml(s: string): string {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function genId(): string {
    return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  }

  // 精简 markdown 渲染（标题/加粗/行内代码/无序列表/换行）。
  // 注：reading-mode 里另有一份 renderMdSimple，暂不统一（未来抽公共）。
  function renderMd(md: string): string {
    let h = escapeHtml(md);
    h = h.replace(/```([\s\S]*?)```/g, (_m, code) =>
      '<pre style="background:rgba(127,127,127,0.12);padding:8px 10px;border-radius:6px;overflow-x:auto;margin:6px 0"><code>' + code.trim() + '</code></pre>');
    h = h.replace(/^### (.+)$/gm, '<h4 style="margin:8px 0 4px;font-size:13px;font-weight:600">$1</h4>');
    h = h.replace(/^## (.+)$/gm, '<h3 style="margin:10px 0 4px;font-size:14px;font-weight:600">$1</h3>');
    h = h.replace(/^# (.+)$/gm, '<h3 style="margin:10px 0 4px;font-size:15px;font-weight:700">$1</h3>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/`([^`]+?)`/g, '<code style="background:rgba(127,127,127,0.15);padding:1px 4px;border-radius:3px">$1</code>');
    h = h.replace(/^[-*] (.+)$/gm, '<div style="padding-left:12px;margin:2px 0">• $1</div>');
    h = h.replace(/\n/g, '<br>');
    return h;
  }

  // ── DOM ──────────────────────────────────────────────────────

  function build(): HTMLElement {
    const dark = isDark();
    const host = document.createElement('div');
    host.id = PANEL_ID;
    host.style.cssText = [
      'position:fixed', 'top:16px', 'right:16px', 'width:360px', 'max-height:78vh',
      'display:flex', 'flex-direction:column', 'z-index:' + Z,
      'font-family:-apple-system,system-ui,"PingFang SC",sans-serif', 'font-size:13px',
      'color:' + (dark ? '#e6e8ec' : '#1f2430'),
      'background:' + (dark ? 'rgba(28,31,38,0.98)' : 'rgba(255,255,255,0.98)'),
      'border:1px solid ' + (dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.12)'),
      'border-radius:12px', 'box-shadow:0 8px 32px rgba(0,0,0,0.22)',
      'backdrop-filter:blur(8px)', 'overflow:hidden',
    ].join(';');

    host.innerHTML = [
      // header
      '<div id="' + PANEL_ID + '_head" style="display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid ' + (dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)') + ';flex-shrink:0">',
      '  <span style="font-size:15px">🦊</span>',
      '  <strong id="' + PANEL_ID + '_title" style="flex:1;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">结果</strong>',
      '  <button id="' + PANEL_ID + '_prev" title="上一条" style="border:none;background:none;cursor:pointer;color:inherit;font-size:13px;padding:2px 5px;opacity:0.6">‹</button>',
      '  <span id="' + PANEL_ID + '_idx" style="font-size:11px;opacity:0.6;min-width:28px;text-align:center">-</span>',
      '  <button id="' + PANEL_ID + '_next" title="下一条" style="border:none;background:none;cursor:pointer;color:inherit;font-size:13px;padding:2px 5px;opacity:0.6">›</button>',
      '  <button id="' + PANEL_ID + '_close" title="关闭" style="border:none;background:none;cursor:pointer;color:inherit;font-size:14px;padding:2px 6px">✕</button>',
      '</div>',
      // body
      '<div id="' + PANEL_ID + '_body" style="flex:1;overflow-y:auto;padding:12px;line-height:1.6;min-height:0;word-break:break-word"></div>',
      // actions
      '<div style="display:flex;gap:6px;padding:8px 12px;border-top:1px solid ' + (dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.08)') + ';flex-shrink:0">',
      '  <button id="' + PANEL_ID + '_copy" style="flex:none;padding:5px 10px;border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';border-radius:6px;background:none;color:inherit;cursor:pointer;font-size:12px">复制</button>',
      '  <button id="' + PANEL_ID + '_kb" style="flex:none;padding:5px 10px;border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';border-radius:6px;background:none;color:inherit;cursor:pointer;font-size:12px">存知识库</button>',
      '</div>',
      // follow-up
      '<div style="display:flex;gap:6px;align-items:flex-end;padding:0 12px 12px">',
      '  <textarea id="' + PANEL_ID + '_input" rows="1" placeholder="追问…" style="flex:1;resize:none;padding:7px 9px;border-radius:8px;border:1px solid ' + (dark ? '#374151' : '#e5e7eb') + ';background:' + (dark ? '#2a2e37' : '#fff') + ';color:inherit;font-size:13px;font-family:inherit;line-height:1.4;max-height:80px;outline:none"></textarea>',
      '  <button id="' + PANEL_ID + '_send" style="flex:none;padding:7px 12px;border:none;border-radius:8px;background:#0d9488;color:#fff;font-size:13px;cursor:pointer">发送</button>',
      '</div>',
    ].join('');

    document.documentElement.appendChild(host);

    (host.querySelector('#' + PANEL_ID + '_close') as HTMLElement).onclick = hide;
    (host.querySelector('#' + PANEL_ID + '_prev') as HTMLElement).onclick = () => nav(-1);
    (host.querySelector('#' + PANEL_ID + '_next') as HTMLElement).onclick = () => nav(1);
    (host.querySelector('#' + PANEL_ID + '_copy') as HTMLElement).onclick = copyCur;
    (host.querySelector('#' + PANEL_ID + '_kb') as HTMLElement).onclick = saveKb;

    const input = host.querySelector('#' + PANEL_ID + '_input') as HTMLTextAreaElement;
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 80) + 'px';
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendFollowUp(); }
    });
    (host.querySelector('#' + PANEL_ID + '_send') as HTMLElement).onclick = sendFollowUp;

    return host;
  }

  function el(id: string): HTMLElement | null {
    return document.getElementById(PANEL_ID + '_' + id);
  }
  function panel(): HTMLElement {
    return document.getElementById(PANEL_ID) || build();
  }

  function show() { panel().style.display = 'flex'; }
  function hide() {
    const p = document.getElementById(PANEL_ID);
    if (p) p.style.display = 'none';
  }

  // ── 渲染 ─────────────────────────────────────────────────────

  function render() {
    if (cur < 0 || !items[cur]) return;
    const it = items[cur];
    const title = el('title'); if (title) title.textContent = it.title;
    const idx = el('idx'); if (idx) idx.textContent = (cur + 1) + '/' + items.length;
    const body = el('body');
    if (body) {
      if (it.error) {
        body.innerHTML = '<span style="color:#ef4444">错误: ' + escapeHtml(it.error) + '</span>';
      } else if (!it.markdown) {
        body.innerHTML = '<span style="color:#9aa0aa;font-style:italic">思考中…</span>';
      } else {
        body.innerHTML = renderMd(it.markdown);
      }
      body.scrollTop = body.scrollHeight;
    }
  }

  function nav(dir: number) {
    const n = cur + dir;
    if (n < 0 || n >= items.length) return;
    cur = n;
    render();
  }

  function copyCur() {
    if (cur < 0 || !items[cur]) return;
    navigator.clipboard.writeText(items[cur].markdown).then(() => flash('copy', '已复制'));
  }

  function saveKb() {
    if (cur < 0 || !items[cur] || !items[cur].markdown) return;
    const it = items[cur];
    const title = it.title + ' · ' + (document.title || '');
    chrome.runtime.sendMessage(
      { type: 'reading:saveKnowledge', title, content: it.markdown },
      (resp) => flash('kb', resp?.ok ? '已存 ✓' : '失败'),
    );
  }

  function flash(btnId: string, text: string) {
    const b = el(btnId) as HTMLButtonElement | null;
    if (!b) return;
    const old = b.textContent;
    b.textContent = text;
    setTimeout(() => { b.textContent = old; }, 1500);
  }

  function sendFollowUp() {
    const input = el('input') as HTMLTextAreaElement | null;
    if (!input || cur < 0 || !items[cur]) return;
    const q = input.value.trim();
    if (!q || activeReqId) return;   // 有正在进行的请求则忽略
    input.value = '';
    input.style.height = 'auto';

    const base = items[cur];
    // 追问延用当前结果的 session，走多轮
    const reqId = genId();
    activeReqId = reqId;
    const it: ResultItem = { title: '追问：' + q.slice(0, 20), sessionId: base.sessionId, markdown: '', done: false };
    pushItem(it);
    chrome.runtime.sendMessage({ type: 'result:chat', requestId: reqId, prompt: q, sessionId: base.sessionId });
  }

  function pushItem(it: ResultItem) {
    items.push(it);
    if (items.length > MAX_ITEMS) items.shift();
    cur = items.length - 1;
    show();
    render();
  }

  // ── 对外 API ─────────────────────────────────────────────────

  function newResult(opts: { title: string; sessionId: string; requestId: string }) {
    activeReqId = opts.requestId;
    pushItem({ title: opts.title, sessionId: opts.sessionId, markdown: '', done: false });
  }

  // ── 消息监听 ─────────────────────────────────────────────────

  function onMessage(msg: any) {
    if (msg?.target !== 'result') return;
    if (msg.type === 'chatChunk' && msg.requestId === activeReqId) {
      const it = items[cur];
      if (it && !it.done) { it.markdown += msg.delta || ''; render(); }
    } else if (msg.type === 'chatDone' && msg.requestId === activeReqId) {
      const it = items[cur];
      if (it) { it.done = true; if (msg.error) it.error = msg.error; render(); }
      activeReqId = '';
    }
  }

  if (!w.__ethanResultListenerAdded) {
    w.__ethanResultListenerAdded = true;
    chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
      onMessage(msg);
      return false;
    });
  }

  const api: EthanResultPanelApi = { newResult, show, hide };
  w.__ethanResultPanel = api;
})();
